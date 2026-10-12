"""Screen 3a (Browse topics): the taxonomy, and turning retrieved chunks into
one resource card per page. Uses the real f03 chunks, as every stage does."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import rag.api
from rag import REFUSAL_THRESHOLD, browse, browse_topics
from rag.browse import MAX_PER_LEVEL, find_subcategory, resources_from_chunks
from rag.s06_verify import load_approved_domains
from rag.schemas import Retrieved

F03 = Path(__file__).parent.parent / "rag" / "fixtures" / "f03_chunks.json"
CHUNKS = json.loads(F03.read_text(encoding="utf-8"))
APPROVED = load_approved_domains()


def _retrieved(scores: list[float], **overrides: str) -> list[Retrieved]:
    """The first len(scores) fixture chunks, scored best-first like retrieve() returns them."""
    return [
        Retrieved(**{**chunk, **overrides}, score=score, method="fused")
        for chunk, score in zip(CHUNKS, scores)
    ]


def test_taxonomy_respects_the_seven_per_level_rule_and_ids_are_unique() -> None:
    categories = browse_topics()

    assert 0 < len(categories) <= MAX_PER_LEVEL
    assert len({c.id for c in categories}) == len(categories)
    for category in categories:
        assert 0 < len(category.subcategories) <= MAX_PER_LEVEL, category.id
        assert len({s.id for s in category.subcategories}) == len(category.subcategories), category.id
        assert all(s.query.strip() for s in category.subcategories), category.id


def test_unknown_subcategory_is_a_key_error() -> None:
    assert find_subcategory("staying-safe", "passwords").title == "Passwords"
    with pytest.raises(KeyError):
        find_subcategory("staying-safe", "no-such-thing")


def test_chunks_of_one_page_collapse_into_one_resource_carrying_its_best_chunk() -> None:
    # The first five f03 chunks are all from the same Be Connected page.
    chunks = _retrieved([0.6, 0.9, 0.7, 0.8, 0.5])
    assert len({c.doc_id for c in chunks}) == 1

    resources = resources_from_chunks(chunks, APPROVED, REFUSAL_THRESHOLD)

    assert len(resources) == 1
    assert resources[0].score == 0.9
    assert resources[0].snippet == chunks[1].text[:200].rstrip()
    assert resources[0].url == str(chunks[0].url)


def test_distinct_pages_are_ordered_best_first_and_capped_at_seven() -> None:
    chunks = [
        Retrieved(**{**chunk, "doc_id": f"doc-{i}"}, score=0.5 + i / 100, method="vector")
        for i, chunk in enumerate(CHUNKS[:10])
    ]

    resources = resources_from_chunks(chunks, APPROVED, REFUSAL_THRESHOLD)

    assert [r.doc_id for r in resources] == [f"doc-{i}" for i in range(9, 2, -1)]


def test_weak_matches_are_not_listed_so_the_empty_state_shows() -> None:
    weak = _retrieved([REFUSAL_THRESHOLD - 0.01] * 3)

    assert resources_from_chunks(weak, APPROVED, REFUSAL_THRESHOLD) == []


def test_a_page_from_a_domain_no_longer_approved_is_not_listed() -> None:
    chunks = _retrieved([0.9], domain="evil.example.com")

    assert resources_from_chunks(chunks, APPROVED, REFUSAL_THRESHOLD) == []


def test_browse_runs_the_subcategory_query_through_retrieve(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, int]] = []

    def fake_retrieve(query_en: str, lang: str, k: int) -> tuple[list[Retrieved], float]:
        calls.append((query_en, lang, k))
        return _retrieved([0.9]), 0.9

    monkeypatch.setattr(rag.api, "retrieve", fake_retrieve)
    rag.api._browse.cache_clear()

    first = browse("staying-safe", "passwords", "zh")
    again = browse("staying-safe", "passwords", "en")

    assert calls == [(find_subcategory("staying-safe", "passwords").query, "en", 20)]
    assert first == again and first[0].doc_id == CHUNKS[0]["doc_id"]
