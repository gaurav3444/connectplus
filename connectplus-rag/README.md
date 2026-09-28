# connectplus-rag

Trusted-knowledge pipeline for **CONNECT Plus** - a digital navigation and referral platform for culturally and linguistically diverse (CALD) seniors. This repo owns the RAG side of the project: crawling the client's approved trusted sources, cleaning that content, splitting it into retrievable chunks, embedding it into a searchable index, retrieving from it, and verifying generated answers against it. `connectplus-llm` calls it twice per question: `retrieve()` before generating, `verify()` after.

This is a class project (CW2, Monash TAP) built stage by stage, testing each stage against real crawled data before moving to the next - not just synthetic examples. That mattered: several real bugs only showed up once real data was run through the pipeline, and they're documented below rather than swept under the rug.

> **Two READMEs, on purpose.** This file describes what was actually built and why. `README_rag.md`, alongside it, is the brief this repo was built against - the spec the source comments mean when they cite `README_rag.md` or "the outer README". It is committed verbatim so those citations resolve, and it is not updated to match the code: where the two disagree, that disagreement is the record.

## Status

| Stage | What it does | Status |
|---|---|---|
| 01 - Ingest | Allowlisted crawl, robots.txt/sitemap-aware, cached to disk | ✅ Done - both domains fully crawled |
| 02 - Extract | HTML/PDF → clean text + structure, via trafilatura + pypdf | ✅ Done - real content-loss bugs found and fixed |
| 03 - Chunk | Heading-aware, list-safe, token-budgeted chunking | ✅ Done - 3 real bugs found and fixed against real data |
| 04 - Embed + Index | BGE-m3 embeddings → Supabase Postgres (pgvector + tsvector) | ✅ Done - both domains fully embedded and indexed |
| 05 - Retrieve | Hybrid vector + keyword search, RRF fusion, optional reranking, confidence score | ✅ Built and tested - real-query verification pending |
| 06 - Verify / Guardrails | Citation resolution, approved-domain enforcement, confidence threshold, safety deny-list, NLI grounding | ✅ Built and tested - adversarial fixture green |

### Stage numbering

RAG owns stages **01-06**; `connectplus-llm` owns **07-10**. File numbers match stage numbers, and match `README_rag.md`.

| Stage | Repo | What |
|---|---|---|
| 01 `s01_ingest` | connectplus-rag | Ingest |
| 02 `s02_extract` | connectplus-rag | Extract |
| 03 `s03_chunk` | connectplus-rag | Chunk |
| 04 `s04_embed` | connectplus-rag | Embed + index |
| 05 `s05_retrieve` | connectplus-rag | Hybrid retrieval |
| 06 `s06_verify` | connectplus-rag | Guardrails + citation check |
| 07 `s07_query` | connectplus-llm | Query understanding: language detection, rewrite into English |
| 08 `s08_prompt` | connectplus-llm | Prompt construction |
| 09 `s09_generate` | connectplus-llm | Grounded generation |
| 10 | connectplus-llm | Answer API (FastAPI SSE) |

Online order per question: 07 query, 05 retrieve, 08 prompt, 09 generate, 06 verify, 10 respond.

**Approved sources:** `beconnected.esafety.gov.au`, `scamwatch.gov.au`. A third domain, `esafety.gov.au`, was dropped after confirming it blocks automated crawlers - see `rag/config/domain_decisions.md`.

**Current real numbers** (last full run):

| Domain | Pages crawled | Docs extracted | Chunks |
|---|---:|---:|---:|
| Be Connected | 1,094 | 929 | 4,148 |
| Scamwatch | 500 | 314 | 1,184 |

## Pipeline

```
approved_domains.json
        │
   [01] Ingest ──────► raw HTML/PDF cache (.cache/html/)
        │
   [02] Extract ─────► clean text + structure (.cache/extracted/)
        │
   [03] Chunk ───────► retrievable chunks, ~300-500 tokens (.cache/chunked/)
        │
   [04] Embed+Index ─► Supabase Postgres (pgvector + tsvector)

ONLINE, per question (called from connectplus-llm)
   [05] Retrieve ────► top-k chunks + one confidence number
   [06] Verify ──────► pass | refuse(reason)
```

