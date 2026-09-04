"""CLI entry point. Wires up stages 01, 02, 03, and 04.

Usage (from README_rag.md, extended for 02, 03, and 04):
    python -m rag.main ingest
    python -m rag.main ingest --domain scamwatch.gov.au
    python -m rag.main extract --domain scamwatch.gov.au
    python -m rag.main chunk --domain scamwatch.gov.au
    python -m rag.main index --domain scamwatch.gov.au

`index` reads DATABASE_URL from a .env file in the project root (or the
real environment) — Supabase's SESSION POOLER connection string
specifically (dashboard -> "Connect" -> "Session pooler"), not "Direct
connection" and not "Project URL". Confirmed real issue: Supabase's
direct connection only resolves over IPv6 by default, which fails with
"No route to host" on networks that don't route IPv6 — the session
pooler works over IPv4. See .env.example and rag/config/schema.sql.
"""

from __future__ import annotations

import argparse
import json
import os
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
from rag.schemas import Chunk, ExtractedDoc

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config" / "approved_domains.json"
DEFAULT_CACHE_DIR = Path(".cache/html")
DEFAULT_EXTRACTED_DIR = Path(".cache/extracted")
DEFAULT_CHUNKED_DIR = Path(".cache/chunked")


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
    out_path.write_text(json.dumps([d.model_dump(mode="json") for d in docs], ensure_ascii=False, indent=2))

    print(f"{domain}: {summary.extracted}/{summary.total_input_pages} pages extracted -> {out_path}")
    print(f"  skipped non-200: {summary.skipped_non_200_status}")
    print(f"  skipped unsupported content-type: {summary.skipped_unsupported_content_type}")
    print(f"  skipped empty after extraction: {summary.skipped_empty_after_extraction}")
    print(f"  deduplicated (exact text match): {summary.deduplicated_exact_text_matches}")


def _run_chunk(domain: str, extracted_dir: Path, chunked_dir: Path) -> None:
    extracted_path = extracted_dir / f"{domain}.json"
    if not extracted_path.exists():
        print(f"{domain}: no extracted docs found at {extracted_path} — run `extract` for this domain first")
        return

    docs = [ExtractedDoc.model_validate(d) for d in json.loads(extracted_path.read_text())]
    chunks = chunk_docs(docs)  # real BGE-m3 tokenizer here — no injected counter in production use

    chunked_dir.mkdir(parents=True, exist_ok=True)
    out_path = chunked_dir / f"{domain}.json"
    out_path.write_text(json.dumps([c.model_dump(mode="json") for c in chunks], ensure_ascii=False, indent=2))

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
        print(f"{domain}: no chunked file found at {chunked_path} — run `chunk` for this domain first")
        return

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        env_path = Path(__file__).parent.parent / ".env"
        print(
            f"DATABASE_URL is not set. Checked for a .env file at: {env_path}\n"
            "  - Does that file exist and contain a DATABASE_URL=... line?\n"
            "  - Is python-dotenv installed? "
            "(`python3 -c \"import dotenv\"` should print nothing, not an error)\n"
            "  - Use Supabase's SESSION POOLER connection string (dashboard -> Connect -> "
            "'Session pooler'), not 'Direct connection' or 'Project URL' — direct connections "
            "often fail with IPv6 routing issues; the pooler works over IPv4."
        )
        return

    chunks = [Chunk.model_validate(c) for c in json.loads(chunked_path.read_text())]
    upsert_fn = make_postgres_upserter(db_url)

    def print_progress(done: int, total: int) -> None:
        print(f"  embedding batch {done}/{total}...", end="\r", flush=True)

    summary = index_chunks(chunks, upsert_fn=upsert_fn, batch_size=batch_size, on_batch_done=print_progress)
    print()  # move past the \r-overwritten progress line

    print(f"{domain}: {summary.embedded}/{summary.total_chunks} chunks embedded and upserted")
    print(f"  model: {summary.embedding_model} ({summary.embedding_dim}-dim)")
    print(f"  batches: {summary.batches}")


def main() -> None:
    # Load a .env file if present — the natural place for DATABASE_URL to
    # live, matching README_rag.md's `cp .env.example .env` setup step.
    # Explicit path (project root, i.e. one level up from this file's own
    # rag/ package directory) rather than relying on load_dotenv()'s
    # implicit cwd-based search — that search is relative to where the
    # command happens to be run from, which is fragile. A missing
    # python-dotenv install now prints a clear warning instead of silently
    # doing nothing: that silence is exactly what made a real, confirmed
    # case of this ("DATABASE_URL is not set" despite a correctly filled
    # .env file) confusing to diagnose — stages 01-03 still work fine
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


if __name__ == "__main__":
    main()
