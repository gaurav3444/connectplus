"""Eval harness - the measurement stage 05's DONE criterion depends on.

    stage 05 (retrieval): "hit@3 baseline recorded over the eval set, in
        Mandarin as well as English. Measure before and after the reranker
        - if it doesn't move the number, drop it."

One command, one table. Needs a live DATABASE_URL (see .env.example).
Queries go to retrieval exactly as written; query understanding (rewriting
into English) belongs to connectplus-llm, not this repo.

    python scripts/eval_queries.py                 # reranker on, both languages
    python scripts/eval_queries.py --no-rerank     # the before half of before/after
    python scripts/eval_queries.py --lang en       # one language only

A "hit" means the expected page appears in the top 3 results. Chunk-level
retrieval means several chunks can come from the same page, so rank is
measured over distinct pages, not raw result positions - otherwise three
chunks off one page would fill the top 3 and make hit@3 meaningless.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rag.s05_retrieve import (  # noqa: E402
    get_default_reranker,
    make_postgres_chunk_fetcher,
    make_postgres_keyword_search,
    make_postgres_vector_search,
    retrieve,
)

EVAL_PATH = REPO_ROOT / "rag" / "fixtures" / "eval_queries.json"
HIT_AT = 3


def load_db_url() -> str:
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=REPO_ROOT / ".env")
    except ImportError:
        pass
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        sys.exit(
            "DATABASE_URL is not set. Copy .env.example to .env and fill in your Supabase "
            "SESSION POOLER connection string."
        )
    return db_url


def distinct_urls(results: list) -> list[str]:
    """Result URLs, deduplicated, in rank order.

    Distinct pages, not raw results: chunk-level retrieval routinely
    returns several chunks from the same URL, and counting those
    separately would let one page occupy the whole top 3 and make hit@3
    meaningless.
    """
    seen: list[str] = []
    for r in results:
        url = str(r.url)
        if url not in seen:
            seen.append(url)
    return seen


def first_hit_rank(results: list, expect_url_contains: str | None) -> int | None:
    """1-based rank of the expected page among distinct pages, or None.

    None also when there is no expectation to check - see run_one().
    """
    if not expect_url_contains:
        return None
    for i, url in enumerate(distinct_urls(results), start=1):
        if expect_url_contains in url:
            return i
    return None


def run_one(
    query: str,
    lang: str,
    expect: str | None,
    backends: dict,
    use_rerank: bool,
):
    results, confidence = retrieve(
        query,
        vector_search_fn=backends["vector"],
        keyword_search_fn=backends["keyword"],
        fetch_chunks_fn=backends["fetch"],
        rerank_fn=backends["rerank"] if use_rerank else None,
    )
    rank = first_hit_rank(results, expect)
    methods = {r.method for r in results}
    return {
        "query": query,
        "rank": rank,
        "hit": rank is not None and rank <= HIT_AT,
        # An unscored row. Its expected page is not filled in yet, so it
        # contributes to neither the numerator nor the denominator -
        # counting it as a miss would understate retrieval, and guessing an
        # expectation would be worse. Its top URLs are printed instead, so
        # the first run is what completes the eval set.
        "unset": not expect,
        "top_urls": distinct_urls(results)[:HIT_AT],
        "confidence": confidence,
        # Whether the keyword half contributed anything at all. This is the
        # single number that catches an English-only tsvector silently
        # eating a Mandarin query: all-"vector" means half the system did
        # nothing and nobody was told.
        "keyword_contributed": bool(methods & {"keyword", "fused"}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--lang", choices=["en", "zh", "both"], default="both")
    args = parser.parse_args()

    for stream in (sys.stdout, sys.stderr):  # see rag/main.py:_use_utf8_stdout
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    db_url = load_db_url()
    spec = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    langs = ["en", "zh"] if args.lang == "both" else [args.lang]
    use_rerank = not args.no_rerank

    backends = {
        "vector": make_postgres_vector_search(db_url),
        "keyword": make_postgres_keyword_search(db_url),
        "fetch": make_postgres_chunk_fetcher(db_url),
        "rerank": get_default_reranker() if use_rerank else None,
    }

    print(f"reranker: {'ON' if use_rerank else 'OFF'}\n")

    tallies = {lang: [0, 0] for lang in langs}  # [hits, scored]
    keyword_dead = {lang: 0 for lang in langs}
    unset_report: list[tuple[str, str, list[str]]] = []

    for lang in langs:
        print(f"=== {lang.upper()} " + "=" * 62)
        print(f"{'id':<26}{'hit@3':<8}{'rank':<7}{'conf':<8}{'kw':<5}query")
        print("-" * 78)
        for q in spec["queries"]:
            out = run_one(q[lang], lang, q["expect_url_contains"], backends, use_rerank)
            if out["unset"]:
                verdict = "UNSET"
                unset_report.append((q["id"], lang, out["top_urls"]))
            else:
                verdict = "yes" if out["hit"] else "NO"
                tallies[lang][1] += 1
                tallies[lang][0] += int(out["hit"])
            if not out["keyword_contributed"]:
                keyword_dead[lang] += 1
            rank = str(out["rank"]) if out["rank"] else "-"
            print(
                f"{q['id']:<26}{verdict:<8}{rank:<7}"
                f"{out['confidence']:<8.3f}{'y' if out['keyword_contributed'] else 'n':<5}"
                f"{out['query'][:36]}"
            )
        print()

    print("=== REFUSAL SET (low confidence is the correct answer here) " + "=" * 10)
    for q in spec["refusal_queries"]:
        for lang in langs:
            out = run_one(q[lang], lang, "\x00never-matches", backends, use_rerank)
            print(f"{q['id']:<22}{lang:<5}confidence={out['confidence']:.3f}   {out['query'][:40]}")
    print()

    if unset_report:
        print("=== UNSCORED - expected page not set yet " + "=" * 30)
        print(
            "These rows have no expected page, so they count neither for nor against\n"
            "hit@3. Below is what retrieval actually returned. Pick the correct page,\n"
            "put a distinctive part of its path (never a bare hostname) into\n"
            "rag/fixtures/eval_queries.json as expect_url_contains, and re-run.\n"
        )
        for qid, lang, urls in unset_report:
            print(f"{qid}  [{lang}]")
            for i, url in enumerate(urls, 1):
                print(f"    {i}. {url}")
            if not urls:
                print("    (no results at all)")
        print()

    total_queries = len(spec["queries"])
    print("=" * 78)
    for lang in langs:
        hits, scored = tallies[lang]
        pending = total_queries - scored
        line = f"hit@{HIT_AT}  {lang.upper()}: {hits}/{scored} scored"
        if pending:
            line += f"  ({pending} still unset)"
        line += f"    keyword half found nothing on {keyword_dead[lang]}/{total_queries}"
        print(line)
    if any(total_queries - tallies[lang][1] for lang in langs):
        print(
            "\nThis is a PARTIAL baseline. Fill in the unset expected pages above before "
            "quoting these numbers as the stage 05 DONE measurement."
        )
    print(
        "\nRecord both numbers in the README, with and without --no-rerank. If the reranker "
        "doesn't move them, drop it - that is stage 05's own DONE criterion."
    )


if __name__ == "__main__":
    main()