Stages 01-04 are the offline ingest job; each reads the previous stage's the previous stage's JSON output and writes its own - no stage needs the others in memory, so any stage can be re-run independently once its input exists.

## Methods

### Stage 01 - Ingest
Domain-level allowlist enforced in code before any network call. Discovers pages via `sitemap.xml` (falling back to same-domain link-following if a sitemap is empty or missing). Caches raw responses to disk, keyed by a hash of the URL, so re-running a domain that's already been crawled makes zero network calls. A circuit breaker aborts a domain after 5 consecutive fetch failures rather than grinding through hundreds of guaranteed timeouts - this is exactly how `esafety.gov.au` was confirmed to be blocking the crawler. Binary content (PDFs) is cached as raw bytes separately from text, after discovering that decoding a PDF's bytes as text silently corrupts it.

### Stage 02 - Extract
`trafilatura` for HTML, `pypdf` for PDFs. Two real content-loss bugs were found and fixed here, both confirmed against actual crawled pages before being treated as real:

- **Recovered content.** `trafilatura`'s boilerplate-detection sometimes drops entire content blocks that are structurally marked as "callout" components - a real Scamwatch page had its entire "what to do if you've been scammed" procedure silently excluded this way. A recovery pass detects `<ol>`/`<ul>` content trafilatura excluded but that looks like real content (long-ish text per item, not a nav menu), and adds it back. Confirmed at scale: 315 of 929 Be Connected docs and 34 of 314 Scamwatch docs gained recovered content this way - over 1,000,000 characters total, mostly full video transcripts hidden behind toggle/expand widgets.
- **Deduplication.** Scamwatch's sitemap lists both `http://` and `https://` versions of many pages. 162 of 477 raw Scamwatch docs were exact-duplicate content; deduplication keeps one canonical copy per unique text, preferring the `https://` version.

Known, deliberately deferred: two Chinese-language pages that `trafilatura` can't extract at all (a documented limitation of readability-style extractors on CJK text), and lower text-extraction quality on some non-English PDFs (Hindi, Greek), likely a `pypdf` limitation with complex scripts.

### Stage 03 - Chunk
Structure comes from `trafilatura`'s XML output (headings, paragraphs, lists as real elements) - not from raw HTML and not from a markdown re-rendering, after finding that markdown's text serialization introduces real structural bugs (a heading glued to its own next paragraph with no separating newline) that don't exist in XML.

Chunks target 300–500 tokens, measured with **BGE-m3's own tokenizer** - not a generic approximation - since the corpus has confirmed real content in Vietnamese, Chinese, Hindi, and Greek, and a tokenizer tuned for English/code underrepresents non-Latin scripts. Small adjacent sections merge under a shared heading ancestor; oversized sections split at paragraph boundaries, then sentence boundaries, then (as a last resort) a word-boundary-respecting token slice - each level only kicking in if the previous one wasn't enough.

**Numbered procedures are never split** - the one hard correctness rule the whole design serves. Three real bugs were found and fixed while getting this right:
1. Recovered content (see above) was represented as an atomic "list," making genuine prose (like a 9,000-token transcript) impossible to split.
2. `trafilatura` sometimes captures an entire transcript *natively* inside a single `<ul><li>` (an accordion/"read transcript" widget) - a list is now only treated as atomic when its items are flat text with no nested headings.
3. A single oversized paragraph (a transcript merged into one `<p>` tag) had no mechanism to split it internally at all.

The worst chunk in the real test data went from 8,968 tokens (before these fixes) to 479 tokens (after).

