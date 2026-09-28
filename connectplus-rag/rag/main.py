"""CLI entry point. Wires up stages 01 through 06.

Usage (from README_rag.md, extended for 02-05):
    python -m rag.main ingest
    python -m rag.main ingest --domain scamwatch.gov.au
    python -m rag.main extract --domain scamwatch.gov.au
    python -m rag.main chunk --domain scamwatch.gov.au
    python -m rag.main index --domain scamwatch.gov.au
    python -m rag.main retrieve "how do I know if a text message is a scam"
    python -m rag.main verify

`index` and `retrieve` read DATABASE_URL from a .env file in the project
root (or the real environment) - Supabase's SESSION POOLER connection
string specifically (dashboard -> "Connect" -> "Session pooler"), not
"Direct connection" and not "Project URL". Confirmed real issue:
Supabase's direct connection only resolves over IPv6 by default, which
fails with "No route to host" on networks that don't route IPv6 - the
session pooler works over IPv4. See .env.example and rag/config/schema.sql.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from rag.s01_ingest import MAX_PAGES_PER_DOMAIN as DEFAULT_MAX_PAGES
from rag.s01_ingest import ingest, load_pages_from_manifest
from rag.s02_extract import (
    configure_json_logging as configure_extract_logging,
)
from rag.s02_extract import (
    extract_pages,
    load_extraction_inputs_from_cache,
)
from rag.s03_chunk import chunk_docs
from rag.s04_embed import DEFAULT_BATCH_SIZE, index_chunks, make_postgres_upserter
from rag.s05_retrieve import (
    DEFAULT_TOP_K_FINAL,
    get_default_reranker,
    make_postgres_chunk_fetcher,
    make_postgres_keyword_search,
    make_postgres_vector_search,
    retrieve,
)
from rag.s06_verify import get_default_entailment, verify
from rag.schemas import Chunk, ExtractedDoc

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "approved_domains.json"
DEFAULT_CACHE_DIR = Path(".cache/html")
DEFAULT_EXTRACTED_DIR = Path(".cache/extracted")
DEFAULT_CHUNKED_DIR = Path(".cache/chunked")


def _use_utf8_stdout() -> None:
    """Windows consoles still default to a legacy codepage (cp1252 here),
    and printing a Mandarin query to one raises UnicodeEncodeError before
    a single result is shown. Confirmed real: printing a Chinese
    query crashed on its own output.

    errors="replace" as well as utf-8, so a genuinely incapable terminal
    prints boxes instead of taking the command down.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def _get_db_url() -> str | None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        env_path = Path(__file__).parent.parent / ".env"
        print(
            f"DATABASE_URL is not set. Checked for a .env file at: {env_path}\n"
            "  - Does that file exist and contain a DATABASE_URL=... line?\n"
            "  - Is python-dotenv installed? "
            "(`python3 -c \"import dotenv\"` should print nothing, not an error)\n"
            "  - Use Supabase's SESSION POOLER connection string (dashboard -> Connect -> "
            "'Session pooler'), not 'Direct connection' or 'Project URL' - direct connections "
            "often fail with IPv6 routing issues; the pooler works over IPv4."
        )
        return None
    return db_url


NO_RERANK_WARNING = (
    "Note: running WITHOUT the reranker. Confirmed real risk, not just a slower/"
    "faster trade-off: on real data, RRF fusion without reranking ranked a generic "
    "chunk above the one that specifically answered the query, because keyword "
    "search's ts_rank can't tell a common domain word from a real relevance signal. "
    "Use this flag for the README's own before/after comparison, not for real use.\n"
)


