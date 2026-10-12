"""The agreed public surface: retrieve(query_en, lang, k) and verify(draft, chunks).

The stage logic is tested in test_s05_retrieve.py and test_s06_verify.py.
What is tested here is the wiring those files can't see: that k and the
reranker reach stage 05, that retrieve's output feeds verify unchanged, and
that verify takes confidence from the chunks rather than from the draft.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rag.api
import rag.s05_retrieve
from rag import REFUSAL_THRESHOLD, retrieve, verify
from rag.schemas import Chunk

FIXTURE = Path(__file__).parent.parent / "rag" / "fixtures" / "f06_drafts.json"
SPEC = json.loads(FIXTURE.read_text(encoding="utf-8"))
CHUNKS = {c["id"]: Chunk.model_validate(c) for c in SPEC["chunks"]}
DRAFTS = {d["id"]: d for d in SPEC["drafts"]}
IDS = list(CHUNKS)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Production dependencies swapped for fakes. Returns the reranker's
    per-chunk scores so a test can set how confident retrieval is."""
    rerank_scores = {IDS[0]: 0.9, IDS[1]: 0.6, IDS[2]: 0.1}

    def search(_query: object, top_k: int) -> list[tuple[str, float]]:
        return [(cid, 1.0) for cid in IDS[:top_k]]

    monkeypatch.setattr(
        rag.api, "_search_fns",
        lambda: (search, search, lambda ids: {i: CHUNKS[i] for i in ids}),
    )
    monkeypatch.setattr(
        rag.api, "get_default_reranker",
        lambda: lambda _q, texts: [
            next(rerank_scores[c.id] for c in CHUNKS.values() if c.text == t) for t in texts
        ],
    )
    monkeypatch.setattr(rag.s05_retrieve, "get_default_embedder", lambda _name: lambda qs: [[0.0]] * len(qs))
    monkeypatch.setattr(rag.api, "get_default_entailment", lambda *_args: lambda p, h: [1.0] * len(p))
    return rerank_scores


def test_retrieve_honours_k_and_confidence_is_the_top_reranked_score(wired: dict[str, float]) -> None:
    chunks, confidence = retrieve("how do I spot a scam text", "zh", 2)

    assert [c.id for c in chunks] == [IDS[0], IDS[1]]
    assert confidence == wired[IDS[0]] == chunks[0].score


def test_retrieve_then_verify_passes_a_grounded_cited_answer(wired: dict[str, float]) -> None:
    chunks, _ = retrieve("how do I spot a scam text", "zh", 2)

    verdict = verify(DRAFTS["d01-good-answer"]["answer_md"], chunks, lang="zh")

    assert verdict.passed, verdict.reason
    assert verdict.chunk_ids == [IDS[0], IDS[1]]


def test_verify_accepts_the_answer_envelope_and_chunks_as_json(wired: dict[str, float]) -> None:
    chunks, _ = retrieve("reply with the code", "zh", 2)
    as_json = [c.model_dump(mode="json") for c in chunks]

    verdict = verify({"answer_md": DRAFTS["d05-reply-with-the-code"]["answer_md"]}, as_json)

    assert verdict.reason == "unsafe"


def test_a_draft_cannot_vouch_for_its_own_confidence(wired: dict[str, float]) -> None:
    wired.update({IDS[0]: 0.2, IDS[1]: 0.1})
    chunks, _ = retrieve("something the corpus doesn't cover", "zh", 2)

    draft = {"answer_md": DRAFTS["d01-good-answer"]["answer_md"], "confidence": 0.99}

    assert max(wired.values()) < REFUSAL_THRESHOLD
    assert verify(draft, chunks).reason == "low_confidence"


def test_missing_database_url_is_an_error_not_an_empty_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(rag.api, "ENV_PATH", tmp_path / ".env")
    rag.api._search_fns.cache_clear()

    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        retrieve("anything", "en", 3)