### Stage 04 - Embed + Index
`BAAI/bge-m3` (1024-dim, multilingual) via `sentence-transformers`, batched, upserted into Supabase Postgres. The table (`rag/config/schema.sql`) carries a `vector(1024)` column with an HNSW index for similarity search, and a generated `tsvector` column with a GIN index for keyword search - both from the same table, since stage 05 needs to fuse both. Re-running `index` on the same chunks is idempotent (`ON CONFLICT (id) DO UPDATE`), since chunk IDs are stable hashes from stage 03. Upserting happens after every batch, not once at the end - a real crash (PyTorch's Metal/MPS backend running out of GPU memory on Apple Silicon, mid-run) confirmed that collecting everything in memory before writing loses all progress on failure; embedding now defaults to CPU-only for the same reason.

### Stage 05 - Retrieve
Vector search (pgvector cosine similarity) and keyword search (Postgres full-text search over the `tsvector` column) run independently, then combine via Reciprocal Rank Fusion - a chunk both methods agree on outranks one only a single method found. Reranking with `BAAI/bge-reranker-v2-m3` (the standard cross-encoder pairing for BGE-m3) is optional, not hardwired, per this stage's own DONE criterion in `README_rag.md`: measure hit@3 before and after the reranker, and drop it if it doesn't move the number.

The single confidence number stage 06 refuses on comes from bge-reranker-v2-m3's own output directly (its default CrossEncoder activation already returns a calibrated [0,1] relevance probability - confirmed via the official sentence-transformers docs, not assumed) when reranking is used, or the top result's raw vector similarity as a lower-fidelity fallback otherwise. Worth knowing before tuning a threshold: real BGE-m3 similarity scores for confirmed-relevant results on this project's own data landed in the 0.53–0.78 range, not 0.85+ - cosine similarity from dense embedding models doesn't behave like a percentage-match score, and a published benchmark (Ros et al., arXiv 2605.22099) reports comparable top-1 similarity (~0.70) for BGE-M3 on correct matches.

Two real bugs were found and fixed against real query results, not synthetic tests: (1) RRF fusion without reranking could rank a generic chunk above the one that specifically answered the query, because keyword search's `ts_rank` can't tell a corpus-common word ("scam", present in nearly every document) from a genuine relevance signal - reranking is now the effectively mandatory default, not just an available option. (2) A real nonsense query ("purple elephant quantum banana recipe") returned 5 completely unrelated results that all scored exactly 0.500 - traced to double-applying sigmoid to a reranker score that was already a calibrated [0,1] probability, collapsing every genuinely-different low score toward 0.5. Confirmed and fixed by checking the official sentence-transformers documentation rather than assuming the model's output shape.

**Keyword search only works on English.** `rag/config/schema.sql` builds its `tsvector` with Postgres's `'english'` configuration, so a Mandarin query produces an **empty** `tsquery`, matches nothing, and hybrid retrieval silently collapses to vector-only. Switching to `'simple'` would not help: Postgres cannot tokenise CJK text at all. So `retrieve()` expects an English query: `connectplus-llm`'s stage 07 rewrites the senior's question into English first, which is why the public call is `retrieve(query_en, ...)`. Non-English chunks in the index (real: Vietnamese, Chinese, Hindi and Greek translated pages) are reachable through vector search only.

Every external dependency (vector search, keyword search, chunk fetching, reranking) is injectable, so the fusion and scoring logic is fully tested without a live database or downloaded models - see `tests/test_s05_retrieve.py`.

### Stage 06 - Verify / Guardrails

Its own stage, not a flag inside generation. Four checks, all of which must pass:

| Check | Fails when |
|---|---|
| **Confident** | Retrieval confidence is below threshold - there was never good enough source material |
| **Safe** | The answer tells the senior to hand over a password, an MFA code or payment details |
| **Cited** | A citation marker resolves to nothing, or to a domain not on the approved list |
| **Grounded** | The answer states a fact that is not in the supplied chunks |

Fail any one and the answer is **dropped, not patched**. Check order is harm-first rather than cost-first: `unsafe` outranks `bad_citation` even though both are cheap regexes, because `reason` decides which message the senior sees, and "that advice was dangerous" matters more than "a footnote did not resolve".

Everything except grounding is deterministic - no second LLM judging the first one on the hot path, since a model that can invent an answer can invent a defence of it.

**The hard part of the safety check is not the deny-list, it is the negation.** The correct, desirable answer on this corpus is *"never share your password with anyone"* - a naive deny-list on the word "password" rejects every good safety answer, while the lazy fix of dropping the word lets the dangerous one through. So the pattern matches *instructions to disclose* and then checks for a negation, looking back only to the start of the current sentence: a "never" in a **previous** sentence must not launder the instruction in this one (fixture `d11`).

Two real details that only showed up on the fixture:

- **Bare `code` had to be a match.** The outer README's literal acceptance case is *"reply with the code you received"* - a senior forwarding a one-time code does not call it a "verification code". Requiring the qualifier missed the exact phrasing the check exists to catch. The false positives that buys ("enter your postcode", "share the discount code") are handled by a separate benign-code list rather than by narrowing the match, because the missing qualifier *is* the problem.
- **An answer with no citations at all fails `cited`.** Without that rule the easiest way to pass the citation check is to cite nothing - precisely the shape a wholly invented answer takes.

Grounding scores the answer's **weakest** substantive claim, not the average. An average lets one invented step hide behind four well-supported ones, and "a hand-written answer containing one invented step is caught" is this stage's own acceptance criterion - a mean cannot deliver it. Each sentence is scored against its best-matching chunk, since a claim needs only one source to support it.

The entailment model's label index is read from the model's own `id2label`, not hardcoded. Hardcoding it would fail **open** on a model swap - every answer graded against the wrong class, wrong answers passing silently.

The approved-domain list is enforced here as well as at fetch time, which is not redundant: chunks already in the index outlive a domain's approval, because stage 04's upsert-by-id never deletes anything.

```bash
python -m rag.main verify              # three deterministic checks
python -m rag.main verify --grounding  # + NLI (first run downloads ~500MB)
```

`rag/fixtures/f06_drafts.json` holds 12 drafts, most of which **should be rejected** - including all three cases the outer README names as acceptance criteria. Adversarial fixtures matter more than happy-path ones here; run them on every change.

## Using it from connectplus-llm

Two calls, the signatures agreed with `connectplus-llm`, both plain function calls in the same process:

```python
from rag import retrieve, verify, REFUSAL_THRESHOLD

chunks, confidence = retrieve(query_en, lang, k)   # query already translated to English
if confidence < REFUSAL_THRESHOLD: ...             # refuse early, don't generate
draft = generate(chunks, lang)                     # connectplus-llm
verdict = verify(draft, chunks, lang=lang)         # draft: answer_md str, or an Answer dict/object
```

`REFUSAL_THRESHOLD` is the same number `verify` refuses on, so skipping generation below it loses nothing. `lang` is logged, not used by the checks.

`rag/api.py` binds the production dependencies (Postgres from this repo's own `.env`, the reranker, the NLI model), so the caller passes plain values only. The reranker is always on, which makes `confidence` equal the top chunk's score - so `verify` recomputes it from `chunks` instead of taking it from the caller, and a draft cannot vouch for its own confidence. Pass `chunks` back exactly as `retrieve` returned them: `[n]` means the n-th chunk the generator was shown. A failing verdict means drop the answer and offer a mentor; never patch and retry. Both calls log to the `rag` logger.

## Project structure

```
rag/
  schemas.py          # every contract between stages, frozen
  api.py              # retrieve(query_en, lang, k) and verify(draft, chunks, lang) - the public surface
  main.py             # CLI: ingest / extract / chunk / index / retrieve / verify
  s01_ingest.py
  s02_extract.py
  s03_chunk.py
  s04_embed.py
  s05_retrieve.py
  s06_verify.py
  lang.py             # langdetect, used by stage 02
  config/
    approved_domains.json
    domain_decisions.md
    schema.sql
  fixtures/
    f01_pages.json    # 6 real pages, used to test every stage
    f03_chunks.json   # 37 real chunks from f01, the handoff for stages 05/06 and connectplus-llm
    eval_queries.json # the eval set: 10 vague questions x 2 languages + 2 refusal cases
    f06_drafts.json   # 12 draft answers for stage 06, most of which should be REJECTED
    sample_little_book_of_scams.pdf
scripts/
  verify_index.sql       # manual sanity checks for stage 04's output
  spot_check_index.py    # manual vector-search-only smoke test (superseded by `retrieve`, kept for reference)
  eval_queries.py        # hit@3 over the eval set, per language, reranker on/off
  make_f03_chunks.py     # regenerates f03_chunks.json with the real stage 02 + 03
tests/
  test_api.py
  test_s01_ingest.py
  test_s02_extract.py
  test_s03_chunk.py
  test_s04_embed.py
  test_s05_retrieve.py
  test_s06_verify.py
.github/workflows/ci.yml
README_rag.md
.env.example
```

`lang.py` is its own module rather than living inside `s02_extract` so that detecting a language never requires importing `trafilatura` and the rest of the offline crawl-and-extract stack.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python3 -m pip install -e ".[dev]"
```

For stage 04, you also need a Supabase project:

1. Create a free project at [supabase.com](https://supabase.com).
2. In the SQL Editor, run `create extension if not exists vector;`, then run the full contents of `rag/config/schema.sql`.
3. Copy `.env.example` to `.env` and fill in your **Session pooler** connection string (Supabase dashboard → Connect → Session pooler - not "Direct connection", which fails with "No route to host" on many networks due to an IPv6 routing issue).

## Running it

```bash
# Stage 01 - crawl (idempotent; re-running an already-crawled domain makes no network calls)
python -m rag.main ingest --domain scamwatch.gov.au
python -m rag.main ingest --domain beconnected.esafety.gov.au --max-pages 1200

# Stage 02 - extract
python -m rag.main extract --domain scamwatch.gov.au
python -m rag.main extract --domain beconnected.esafety.gov.au

# Stage 03 - chunk
python -m rag.main chunk --domain scamwatch.gov.au
python -m rag.main chunk --domain beconnected.esafety.gov.au

# Stage 04 - embed + index (needs Supabase set up, see above)
python -m rag.main index --domain scamwatch.gov.au
python -m rag.main index --domain beconnected.esafety.gov.au

# Stage 05 - retrieve (query against the real index)
python -m rag.main retrieve "how do I know if a text message is a scam"
python -m rag.main retrieve "what is mygov" --top-k 3
python -m rag.main retrieve "artificial intelligence scams" --no-rerank

# Stage 06 - grade the adversarial drafts (no database needed)
python -m rag.main verify
python -m rag.main verify --grounding
```

`retrieve` sends the raw string to both search halves, so ask it in English: a Mandarin query only reaches the vector half (see stage 05).

`beconnected.esafety.gov.au` needs `--max-pages 1200` on ingest - its real sitemap has 1,094 URLs, above the default 500-page safety cap.

First run of `chunk` downloads BGE-m3's tokenizer (~a few MB); first run of `index` downloads the full BGE-m3 model (~2GB); first run of `retrieve` with reranking on additionally downloads `bge-reranker-v2-m3`. All are one-time downloads, cached afterward. Embedding a full domain on CPU (no GPU) can take a while - the CLI prints live batch progress (`embedding batch 47/259...`) so this doesn't look like a hang.

## Testing

```bash
pytest tests/ -v
```

168 tests. Every stage's tests run against the real 6-page fixture in `rag/fixtures/` (not just synthetic cases) - several of the bugs described above were only caught because of this. Every external dependency (network calls, the BGE-m3 model/tokenizer, the reranker, the Supabase connection, the NLI cross-encoder) is injectable, so the full test suite runs with no internet access and no live services.

## Evaluating retrieval

Stage 05's DONE criterion is a *measurement*, not a code review: hit@3 over the eval set, in Mandarin as well as English, measured before and after the reranker. If the reranker doesn't move the number, drop it.

Scored by one command, against the live index:

```bash
python scripts/eval_queries.py                  # reranker on, both languages
python scripts/eval_queries.py --no-rerank      # the "before" half of before/after
```

The question set is `rag/fixtures/eval_queries.json` - ten questions phrased the way a senior would actually ask (vague, wrong word, symptom described rather than named), each in English and Mandarin, plus two queries the knowledge base should *not* be able to answer. A query set written in the corpus's own vocabulary measures nothing: it would score well without query understanding existing at all.

**All 10 expected pages are set.** 4 were confirmed against `f01_pages.json` up front; the other 6 were filled after the first live run by checking which pages exist in the index, never by copying what retrieval happened to return. A bare hostname (`scamwatch.gov.au`) is never a valid expectation: it scores *any* page on that domain as a hit. q03 (two-factor) is a weak target - no page in the corpus is about two-factor authentication itself, so it points at the page with the most chunks mentioning it. That is a corpus gap, not a retrieval one.

### Results (2026-09-28, full index: 5,332 chunks)

Reranker **off** (`--no-rerank`), raw query straight in, no query understanding:

| Query | EN | ZH |
|---|---|---|
| q01 scam text | ✅ 2 | ❌ 4 |
| q02 myGov | ❌ | ❌ |
| q03 two-factor | ❌ | ✅ 1 |
| q04 tax office call | ❌ | ❌ |
| q05 already scammed | ✅ 2 | ✅ 1 |
| q06 AI scams | ❌ 4 | ❌ |
| q07 strong password | ✅ 3 | ✅ 2 |
| q08 report a scam | ❌ | ❌ |
| q09 romance | ✅ 1 | ✅ 3 |
| q10 email link | ✅ 1 | ❌ |
| **hit@3** | **5/10** | **4/10** |
| keyword half found nothing | 1/10 | **10/10** |

Numbers are the rank of the first correct page; a bare ❌ means the page was not among the 5 chunks returned at all.

Refusal set (should be low): nonsense 0.437 EN / 0.367 ZH, Melbourne weather 0.483 EN / 0.495 ZH. Real questions scored 0.59-0.78.

What this shows:

- **Keyword search contributes nothing to Mandarin**, confirmed on the real index: 10/10 Chinese queries got an empty keyword result. Chinese retrieval is vector-only unless `connectplus-llm`'s stage 07 hands `retrieve()` an English rewrite. These ZH numbers are the floor that stage has to beat.
- **Raw similarity cannot separate in-scope from out-of-scope.** The weather question scores 0.48-0.50, above the 0.45 threshold, so on this path it would *not* be refused. The public `retrieve()` always reranks, which is why the threshold decision waits for the reranked run.

**Reranker on: not yet measured.** The run was started and stopped - on CPU, reranking 24 queries x up to 40 candidates did not finish in 30 minutes. Run it on a machine with more headroom (`python -u scripts/eval_queries.py`, `-u` so progress shows line by line), then decide keep-or-drop and set the threshold from its refusal-set scores.

The output includes a `kw` column showing whether the keyword half contributed anything. That column is the alarm for the English-only keyword search described under stage 05 - all-`vector` results mean half the system did nothing and nothing said so.

## What's next

This repo's own stages are complete. What remains is `connectplus-llm`'s half - stages **07-10** (query understanding, prompt, generation, answer API) - plus:

- **The reranked eval run.** The no-rerank baseline is recorded above (EN 5/10, ZH 4/10); the reranked half of stage 05's before/after is not. Until it is, keep-or-drop for the reranker is undecided.
- **`confidence` has two incompatible scales.** With reranking it is bge-reranker-v2-m3's calibrated `[0,1]` probability; without, it is the top result's raw cosine similarity, which on this project's real data landed in the 0.53–0.78 range for *confirmed relevant* results. Stage 06 refuses on a single threshold (`DEFAULT_CONFIDENCE_THRESHOLD = 0.45`) that cannot serve both. The public `retrieve` always reranks, so only the CLI's `--no-rerank` path hits this; the 0.45 itself is still uncalibrated - the no-rerank run already shows an out-of-scope question at 0.495. The eval harness prints the real distribution, including for queries that should be refused - calibrate against that, not against percentage-match intuition.

### Known gaps, deliberately deferred

- Chunk text is embedded without its `title`/`heading_path` prefix. Likely a real retrieval-quality loss, but fixing it means a full re-index - measure with the eval harness first, then decide.
- No delete path for de-approved domains or removed pages. Stage 06 now refuses to *cite* an unapproved domain, but the rows stay in the index and stay retrievable.
- Nothing enforces source diversity in the top-k - all five results can come from one page, starving the generator of independent sources.
- Two Chinese-language pages `trafilatura` cannot extract, and lower text quality on some non-English PDFs (see stage 02).
