# connectplus-rag

Trusted-knowledge pipeline for **CONNECT Plus** — a digital navigation and referral platform for culturally and linguistically diverse (CALD) seniors. This repo owns the RAG side of the project: crawling the client's approved trusted sources, cleaning that content, splitting it into retrievable chunks, and embedding it into a searchable index.

This is a class project (CW2, Monash TAP) built stage by stage, testing each stage against real crawled data before moving to the next — not just synthetic examples. That mattered: several real bugs only showed up once real data was run through the pipeline, and they're documented below rather than swept under the rug.

## Status

| Stage | What it does | Status |
|---|---|---|
| 01 — Ingest | Allowlisted crawl, robots.txt/sitemap-aware, cached to disk | ✅ Done — both domains fully crawled |
| 02 — Extract | HTML/PDF → clean text + structure, via trafilatura + pypdf | ✅ Done — real content-loss bugs found and fixed |
| 03 — Chunk | Heading-aware, list-safe, token-budgeted chunking | ✅ Done — 3 real bugs found and fixed against real data |
| 04 — Embed + Index | BGE-m3 embeddings → Supabase Postgres (pgvector + tsvector) | ✅ Scamwatch fully indexed; Be Connected in progress |

**Approved sources:** `beconnected.esafety.gov.au`, `scamwatch.gov.au`. A third domain, `esafety.gov.au`, was dropped after confirming it blocks automated crawlers — see `rag/config/domain_decisions.md`.

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
```

Each stage reads the previous stage's JSON output and writes its own — no stage needs the others in memory, so any stage can be re-run independently once its input exists.

## Methods

### Stage 01 — Ingest
Domain-level allowlist enforced in code before any network call. Discovers pages via `sitemap.xml` (falling back to same-domain link-following if a sitemap is empty or missing). Caches raw responses to disk, keyed by a hash of the URL, so re-running a domain that's already been crawled makes zero network calls. A circuit breaker aborts a domain after 5 consecutive fetch failures rather than grinding through hundreds of guaranteed timeouts — this is exactly how `esafety.gov.au` was confirmed to be blocking the crawler. Binary content (PDFs) is cached as raw bytes separately from text, after discovering that decoding a PDF's bytes as text silently corrupts it.

### Stage 02 — Extract
`trafilatura` for HTML, `pypdf` for PDFs. Two real content-loss bugs were found and fixed here, both confirmed against actual crawled pages before being treated as real:

- **Recovered content.** `trafilatura`'s boilerplate-detection sometimes drops entire content blocks that are structurally marked as "callout" components — a real Scamwatch page had its entire "what to do if you've been scammed" procedure silently excluded this way. A recovery pass detects `<ol>`/`<ul>` content trafilatura excluded but that looks like real content (long-ish text per item, not a nav menu), and adds it back. Confirmed at scale: 315 of 929 Be Connected docs and 34 of 314 Scamwatch docs gained recovered content this way — over 1,000,000 characters total, mostly full video transcripts hidden behind toggle/expand widgets.
- **Deduplication.** Scamwatch's sitemap lists both `http://` and `https://` versions of many pages. 162 of 477 raw Scamwatch docs were exact-duplicate content; deduplication keeps one canonical copy per unique text, preferring the `https://` version.

Known, deliberately deferred: two Chinese-language pages that `trafilatura` can't extract at all (a documented limitation of readability-style extractors on CJK text), and lower text-extraction quality on some non-English PDFs (Hindi, Greek), likely a `pypdf` limitation with complex scripts.

### Stage 03 — Chunk
Structure comes from `trafilatura`'s XML output (headings, paragraphs, lists as real elements) — not from raw HTML and not from a markdown re-rendering, after finding that markdown's text serialization introduces real structural bugs (a heading glued to its own next paragraph with no separating newline) that don't exist in XML.

Chunks target 300–500 tokens, measured with **BGE-m3's own tokenizer** — not a generic approximation — since the corpus has confirmed real content in Vietnamese, Chinese, Hindi, and Greek, and a tokenizer tuned for English/code underrepresents non-Latin scripts. Small adjacent sections merge under a shared heading ancestor; oversized sections split at paragraph boundaries, then sentence boundaries, then (as a last resort) a word-boundary-respecting token slice — each level only kicking in if the previous one wasn't enough.

