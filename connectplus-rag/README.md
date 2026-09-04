# connectplus-rag

Trusted-knowledge and verification service for **CONNECT Plus**, a digital navigation and referral platform for culturally and linguistically diverse (CALD) seniors.

This repo owns the client's **approved domain list** and everything built from it: the crawled knowledge base, retrieval over it, and the check that decides whether a generated answer is actually supported by it.

[`connectplus-llm`](../connectplus-llm) imports this package and calls it twice per question: once to **retrieve** source material before generating, once to **verify** the answer afterwards. Nothing reaches a senior that this repo has not signed off.

This is a **library, not a service.** Separate repo for separate ownership and git history; at runtime it's two function calls inside the `connectplus-llm` process. No second server, no port, no HTTP between your own repos.

---

## Why this exists

CONNECT Plus does not publish digital literacy content. Trusted content already exists at Be Connected, eSafety, myGov and Scamwatch. The platform's job is to find the right page on one of those sites and have it explained in the senior's language.

That makes this repo the trust boundary. Two rules drive everything here:

- **The approved domain list is enforced in code**, at fetch time and again at verification time. Not in config, not in a comment, not in a seed list. Content from an unapproved domain never enters the index, and a citation pointing outside the list fails verification.
- **Every chunk carries provenance** (source URL, domain, title, fetch date) with no exceptions. Answers shown to seniors must cite where they came from. A chunk without provenance can't be cited, so it's unusable.

## Two jobs

### 1. Retrieve, before generation

Cross-language search over the approved knowledge base. A Mandarin query must hit an English source page, so the embeddings are multilingual and the retrieval is hybrid (vector + keyword).

Returns ranked chunks with provenance and **one confidence number**. Low confidence is how the system knows to refuse rather than bluff.

### 2. Verify, after generation

Grades the LLM's draft answer against the chunks that were actually retrieved. Four checks, all of which must pass:

| Check | Fails when |
|---|---|
| **Grounded** | The answer states a fact that is not in the supplied chunks |
| **Cited** | A citation marker doesn't resolve to a real chunk, or points off the approved domain list |
| **Confident** | Retrieval confidence is below threshold, so there was never good enough source material |
| **Safe** | The answer tells the user to share a password, an MFA code, or payment details |

Fail any of them and the answer is **dropped, not patched**. What the senior gets instead is *"I don't have trusted information on that"* plus a mentor offer. In a scam-and-safety domain a confident wrong answer about myGov is real harm, not a quality bug.

> **Verification is not a substitute for retrieval.** If the LLM answered from its own training data and this repo only graded the result, almost everything would fail as ungrounded, and the failures that slipped through would be the plausible ones. Retrieval feeds the generator the material the grader will measure it against. That's why it's two calls, not one.

## Scope

| Stage | Module | What it does |
|---|---|---|
| 01 | `s01_ingest.py` | Allowlist → robots.txt/sitemap → polite crawl → raw HTML disk cache |
| 02 | `s02_extract.py` | trafilatura strips nav/ads/footers → clean text + provenance + language |
| 03 | `s03_chunk.py` | Heading-aware splits that never cut a numbered procedure |
| 04 | `s04_embed.py` | BGE-m3 embeddings → pgvector HNSW + Postgres `tsvector` |
| 05 | `s05_retrieve.py` | Vector + keyword search, RRF fusion, rerank, confidence score |
| 06 | `s06_verify.py` | Grounding, citation resolution, threshold, safety deny-list |

Stages 01-04 are the offline ingest job, run from the CLI. 05 and 06 are the two functions this package exports.

Query translation, prompt construction, generation and the user-facing API live in `connectplus-llm`.

## Architecture

```
OFFLINE                         ONLINE
approved_domains                connectplus-llm
   │                                 │
[01] Ingest                          ├──►  [05] Retrieve  ──► chunks + confidence
[02] Extract                         │
[03] Chunk                           └──►  [06] Verify    ──► pass | refuse(reason)
[04] Embed + Index ──► pgvector ──────────────┘
```

Each stage is a **pure function** `stage(input) -> output`, one module each, no hidden state. Every boundary has a frozen schema in `schemas.py` and a committed fixture in `fixtures/`, so each stage is developed against the upstream fixture and nobody waits on anybody.

```
rag/
  schemas.py         # every contract, frozen; changes need team agreement
  fixtures/          # f01_pages.json ... f06_verdict.json
  s01_ingest.py      s04_embed.py
  s02_extract.py     s05_retrieve.py
  s03_chunk.py       s06_verify.py
  __init__.py        # exports retrieve() and verify(), the whole public surface
tests/
```

