"""Tests for stage 04.

Uses fake embed and upsert functions throughout — never the real BGE-m3
model or a real Postgres connection. This sandbox can't download a 2GB
model or reach a live database, so what's tested here is the batching,
validation, and row-shaping LOGIC, not the real model or the real
database. get_default_embedder() and make_postgres_upserter() are the
production code paths and are genuinely untested by me.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rag.s02_extract import extract_pages, load_extraction_inputs_from_fixture
from rag.s03_chunk import chunk_docs
from rag.s04_embed import (
    DEFAULT_EMBEDDING_DIM,
    _to_row,
    embed_chunks,
    index_chunks,
)
from rag.schemas import Chunk

FIXTURES_DIR = Path(__file__).parent.parent / "rag" / "fixtures"


def fake_embedder(dim: int = DEFAULT_EMBEDDING_DIM):
    """Deterministic fake: same text always produces the same vector
    (hash-based), different texts produce different vectors — enough to
    test batching and row-shaping without a real model."""
    def embed(texts: list[str]) -> list[list[float]]:
        return [[float((hash(t) + i) % 1000) / 1000 for i in range(dim)] for t in texts]
    return embed


def _chunk(chunk_id="c1", text="Some real chunk text, long enough to be plausible.") -> Chunk:
    return Chunk(
        id=chunk_id, doc_id="doc-1", url="https://example.test/page", domain="example.test",
        title="Test", lang="en", fetched_at="2026-01-01T00:00:00+00:00",
        heading_path=["A", "B"], text=text, token_count=10, order_idx=0,
    )


# ---------------------------------------------------------------------------
# Batching and dimension validation
# ---------------------------------------------------------------------------

def test_embed_chunks_produces_one_embedding_per_chunk() -> None:
    chunks = [_chunk(f"c{i}", f"chunk text number {i}") for i in range(5)]
    embedded, _ = embed_chunks(chunks, embed_fn=fake_embedder())
    assert len(embedded) == 5
    assert {e.id for e in embedded} == {c.id for c in chunks}


def test_embed_chunks_respects_batch_size() -> None:
    chunks = [_chunk(f"c{i}") for i in range(10)]
    calls = []

    def counting_embedder(texts):
        calls.append(len(texts))
        return fake_embedder()(texts)

    embedded, batch_count = embed_chunks(chunks, embed_fn=counting_embedder, batch_size=3)
    assert calls == [3, 3, 3, 1]
    assert batch_count == 4
    assert len(embedded) == 10


def test_on_batch_done_callback_fires_once_per_batch_with_correct_totals() -> None:
    """Regression test for a real UX problem: with no progress feedback at
    all, a large domain (Be Connected: 4148 chunks, 259 batches) silently
    encoding on CPU was indistinguishable from a hang and got Ctrl+C'd
    because of it."""
    chunks = [_chunk(f"c{i}") for i in range(10)]
    progress_calls = []

    embed_chunks(
        chunks, embed_fn=fake_embedder(), batch_size=3,
        on_batch_done=lambda done, total: progress_calls.append((done, total)),
    )
    assert progress_calls == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_on_batch_done_is_optional() -> None:
    """Must not require a callback — the core function stays silent and
    easy to test by default."""
    chunks = [_chunk(f"c{i}") for i in range(3)]
    embedded, _ = embed_chunks(chunks, embed_fn=fake_embedder())  # no on_batch_done at all
    assert len(embedded) == 3


def test_embed_chunks_empty_input_makes_no_calls() -> None:
    calls = []

    def embedder(texts):
        calls.append(texts)
        return []

    embedded, batch_count = embed_chunks([], embed_fn=embedder)
    assert embedded == []
    assert batch_count == 0
    assert calls == []


def test_wrong_embedding_dimension_raises_clear_error() -> None:
    chunks = [_chunk()]
    bad_embedder = fake_embedder(dim=768)  # wrong dimension on purpose
    with pytest.raises(ValueError, match="768"):
        embed_chunks(chunks, embed_fn=bad_embedder, expected_dim=1024)


def test_embed_fn_returning_wrong_count_raises_rather_than_misassigning() -> None:
    def broken_embedder(texts):
        return fake_embedder()(texts)[:-1]  # one short

    chunks = [_chunk(f"c{i}") for i in range(3)]
    with pytest.raises(ValueError, match="batching contract"):
        embed_chunks(chunks, embed_fn=broken_embedder, batch_size=10)


def test_embedded_chunk_carries_model_name_and_dimension() -> None:
    chunks = [_chunk()]
    embedded, _ = embed_chunks(chunks, embed_fn=fake_embedder(), model_name="test-model-x")
    assert embedded[0].embedding_model == "test-model-x"
    assert embedded[0].embedding_dim == DEFAULT_EMBEDDING_DIM


# ---------------------------------------------------------------------------
# Row shaping and index orchestration
# ---------------------------------------------------------------------------

def test_to_row_matches_schema_sql_columns() -> None:
    chunks = [_chunk()]
    embedded, _ = embed_chunks(chunks, embed_fn=fake_embedder())
    row = _to_row(embedded[0])
    expected_columns = {
        "id", "doc_id", "url", "domain", "title", "lang", "fetched_at", "heading_path",
        "text", "token_count", "order_idx", "embedding", "embedding_model", "embedding_dim",
    }
    assert set(row.keys()) == expected_columns
    assert row["id"] == "c1"
    assert len(row["embedding"]) == DEFAULT_EMBEDDING_DIM


def test_index_chunks_calls_upsert_with_all_rows() -> None:
    chunks = [_chunk(f"c{i}") for i in range(5)]
    upserted_rows = []

    def fake_upsert(rows):
        upserted_rows.extend(rows)

    summary = index_chunks(chunks, embed_fn=fake_embedder(), upsert_fn=fake_upsert)
    assert summary.total_chunks == 5
    assert summary.embedded == 5
    assert summary.upserted == 5
    assert len(upserted_rows) == 5


def test_index_chunks_requires_an_upsert_function() -> None:
    with pytest.raises(ValueError, match="upsert_fn is required"):
        index_chunks([_chunk()], embed_fn=fake_embedder(), upsert_fn=None)


def test_reindexing_the_same_chunks_is_idempotent_via_upsert_by_id() -> None:
    """Simulates README's stage 04 DONE criterion ("re-ingest is
    idempotent") with an in-memory fake standing in for Postgres's real
    ON CONFLICT (id) DO UPDATE — the real guarantee lives in schema.sql,
    not in this Python code, but this proves upsert_fn always receives
    the same `id` for the same chunk, which is what ON CONFLICT relies on.
    """
    fake_table: dict[str, dict] = {}

    def fake_upsert(rows):
        for row in rows:
            fake_table[row["id"]] = row  # overwrite, not append — mirrors ON CONFLICT DO UPDATE

    chunks = [_chunk(f"c{i}") for i in range(3)]
    index_chunks(chunks, embed_fn=fake_embedder(), upsert_fn=fake_upsert)
    index_chunks(chunks, embed_fn=fake_embedder(), upsert_fn=fake_upsert)  # re-run

    assert len(fake_table) == 3  # not 6 — no duplicates from running twice


def test_upsert_happens_per_batch_not_once_at_the_end() -> None:
    """Regression test for a real, confirmed data-loss scenario: a crash
    on real hardware (PyTorch's Metal/MPS backend running out of GPU
    memory on Apple Silicon) happened mid-run, at batch 99 of 260. The old
    design collected every embedded chunk in memory and only upserted
    once at the very end — meaning that crash would have lost all 98
    already-successfully-embedded batches, since nothing had been written
    to the database yet. upsert_fn must be called once per batch, not once
    overall, so a crash only costs the batch in progress.
    """
    upsert_call_sizes = []

    def fake_upsert(rows):
        upsert_call_sizes.append(len(rows))

    chunks = [_chunk(f"c{i}") for i in range(10)]
    index_chunks(chunks, embed_fn=fake_embedder(), upsert_fn=fake_upsert, batch_size=3)

    assert upsert_call_sizes == [3, 3, 3, 1], "must upsert after each batch, not collect until the end"


def test_crash_partway_through_preserves_earlier_batches() -> None:
    """The actual resilience property that matters: if embedding raises
    partway through, whatever was already upserted must remain — not be
    silently lost because it was only held in memory."""
    fake_table: dict[str, dict] = {}

    def fake_upsert(rows):
        for row in rows:
            fake_table[row["id"]] = row

    def crashes_on_third_batch(texts):
        crashes_on_third_batch.calls += 1
        if crashes_on_third_batch.calls == 3:
            raise RuntimeError("simulated GPU out-of-memory crash")
        return fake_embedder()(texts)
    crashes_on_third_batch.calls = 0

    chunks = [_chunk(f"c{i}") for i in range(10)]
    with pytest.raises(RuntimeError, match="simulated GPU"):
        index_chunks(chunks, embed_fn=crashes_on_third_batch, upsert_fn=fake_upsert, batch_size=3)

    # Batches 1 and 2 (6 chunks) succeeded and were upserted before the crash on batch 3.
    assert len(fake_table) == 6


# ---------------------------------------------------------------------------
# End to end with real stage 01-03 fixture data (fake embedder/upsert only)
# ---------------------------------------------------------------------------

def test_real_fixture_chunks_embed_and_index_end_to_end() -> None:
    def word_count(text):
        return max(1, len(text.split()))

    inputs = load_extraction_inputs_from_fixture(FIXTURES_DIR / "f01_pages.json", FIXTURES_DIR)
    docs, _ = extract_pages(inputs)
    chunks = chunk_docs(docs, count_tokens=word_count)

    upserted_rows = []
    summary = index_chunks(chunks, embed_fn=fake_embedder(), upsert_fn=upserted_rows.extend)

    assert summary.total_chunks == len(chunks)
    assert summary.embedded == len(chunks)
    assert len(upserted_rows) == len(chunks)
    # Every real chunk's embedding must actually have landed at the right dimension.
    assert all(len(row["embedding"]) == DEFAULT_EMBEDDING_DIM for row in upserted_rows)


# ---------------------------------------------------------------------------
# make_postgres_upserter: one reused connection + reconnect/retry
# (fake connection objects only; no real database)
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self):
        self.commits = 0
        self.closed = False

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _fake_db(connect_failures: int = 0, execute_failures: int = 0):
    """connect() raises OperationalError for the first `connect_failures`
    calls; execute_values raises for the first `execute_failures` calls —
    the same error class as the real 'SSL SYSCALL error: EOF detected'."""
    import psycopg2

    log = {"connects": 0, "execute_calls": 0, "connections": [], "executed": [], "sleeps": []}

    def connect(dsn, **kwargs):
        log["connects"] += 1
        if log["connects"] <= connect_failures:
            raise psycopg2.OperationalError("SSL SYSCALL error: EOF detected")
        conn = _FakeConn()
        log["connections"].append(conn)
        return conn

    def execute(cur, query, values):
        log["execute_calls"] += 1
        if log["execute_calls"] <= execute_failures:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        log["executed"].append(values)

    return log, connect, execute


def _rows(n: int, start: int = 0) -> list[dict]:
    embedded, _ = embed_chunks([_chunk(f"c{i}") for i in range(start, start + n)], embed_fn=fake_embedder())
    return [_to_row(c) for c in embedded]


def test_upserter_reuses_one_connection_across_batches() -> None:
    """Real failure: a new connection per batch meant 244 TLS handshakes
    for Be Connected, and one failed handshake killed the run."""
    from rag.s04_embed import make_postgres_upserter

    log, connect, execute = _fake_db()
    upsert = make_postgres_upserter("postgresql://fake", _connect=connect, _execute_values=execute,
                                    _sleep=lambda s: log["sleeps"].append(s))
    for b in range(5):
        upsert(_rows(3, start=b * 3))
    assert log["connects"] == 1
    assert len(log["executed"]) == 5
    assert log["connections"][0].commits == 5


def test_upserter_retries_a_failed_connect_then_succeeds() -> None:
    from rag.s04_embed import DB_RETRY_DELAYS, make_postgres_upserter

    log, connect, execute = _fake_db(connect_failures=2)
    upsert = make_postgres_upserter("postgresql://fake", _connect=connect, _execute_values=execute,
                                    _sleep=lambda s: log["sleeps"].append(s))
    upsert(_rows(3))
    assert log["connects"] == 3
    assert log["sleeps"] == list(DB_RETRY_DELAYS[:2])
    assert len(log["executed"]) == 1                                # the batch landed exactly once


def test_upserter_reconnects_when_an_open_connection_drops_mid_run() -> None:
    from rag.s04_embed import make_postgres_upserter

    log, connect, execute = _fake_db(execute_failures=1)
    upsert = make_postgres_upserter("postgresql://fake", _connect=connect, _execute_values=execute,
                                    _sleep=lambda s: log["sleeps"].append(s))
    upsert(_rows(3))
    assert log["connects"] == 2                                     # dropped one closed, fresh one opened
    assert log["connections"][0].closed is True
    assert len(log["executed"]) == 1


def test_upserter_gives_up_with_a_clear_error_after_all_retries() -> None:
    from rag.s04_embed import DB_RETRY_DELAYS, make_postgres_upserter

    log, connect, execute = _fake_db(connect_failures=99)
    upsert = make_postgres_upserter("postgresql://fake", _connect=connect, _execute_values=execute,
                                    _sleep=lambda s: log["sleeps"].append(s))
    with pytest.raises(RuntimeError, match="re-running the same command is safe"):
        upsert(_rows(3))
    assert log["connects"] == len(DB_RETRY_DELAYS) + 1


def test_upserter_does_not_retry_non_connection_errors() -> None:
    """A bad row or schema mismatch can't be fixed by retrying — raise at once."""
    from rag.s04_embed import make_postgres_upserter

    log, connect, _ = _fake_db()

    def bad_execute(cur, query, values):
        raise ValueError("column mismatch")

    upsert = make_postgres_upserter("postgresql://fake", _connect=connect, _execute_values=bad_execute,
                                    _sleep=lambda s: log["sleeps"].append(s))
    with pytest.raises(ValueError, match="column mismatch"):
        upsert(_rows(1))
    assert log["sleeps"] == []