**Numbered procedures are never split** — the one hard correctness rule the whole design serves. Three real bugs were found and fixed while getting this right:
1. Recovered content (see above) was represented as an atomic "list," making genuine prose (like a 9,000-token transcript) impossible to split.
2. `trafilatura` sometimes captures an entire transcript *natively* inside a single `<ul><li>` (an accordion/"read transcript" widget) — a list is now only treated as atomic when its items are flat text with no nested headings.
3. A single oversized paragraph (a transcript merged into one `<p>` tag) had no mechanism to split it internally at all.

The worst chunk in the real test data went from 8,968 tokens (before these fixes) to 479 tokens (after).

### Stage 04 — Embed + Index
`BAAI/bge-m3` (1024-dim, multilingual) via `sentence-transformers`, batched, upserted into Supabase Postgres. The table (`rag/config/schema.sql`) carries a `vector(1024)` column with an HNSW index for similarity search, and a generated `tsvector` column with a GIN index for keyword search — both from the same table, since stage 06 (retrieval, not yet built) needs to fuse both. Re-running `index` on the same chunks is idempotent (`ON CONFLICT (id) DO UPDATE`), since chunk IDs are stable hashes from stage 03.

## Project structure

```
rag/
  schemas.py          # every contract between stages, frozen
  main.py             # CLI: ingest / extract / chunk / index
  s01_ingest.py
  s02_extract.py
  s03_chunk.py
  s04_embed.py
  config/
    approved_domains.json
    domain_decisions.md
    schema.sql
  fixtures/
    f01_pages.json    # 6 real pages, used to test every stage
    sample_little_book_of_scams.pdf
tests/
  test_s01_ingest.py
  test_s02_extract.py
  test_s03_chunk.py
  test_s04_embed.py
.github/workflows/ci.yml
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python3 -m pip install -e ".[dev]"
```

For stage 04, you also need a Supabase project:

1. Create a free project at [supabase.com](https://supabase.com).
2. In the SQL Editor, run `create extension if not exists vector;`, then run the full contents of `rag/config/schema.sql`.
3. Copy `.env.example` to `.env` and fill in your **Session pooler** connection string (Supabase dashboard → Connect → Session pooler — not "Direct connection", which fails with "No route to host" on many networks due to an IPv6 routing issue).

## Running it

```bash
# Stage 01 — crawl (idempotent; re-running an already-crawled domain makes no network calls)
python -m rag.main ingest --domain scamwatch.gov.au
python -m rag.main ingest --domain beconnected.esafety.gov.au --max-pages 1200

# Stage 02 — extract
python -m rag.main extract --domain scamwatch.gov.au
python -m rag.main extract --domain beconnected.esafety.gov.au

# Stage 03 — chunk
python -m rag.main chunk --domain scamwatch.gov.au
python -m rag.main chunk --domain beconnected.esafety.gov.au

# Stage 04 — embed + index (needs Supabase set up, see above)
python -m rag.main index --domain scamwatch.gov.au
python -m rag.main index --domain beconnected.esafety.gov.au
```

`beconnected.esafety.gov.au` needs `--max-pages 1200` on ingest — its real sitemap has 1,094 URLs, above the default 500-page safety cap.

First run of `chunk` downloads BGE-m3's tokenizer (~a few MB); first run of `index` downloads the full BGE-m3 model (~2GB). Both are one-time downloads, cached afterward. Embedding a full domain on CPU (no GPU) can take a while — the CLI prints live batch progress (`embedding batch 47/259...`) so this doesn't look like a hang.

## Testing

```bash
pytest tests/ -v
```

84 tests. Every stage's tests run against the real 6-page fixture in `rag/fixtures/` (not just synthetic cases) — several of the bugs described above were only caught because of this. Network calls, the BGE-m3 model/tokenizer, and the Supabase connection are all injectable (`httpx.Client`, a token-counter callable, an embed function, an upsert function), so the test suite runs with no internet access and no live services.

## What's next

Stage 05 (query understanding) and stage 07 (grounded generation) belong to the LLM side of the team (`connectplus-llm`). Remaining on this side: stage 06 (hybrid retrieval) and stage 08 (guardrails + citation check), per the original stage map.
