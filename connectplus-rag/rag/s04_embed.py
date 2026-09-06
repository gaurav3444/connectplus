"""Stage 04 — Embed + Index.

BGE-m3 embeddings (1024-dim, multilingual — confirmed via search, not
assumed) via sentence-transformers, batched, written to Supabase Postgres
with pgvector (HNSW) for vector search and a generated tsvector column for
keyword search. Stage 06 needs both from the same database, same
connection — that's the whole reason README_rag.md picked this stack.

Design decisions made explicit here:

- Both the embedding function and the database write are injectable
  (EmbedFunction, UpsertFunction), same testability reasoning as
  stage 03's token counter: BGE-m3 is a ~2GB download and Supabase is a
  live external database, neither of which this sandbox can reach. The
  batching and idempotency LOGIC is tested here against deterministic
  fakes; get_default_embedder() and make_postgres_upserter() are the real
  implementations production code calls — genuinely untested by me. You
  are the first to run them against a real model and a real database.
- Idempotency (README stage 04 DONE: "Re-ingest is idempotent — running
  twice produces no duplicate chunks") is upsert-by-id, not
  check-then-insert. chunk.id is already a stable, deterministic hash
  (doc_id + order_idx) from stage 03, so `ON CONFLICT (id) DO UPDATE` is
  simpler and race-free compared to a separate existence check before
  inserting.
- Batch size defaults conservatively (16) rather than the larger batches
  some BGE-m3 examples use, since this runs on whatever hardware you
  have, not a GPU cluster — CPU-only encoding is the expected case for a
  student prototype, and a smaller batch fails more gracefully on
  memory-constrained machines. Override with --batch-size if your
  machine can handle more.
- get_default_embedder() forces device="cpu" explicitly, rather than
  letting sentence-transformers auto-select a GPU backend. Confirmed
  necessary, not just cautious: on real hardware (Apple M3), PyTorch's
  Metal/MPS GPU backend ran out of memory partway through a real
  indexing run (crashed at batch 99 of 260) — a known class of issue
  with MPS not always releasing memory cleanly across many sequential
  batches. CPU is slower but doesn't have this failure mode.
- Embedding dimension is validated against what the model actually
  returns, not just assumed to be 1024: if a different model is swapped
  in later (env var change, per README_llm.md's "swapping providers is
  config" philosophy applied here too) and it returns a different
  dimension, that mismatches the fixed `vector(1024)` column type at
  insert time with a clear Postgres error — validating earlier, in
  Python, gives a clearer message pointing at the actual cause.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache

from rag.schemas import Chunk, EmbeddedChunk, IndexRunSummary

logger = logging.getLogger("rag.embed")

DEFAULT_MODEL_NAME = "BAAI/bge-m3"
DEFAULT_EMBEDDING_DIM = 1024
DEFAULT_BATCH_SIZE = 16

EmbedFunction = Callable[[list[str]], list[list[float]]]
UpsertFunction = Callable[[list[dict]], None]


@lru_cache(maxsize=1)
def get_default_embedder(model_name: str = DEFAULT_MODEL_NAME) -> EmbedFunction:
    """Real BGE-m3 via sentence-transformers, loaded once per process.
    Not used by any test in this repo — this sandbox can't download the
    ~2GB model to verify it actually works, so tests inject a stand-in
    embedder instead (see tests/test_s04_embed.py). This function is what
    production code (the CLI) actually calls.
    """
    from sentence_transformers import SentenceTransformer

    # device="cpu" is deliberate, not the default: a real crash on Apple
    # Silicon (M3) confirmed PyTorch's Metal/MPS GPU backend can run out
    # of memory partway through a long embedding run (crashed at batch
    # 99/260) — a known class of issue with MPS not always releasing
    # memory cleanly across many sequential batches. CPU is slower but
    # doesn't have this failure mode, and reliability matters more than
    # speed for a one-time indexing job.
    model = SentenceTransformer(model_name, device="cpu")

    def embed(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, show_progress_bar=False).tolist()

    return embed


def embed_chunks(
    chunks: list[Chunk],
    embed_fn: EmbedFunction | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    expected_dim: int = DEFAULT_EMBEDDING_DIM,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch_done: Callable[[int, int], None] | None = None,
    on_batch_embedded: Callable[[list[EmbeddedChunk]], None] | None = None,
) -> tuple[list[EmbeddedChunk], int]:
    """Embeds chunks in batches. Returns (embedded_chunks, batch_count).

    Raises ValueError immediately if the embedder's actual output
    dimension doesn't match expected_dim — see the module docstring for
    why this check exists here rather than surfacing as an opaque
    Postgres type-mismatch error later.

    on_batch_done(completed, total), if given, fires after every batch —
    real, confirmed need: with no feedback at all, a large domain (Be
    Connected: 4148 chunks, 259 batches) silently encoding on CPU is
    indistinguishable from a hang, and got Ctrl+C'd because of it.

    on_batch_embedded(batch_chunks), if given, fires with just that
    batch's EmbeddedChunks — real, confirmed need: index_chunks uses this
    to upsert incrementally rather than only at the very end, after a real
    crash (PyTorch's Metal/MPS backend running out of GPU memory on Apple
    Silicon, mid-run) lost all progress from 98 already-successfully-
    embedded batches because nothing had been written to the database yet.

    Both callbacks are optional and separate from the core loop (not bare
    calls to print()/a database) so this function stays silent, has no
    side effects, and is easy to test — the CLI supplies real
    implementations; tests don't need to care about either.
    """
    embed_fn = embed_fn or get_default_embedder(model_name)
    if not chunks:
        return [], 0

    embedded: list[EmbeddedChunk] = []
    batch_count = 0
    total_batches = (len(chunks) + batch_size - 1) // batch_size
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vectors = embed_fn([c.text for c in batch])
        batch_count += 1

        if len(vectors) != len(batch):
            raise ValueError(
                f"embed_fn returned {len(vectors)} vectors for {len(batch)} texts — "
                "batching contract broken, refusing to guess which vector belongs to which chunk"
            )

        batch_embedded: list[EmbeddedChunk] = []
        for chunk, vector in zip(batch, vectors):
            if len(vector) != expected_dim:
                raise ValueError(
                    f"Expected {expected_dim}-dim embeddings from {model_name!r}, got "
                    f"{len(vector)}-dim. The `chunks` table's vector(1024) column won't accept "
                    "this — check DEFAULT_EMBEDDING_DIM matches the model actually in use."
                )
            batch_embedded.append(EmbeddedChunk(
                id=chunk.id, doc_id=chunk.doc_id, url=chunk.url, domain=chunk.domain,
                title=chunk.title, lang=chunk.lang, fetched_at=chunk.fetched_at,
                heading_path=chunk.heading_path, text=chunk.text, token_count=chunk.token_count,
                order_idx=chunk.order_idx, embedding=vector, embedding_model=model_name,
                embedding_dim=expected_dim,
            ))

        embedded.extend(batch_embedded)
        if on_batch_embedded:
            on_batch_embedded(batch_embedded)
        if on_batch_done:
            on_batch_done(batch_count, total_batches)

    return embedded, batch_count


def _to_row(chunk: EmbeddedChunk) -> dict:
    """One EmbeddedChunk -> one row dict matching rag/config/schema.sql's
    column names exactly. Kept as its own function so the real Postgres
    upserter and any test/fake upserter agree on the same shape.
    """
    return {
        "id": chunk.id, "doc_id": chunk.doc_id, "url": str(chunk.url), "domain": chunk.domain,
        "title": chunk.title, "lang": chunk.lang, "fetched_at": chunk.fetched_at.isoformat(),
        "heading_path": chunk.heading_path, "text": chunk.text, "token_count": chunk.token_count,
        "order_idx": chunk.order_idx, "embedding": chunk.embedding,
        "embedding_model": chunk.embedding_model, "embedding_dim": chunk.embedding_dim,
    }


def make_postgres_upserter(connection_string: str) -> UpsertFunction:
    """Real Supabase/Postgres upsert via psycopg2. Not used by any test in
    this repo — this sandbox has no live database to verify it against.
    Untested by me; you are the first to run this against a real database.
    """
    import psycopg2
    from psycopg2.extras import execute_values

    columns = [
        "id", "doc_id", "url", "domain", "title", "lang", "fetched_at", "heading_path",
        "text", "token_count", "order_idx", "embedding", "embedding_model", "embedding_dim",
    ]
    update_clause = ", ".join(f"{col} = excluded.{col}" for col in columns if col != "id")

    def upsert(rows: list[dict]) -> None:
        if not rows:
            return
        values = [tuple(row[col] for col in columns) for row in rows]
        query = f"""
            insert into chunks ({", ".join(columns)})
            values %s
            on conflict (id) do update set {update_clause}, indexed_at = now()
        """
        with psycopg2.connect(connection_string) as conn, conn.cursor() as cur:
            execute_values(cur, query, values)
            conn.commit()

    return upsert


def index_chunks(
    chunks: list[Chunk],
    embed_fn: EmbedFunction | None = None,
    upsert_fn: UpsertFunction | None = None,
    model_name: str = DEFAULT_MODEL_NAME,
    expected_dim: int = DEFAULT_EMBEDDING_DIM,
    batch_size: int = DEFAULT_BATCH_SIZE,
    on_batch_done: Callable[[int, int], None] | None = None,
) -> IndexRunSummary:
    """Orchestrates embed_chunks -> _to_row -> upsert_fn for a full domain's
    worth of chunks, upserting after EVERY batch rather than once at the
    end. upsert_fn defaults to None deliberately (not to
    make_postgres_upserter) — a connection string is required to build a
    real one, and this function shouldn't silently assume where that
    comes from; the CLI wires that up explicitly.

    Per-batch upserting is a real, confirmed fix, not a hypothetical
    safety measure: a crash on real hardware (PyTorch's Metal/MPS backend
    running out of GPU memory on Apple Silicon, mid-run at batch 99/260)
    previously lost all progress, because the old version collected every
    embedded chunk in memory and only upserted once at the very end. Now a
    crash only costs the batch in progress when it happened — everything
    upserted before that stays in the database, and thanks to
    upsert-by-id, simply re-running the whole command afterward is safe
    (re-embeds and overwrites already-good rows with identical data,
    rather than duplicating them).
    """
    if upsert_fn is None:
        raise ValueError(
            "upsert_fn is required — build one with make_postgres_upserter(connection_string) "
            "for real use, or pass a fake for testing."
        )

    upserted_count = 0

    def upsert_batch(batch_chunks: list[EmbeddedChunk]) -> None:
        nonlocal upserted_count
        rows = [_to_row(c) for c in batch_chunks]
        upsert_fn(rows)
        upserted_count += len(rows)

    embedded, batch_count = embed_chunks(
        chunks, embed_fn=embed_fn, model_name=model_name,
        expected_dim=expected_dim, batch_size=batch_size,
        on_batch_done=on_batch_done, on_batch_embedded=upsert_batch,
    )

    return IndexRunSummary(
        total_chunks=len(chunks), embedded=len(embedded), upserted=upserted_count,
        embedding_model=model_name, embedding_dim=expected_dim, batches=batch_count,
    )
