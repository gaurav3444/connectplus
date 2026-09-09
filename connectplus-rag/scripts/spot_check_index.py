"""Manual spot-check: embeds a query and finds the most similar chunks
already sitting in Supabase, so you can eyeball whether stage 04's
indexing actually retrieves sensible results.

This is NOT stage 06 (hybrid retrieval) - that will properly combine this
vector search with keyword search (RRF fusion), rerank the results, and
produce a confidence score. This script only does the vector half, with
no fusion or reranking, purely so you can sanity-check the embeddings
before building on top of them. Not part of the tested `rag` package -
a one-off verification tool, not a pipeline stage.

Usage:
    python3 scripts/spot_check_index.py "how do I know if a text message is a scam"
    python3 scripts/spot_check_index.py "what is mygov"
"""

from __future__ import annotations

import os
import sys

import psycopg2
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

load_dotenv()


def main() -> None:
    query = " ".join(sys.argv[1:]) or "how do I know if a text message is a scam"
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set - check your .env file (see rag/main.py's error message "
              "for the same diagnostic steps used elsewhere in this project).")
        return

    print(f"Query: {query!r}")
    print("Loading BGE-m3 (CPU)... (first run may take a moment, no download needed if stage 04 already ran)")
    model = SentenceTransformer("BAAI/bge-m3", device="cpu")
    vector = model.encode([query])[0].tolist()
    # Explicit pgvector literal format ("[0.1,0.2,...]"), not relying on
    # psycopg2's default list-to-array adaptation - untested against a
    # live database from this end (same caveat as make_postgres_upserter),
    # so this removes one source of doubt rather than assuming it's fine.
    vector_literal = "[" + ",".join(str(x) for x in vector) + "]"

    with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select url, heading_path, left(text, 250), 1 - (embedding <=> %s::vector) as similarity
            from chunks
            order by embedding <=> %s::vector
            limit 5
            """,
            (vector_literal, vector_literal),
        )
        results = cur.fetchall()

    print(f"\nTop {len(results)} matches:\n")
    for i, (url, heading_path, snippet, similarity) in enumerate(results, 1):
        print(f"#{i}  similarity={similarity:.3f}")
        print(f"    url: {url}")
        print(f"    heading_path: {heading_path}")
        print(f"    text: {snippet}...")
        print()


if __name__ == "__main__":
    main()