### Contracts

```python
Chunk = {
    id, doc_id, url, domain, title, lang, fetched_at,
    heading_path,        # ["Staying safe", "Recognising scam texts"]
    text, token_count, order_idx,
}

Retrieved = Chunk + { score, method }    # method: "vector" | "keyword" | "fused"

Verdict = {
    passed,
    reason,              # "ungrounded" | "bad_citation" | "low_confidence" | "unsafe" | None
    grounded_score,
    citations: [ { n, url, title, domain, resolved } ],
    confidence,
    chunk_ids,
}
```

`fixtures/f03_chunks.json` holds ~30 hand-written chunks. That file unblocks retrieval, verification and the whole `connectplus-llm` repo before a single page has been crawled, so keep it committed and current.

## Stack

| Concern | Choice | Why |
|---|---|---|
| Crawl | `httpx` + `urllib.robotparser` | Stdlib robots parsing; no crawler framework needed for a handful of domains |
| Extraction | `trafilatura` | Strips boilerplate far better than a hand-written parser, and it's one call |
| Embeddings | BGE-m3 via `sentence-transformers`, local | Genuinely multilingual and free. A Mandarin query must hit an English page, and monolingual embeddings break that core use case |
| Vector store | Supabase Postgres + pgvector (HNSW) | Vector index and keyword index in one database, one connection, free tier |
| Keyword | Postgres `tsvector` | Already in the same database. No second search engine |
| Grounding check | Chunk-level NLI cross-encoder + citation resolution | Deterministic where it can be; no second LLM judging the first one on the hot path |
| Tests | `pytest` | Enough for a prototype |

Model name and embedding dimensions are stored alongside the vectors. Changing the embedding model invalidates the index, and you need to be able to tell.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt
cp .env.example .env                                # fill in Supabase URL + key
```

Python 3.11+. First run downloads BGE-m3 weights (~2 GB), so expect a wait.

```
SUPABASE_URL=
SUPABASE_SERVICE_KEY=       # server-side only, never in a client bundle
EMBED_MODEL=BAAI/bge-m3
CACHE_DIR=.cache/html
CONFIDENCE_THRESHOLD=0.45
GROUNDING_THRESHOLD=0.7
```

## Usage

Build the knowledge base:

```bash
python -m rag.main ingest                     # 01 → 04
python -m rag.main ingest --domain esafety.gov.au
```

Ingest is **idempotent**. Re-running does not duplicate chunks, and cached pages are not re-fetched.

Use it from `connectplus-llm`:

```python
from rag import retrieve, verify

chunks, confidence = retrieve(query, lang="zh")   # stage 05
verdict = verify(answer_md, chunks)               # stage 06
```

That's the entire public surface. Everything else is internal.

Either function from the CLI, against fixtures:

```bash
python -m rag.s05_retrieve "how do I know if a text message is a scam?" --lang zh
python -m rag.s06_verify fixtures/f07_draft.json
```

## Verifying a stage

Done conditions. Acceptance criteria, not suggestions:

- **01.** A non-allowlisted domain is rejected; a second run makes zero network calls.
- **02.** Five pages per domain read by eye and confirmed clean. Extraction quality caps everything downstream.
- **03.** No chunk starts or ends inside a numbered list; every chunk has a URL that resolves.
- **04.** Running ingest twice produces no duplicate chunks.
- **05.** hit@3 recorded over the eval set **in Mandarin as well as English**. Measure before and after the reranker; if it doesn't move the number, drop it.
- **06.** A hand-written answer containing one invented step is caught; a citation swapped to an unapproved domain is caught; a "reply with the code you received" answer is caught.

Adversarial fixtures matter more than happy-path ones here. Keep a file of drafts that *should* be rejected and run them on every change.

## Adding an approved domain

Domains live in the `approved_domains` table, not in code. A curator adds a row, then re-runs ingest for it. The LLM may *propose* a domain; a human approves it. That approval step is deliberate and must not be automated away. The platform's value is that everything a senior sees comes from somewhere a person vouched for.

## Status

Prototype for CW2 (Digital Literacy Platform for CALD Seniors). Runs locally; no deployment or CI in scope.

**Critical path:** the client's approved-domain list gates stages 01-04. Stages 05-06 develop against `f03_chunks.json` and are not blocked by it.