def _print_results(results: list, confidence: float, use_reranker: bool) -> None:
    print(f"Confidence: {confidence:.3f}  (reranker {'on' if use_reranker else 'off'})")
    print(f"\nTop {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"#{i}  score={r.score:.3f}  method={r.method}")
        print(f"    url: {r.url}")
        print(f"    heading_path: {r.heading_path}")
        print(f"    text: {r.text[:200]}...")
        print()


def _run_retrieve(query: str, top_k: int, use_reranker: bool) -> None:
    db_url = _get_db_url()
    if not db_url:
        return

    if not use_reranker:
        print(NO_RERANK_WARNING)

    rerank_fn = get_default_reranker() if use_reranker else None
    results, confidence = retrieve(
        query,
        vector_search_fn=make_postgres_vector_search(db_url),
        keyword_search_fn=make_postgres_keyword_search(db_url),
        fetch_chunks_fn=make_postgres_chunk_fetcher(db_url),
        rerank_fn=rerank_fn,
        top_k_final=top_k,
    )

    print(f"Query: {query!r}")
    _print_results(results, confidence, use_reranker)


DEFAULT_DRAFTS_PATH = Path(__file__).parent / "fixtures" / "f06_drafts.json"


def _run_verify(drafts_path: Path, use_grounding: bool) -> None:
    """Grades every draft in the fixture and prints pass/fail against what
    each was expected to do. Adversarial fixtures matter more than
    happy-path ones here - most of these SHOULD be rejected, and a guardrail
    that stops rejecting them has broken silently.
    """
    spec = json.loads(drafts_path.read_text(encoding="utf-8"))
    all_chunks = [Chunk.model_validate(c) for c in spec["chunks"]]
    entail_fn = get_default_entailment() if use_grounding else None

    if not use_grounding:
        print(
            "Note: grounding is OFF (no --grounding), so drafts whose only fault is an\n"
            "invented fact will PASS the other three checks. That is correct behaviour,\n"
            "not a bug - and it is exactly why grounding is not optional in production.\n"
        )

    print(f"{'draft':<42}{'expected':<16}{'got':<16}ok")
    print("-" * 82)
    agree = 0
    for d in spec["drafts"]:
        chunks = [all_chunks[i] for i in d["chunks"]]
        verdict = verify(d["answer_md"], chunks, d["confidence"], entail_fn=entail_fn)
        # A draft marked needs_grounding can only fail once grounding runs.
        expected = d["expect"]
        if d.get("needs_grounding") and not use_grounding:
            expected = None
        ok = verdict.reason == expected
        agree += int(ok)
        print(f"{d['id']:<42}{str(expected):<16}{str(verdict.reason):<16}{'yes' if ok else 'NO'}")

    print("-" * 82)
    print(f"{agree}/{len(spec['drafts'])} drafts graded as expected"
          f"   (grounding {'on' if use_grounding else 'off'})")
    if agree != len(spec["drafts"]):
        print(
            "\nA disagreement here means the guardrail changed behaviour. "
            "Investigate before committing."
        )


def _run_extract(domain: str, cache_dir: Path, extracted_dir: Path) -> None:
    try:
        pages = load_pages_from_manifest(domain, cache_dir)
    except FileNotFoundError as exc:
        print(str(exc))
        return

    inputs = load_extraction_inputs_from_cache(pages, cache_dir)
    configure_extract_logging()
    docs, summary = extract_pages(inputs)

    extracted_dir.mkdir(parents=True, exist_ok=True)
    out_path = extracted_dir / f"{domain}.json"
    out_path.write_text(
        json.dumps([d.model_dump(mode="json") for d in docs], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"{domain}: {summary.extracted}/{summary.total_input_pages} pages extracted -> {out_path}")
    print(f"  skipped non-200: {summary.skipped_non_200_status}")
    print(f"  skipped unsupported content-type: {summary.skipped_unsupported_content_type}")
    print(f"  skipped empty after extraction: {summary.skipped_empty_after_extraction}")
    print(f"  deduplicated (exact text match): {summary.deduplicated_exact_text_matches}")


def _run_chunk(domain: str, extracted_dir: Path, chunked_dir: Path) -> None:
    extracted_path = extracted_dir / f"{domain}.json"
    if not extracted_path.exists():
        print(f"{domain}: no extracted docs found at {extracted_path} - run `extract` for this domain first")
        return

    docs = [ExtractedDoc.model_validate(d) for d in json.loads(extracted_path.read_text(encoding="utf-8"))]
    chunks = chunk_docs(docs)  # real BGE-m3 tokenizer here - no injected counter in production use

    chunked_dir.mkdir(parents=True, exist_ok=True)
    out_path = chunked_dir / f"{domain}.json"
    out_path.write_text(
        json.dumps([c.model_dump(mode="json") for c in chunks], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with_headings = sum(1 for c in chunks if c.heading_path)
    over_budget = sum(1 for c in chunks if c.token_count > 500)
    avg_tokens = sum(c.token_count for c in chunks) / len(chunks) if chunks else 0
    print(f"{domain}: {len(docs)} docs -> {len(chunks)} chunks -> {out_path}")
    print(f"  with heading_path: {with_headings}/{len(chunks)}")
    print(f"  average tokens per chunk: {avg_tokens:.0f}")
    print(f"  over the 500-token budget (expected only for oversized atomic lists): {over_budget}")


def _run_index(domain: str, chunked_dir: Path, batch_size: int) -> None:
    chunked_path = chunked_dir / f"{domain}.json"
    if not chunked_path.exists():
        print(f"{domain}: no chunked file found at {chunked_path} - run `chunk` for this domain first")
        return

    db_url = _get_db_url()
    if not db_url:
        return

    chunks = [Chunk.model_validate(c) for c in json.loads(chunked_path.read_text(encoding="utf-8"))]
    upsert_fn = make_postgres_upserter(db_url)

    def print_progress(done: int, total: int) -> None:
        print(f"  embedding batch {done}/{total}...", end="\r", flush=True)

    summary = index_chunks(chunks, upsert_fn=upsert_fn, batch_size=batch_size, on_batch_done=print_progress)
    print()  # move past the \r-overwritten progress line

    print(f"{domain}: {summary.embedded}/{summary.total_chunks} chunks embedded and upserted")
    print(f"  model: {summary.embedding_model} ({summary.embedding_dim}-dim)")
    print(f"  batches: {summary.batches}")


def main() -> None:
    _use_utf8_stdout()
    # Load a .env file if present - the natural place for DATABASE_URL to
    # live, matching README_rag.md's `cp .env.example .env` setup step.
    # Explicit path (project root, i.e. one level up from this file's own
    # rag/ package directory) rather than relying on load_dotenv()'s
    # implicit cwd-based search - that search is relative to where the
    # command happens to be run from, which is fragile. A missing
    # python-dotenv install now prints a clear warning instead of silently
    # doing nothing: that silence is exactly what made a real, confirmed
    # case of this ("DATABASE_URL is not set" despite a correctly filled
    # .env file) confusing to diagnose - stages 01-03 still work fine
    # either way, only stage 04 (index) actually needs this.
    env_path = Path(__file__).parent.parent / ".env"
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_path)
    except ImportError:
        print(
            "Warning: python-dotenv is not installed, so .env is not being loaded. "
            "Run `python3 -m pip install -e \".[dev]\"` if `index` reports "
            "DATABASE_URL as unset despite your .env file looking correct."
        )

    parser = argparse.ArgumentParser(prog="rag.main")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Run stage 01")
    ingest_parser.add_argument(
        "--domain", action="append", default=None,
        help="Restrict to one domain. Repeatable. Defaults to all approved domains.",
    )
    ingest_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    ingest_parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    ingest_parser.add_argument(
        "--max-pages", type=int, default=DEFAULT_MAX_PAGES,
        help=f"Safety cap per domain (default {DEFAULT_MAX_PAGES}). Raise this if a "
             "domain's manifest shows truncated: true and the missing pages matter.",
    )

    extract_parser = subparsers.add_parser("extract", help="Run stage 02 against an already-ingested domain")
    extract_parser.add_argument("--domain", action="append", required=True, help="Repeatable.")
    extract_parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    extract_parser.add_argument("--extracted-dir", type=Path, default=DEFAULT_EXTRACTED_DIR)

    chunk_parser = subparsers.add_parser("chunk", help="Run stage 03 against an already-extracted domain")
    chunk_parser.add_argument("--domain", action="append", required=True, help="Repeatable.")
    chunk_parser.add_argument("--extracted-dir", type=Path, default=DEFAULT_EXTRACTED_DIR)
    chunk_parser.add_argument("--chunked-dir", type=Path, default=DEFAULT_CHUNKED_DIR)

    index_parser = subparsers.add_parser("index", help="Run stage 04 against an already-chunked domain")
    index_parser.add_argument("--domain", action="append", required=True, help="Repeatable.")
    index_parser.add_argument("--chunked-dir", type=Path, default=DEFAULT_CHUNKED_DIR)
    index_parser.add_argument(
        "--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
        help=f"Embedding batch size (default {DEFAULT_BATCH_SIZE}). Raise it if your machine "
             "has GPU/memory to spare; lower it if encoding runs out of memory.",
    )

    retrieve_parser = subparsers.add_parser(
        "retrieve", help="Run stage 05 hybrid retrieval against a real query"
    )
    retrieve_parser.add_argument("query", help="The question to search for, in quotes.")
    retrieve_parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K_FINAL)
    retrieve_parser.add_argument(
        "--no-rerank", action="store_true",
        help="Skip the bge-reranker-v2-m3 cross-encoder step - useful for the README's own "
             "DONE criterion: measure hit@3 before and after the reranker, and drop it if it "
             "doesn't move the number.",
    )

    verify_parser = subparsers.add_parser(
        "verify", help="Run stage 06 guardrails over the adversarial draft fixture"
    )
    verify_parser.add_argument(
        "--drafts", type=Path, default=DEFAULT_DRAFTS_PATH,
        help="Draft fixture to grade (default: rag/fixtures/f06_drafts.json).",
    )
    verify_parser.add_argument(
        "--grounding", action="store_true",
        help="Also run the NLI grounding check. First use downloads the cross-encoder "
             "(~500MB). Without this flag only the three deterministic checks run.",
    )

    args = parser.parse_args()

    if args.command == "ingest":
        results = ingest(args.domain, args.config, args.cache_dir, max_pages=args.max_pages)
        for domain, pages in results.items():
            print(f"{domain}: {len(pages)} pages")
    elif args.command == "extract":
        for domain in args.domain:
            _run_extract(domain, args.cache_dir, args.extracted_dir)
    elif args.command == "chunk":
        for domain in args.domain:
            _run_chunk(domain, args.extracted_dir, args.chunked_dir)
    elif args.command == "index":
        for domain in args.domain:
            _run_index(domain, args.chunked_dir, args.batch_size)
    elif args.command == "retrieve":
        _run_retrieve(args.query, args.top_k, use_reranker=not args.no_rerank)
    elif args.command == "verify":
        _run_verify(args.drafts, use_grounding=args.grounding)


if __name__ == "__main__":
    main()
