"""Tests for stage 05 (hybrid retrieval).

Uses controlled fake vector/keyword search functions throughout - not
real BGE-m3, not a real Postgres connection, not the real reranker. This
sandbox can't reach any of those. What's tested here is the actual
retrieval LOGIC (RRF fusion math, method labeling, confidence scoring,
orchestration) using real Chunk objects from the project's own fixture
data where realistic content matters, and simple controlled rankings
where only the fusion/scoring behavior matters. get_default_reranker(),
make_postgres_vector_search(), make_postgres_keyword_search(), and
make_postgres_chunk_fetcher() are the production code paths and are
genuinely untested by me.
"""

from __future__ import annotations

from pathlib import Path

from rag.s02_extract import extract_pages, load_extraction_inputs_from_fixture
from rag.s03_chunk import chunk_docs
from rag.s05_retrieve import (
    RRF_K,
    _method_for,
    _own_raw_score,
    reciprocal_rank_fusion,
    retrieve,
)
from rag.schemas import Chunk

FIXTURES_DIR = Path(__file__).parent.parent / "rag" / "fixtures"


def _word_count(text: str) -> int:
    return max(1, len(text.split()))


def _real_chunks() -> list[Chunk]:
    inputs = load_extraction_inputs_from_fixture(FIXTURES_DIR / "f01_pages.json", FIXTURES_DIR)
    docs, _ = extract_pages(inputs)
    return chunk_docs(docs, count_tokens=_word_count)


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion - pure logic, no fakes needed at all
# ---------------------------------------------------------------------------

def test_rrf_single_ranking_matches_the_formula_directly() -> None:
    ranking = [("a", 0.9), ("b", 0.8), ("c", 0.7)]
    scores = reciprocal_rank_fusion([ranking], k=60)
    assert scores["a"] == 1 / 61
    assert scores["b"] == 1 / 62
    assert scores["c"] == 1 / 63


def test_rrf_agreement_across_both_rankings_beats_appearing_in_only_one() -> None:
    """The whole point of RRF: a chunk both search methods agree on should
    outrank one only a single method found, even at similar individual ranks."""
    vector_ranking = [("agreed", 0.9), ("vector_only", 0.8)]
    keyword_ranking = [("agreed", 5.0), ("keyword_only", 4.0)]
    scores = reciprocal_rank_fusion([vector_ranking, keyword_ranking])
    assert scores["agreed"] > scores["vector_only"]
    assert scores["agreed"] > scores["keyword_only"]


def test_rrf_ignores_the_original_scores_only_uses_rank_position() -> None:
    """RRF is rank-based by design - a vector similarity of 0.99 and a
    keyword ts_rank of 8.2 aren't on the same scale, so RRF must not try
    to compare the raw numbers directly, only their rank positions."""
    ranking_a = [("x", 999.0)]  # huge raw score
    ranking_b = [("x", 0.001)]  # tiny raw score
    scores_a = reciprocal_rank_fusion([ranking_a])
    scores_b = reciprocal_rank_fusion([ranking_b])
    assert scores_a["x"] == scores_b["x"] == 1 / (RRF_K + 1)


def test_rrf_empty_rankings_produce_empty_scores() -> None:
    assert reciprocal_rank_fusion([]) == {}
    assert reciprocal_rank_fusion([[], []]) == {}


# ---------------------------------------------------------------------------
# Method labeling
# ---------------------------------------------------------------------------

def test_method_for_vector_only() -> None:
    assert _method_for("a", vector_ids={"a"}, keyword_ids={"b"}) == "vector"


def test_method_for_keyword_only() -> None:
    assert _method_for("b", vector_ids={"a"}, keyword_ids={"b"}) == "keyword"


def test_method_for_fused_when_both_agree() -> None:
    assert _method_for("a", vector_ids={"a"}, keyword_ids={"a"}) == "fused"


def test_own_raw_score_prefers_vector_when_both_present() -> None:
    assert _own_raw_score("a", vector_scores={"a": 0.8}, keyword_scores={"a": 5.0}) == 0.8


def test_own_raw_score_falls_back_to_keyword_when_vector_absent() -> None:
    assert _own_raw_score("a", vector_scores={}, keyword_scores={"a": 5.0}) == 5.0


def test_own_raw_score_defaults_to_zero_when_absent_from_both() -> None:
    assert _own_raw_score("a", vector_scores={}, keyword_scores={}) == 0.0


# ---------------------------------------------------------------------------
# Full retrieve() orchestration, with real Chunk data and controlled fakes
# ---------------------------------------------------------------------------

def test_retrieve_returns_empty_for_blank_query() -> None:
    results, confidence = retrieve(
        "   ",
        vector_search_fn=lambda v, k: [],
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {},
        embed_fn=lambda texts: [[0.0] * 4 for _ in texts],
    )
    assert results == []
    assert confidence == 0.0


def test_retrieve_returns_empty_when_both_searches_find_nothing() -> None:
    results, confidence = retrieve(
        "something with no matches",
        vector_search_fn=lambda v, k: [],
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {},
        embed_fn=lambda texts: [[0.0] * 4 for _ in texts],
    )
    assert results == []
    assert confidence == 0.0


def test_retrieve_without_reranker_uses_top_vector_similarity_as_confidence() -> None:
    chunks = _real_chunks()
    real_chunk = chunks[0]

    def fake_vector_search(vector, top_k):
        return [(real_chunk.id, 0.71)]

    def fake_keyword_search(query, top_k):
        return []

    results, confidence = retrieve(
        "a real question",
        vector_search_fn=fake_vector_search,
        keyword_search_fn=fake_keyword_search,
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    assert len(results) == 1
    assert results[0].id == real_chunk.id
    assert results[0].method == "vector"
    assert confidence == 0.71
    assert results[0].score == 0.71, "score must be this chunk's own vector similarity"


def test_score_is_never_the_shared_rrf_fusion_value_when_unreranked() -> None:
    """Regression test for a real, confirmed bug: every unreranked result's
    `score` used to be set to the shared internal RRF fusion value (tiny
    numbers capping near 0.03), not that chunk's own similarity - which
    contradicted this module's own documented contract and looked like
    "very low confidence" to anyone reading it without that context.
    """
    chunks = _real_chunks()
    a, b = chunks[0], chunks[1]

    # Rig it so the RRF fusion values would be obviously different from
    # the real per-chunk similarity scores, so the two can't be confused.
    def fake_vector_search(vector, top_k):
        return [(a.id, 0.65), (b.id, 0.60)]

    def fake_keyword_search(query, top_k):
        return [(a.id, 3.2)]  # a appears in both -> "fused"; b is vector-only

    results, _ = retrieve(
        "a real question",
        vector_search_fn=fake_vector_search,
        keyword_search_fn=fake_keyword_search,
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    by_id = {r.id: r for r in results}

    # 'a' is fused (found by both) - score should be its vector similarity
    # (0.65), never an RRF value (which would be a small fraction near 0.03).
    assert by_id[a.id].method == "fused"
    assert by_id[a.id].score == 0.65

    # 'b' is vector-only - same expectation, its own vector similarity.
    assert by_id[b.id].method == "vector"
    assert by_id[b.id].score == 0.60


def test_keyword_only_chunk_gets_its_own_ts_rank_as_score() -> None:
    """The other half of the fix: a chunk found ONLY by keyword search
    (never by vector search) has no vector similarity to fall back to -
    it must get its own keyword ts_rank, not a fabricated or borrowed value."""
    chunks = _real_chunks()
    keyword_only_chunk = chunks[2]

    results, _ = retrieve(
        "a real question",
        vector_search_fn=lambda v, k: [],
        keyword_search_fn=lambda q, k: [(keyword_only_chunk.id, 4.5)],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    assert results[0].method == "keyword"
    assert results[0].score == 4.5


def test_retrieve_with_reranker_uses_its_output_directly_not_resigmoided() -> None:
    """Regression test for a real, confirmed bug: bge-reranker-v2-m3's
    default CrossEncoder output is already a calibrated [0,1] probability
    (confirmed via official sentence-transformers docs), so it must be
    used as-is. Re-applying sigmoid to it was a real bug: on a genuine
    nonsense query, 5 different irrelevant texts each got their own tiny
    real probability, but sigmoid(anything near 0) rounds to ~0.5 -
    collapsing every score to the same misleading "medium confidence"
    value regardless of true relevance."""
    chunks = _real_chunks()
    real_chunk = chunks[0]

    def fake_rerank(query, texts):
        return [0.93 for _ in texts]  # a realistic already-[0,1] relevance probability

    results, confidence = retrieve(
        "a real question",
        vector_search_fn=lambda v, k: [(real_chunk.id, 0.6)],
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
        rerank_fn=fake_rerank,
    )
    assert confidence == 0.93
    assert results[0].score == 0.93


def test_reranker_output_near_zero_stays_near_zero_not_pulled_to_half() -> None:
    """The exact real symptom, reproduced directly: a reranker correctly
    reporting near-zero relevance for irrelevant content must be reflected
    as near-zero confidence - not collapsed toward 0.5 by an extra sigmoid."""
    chunks = _real_chunks()
    real_chunk = chunks[0]

    def fake_rerank(query, texts):
        return [0.0003 for _ in texts]  # what a real reranker gave for a nonsense query

    results, confidence = retrieve(
        "purple elephant quantum banana recipe",
        vector_search_fn=lambda v, k: [(real_chunk.id, 0.1)],
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
        rerank_fn=fake_rerank,
    )
    assert confidence < 0.01, "a genuinely near-zero relevance score must not be pulled toward 0.5"
    assert results[0].score < 0.01


def test_retrieve_reorders_by_reranker_score_not_fusion_order() -> None:
    """The whole point of reranking: it can and should change the order
    RRF fusion produced, using the cross-encoder's actual relevance
    judgment instead of just rank-agreement."""
    chunks = _real_chunks()
    a, b = chunks[0], chunks[1]

    def fake_vector_search(vector, top_k):
        return [(a.id, 0.9), (b.id, 0.5)]  # a ranks first going in

    def fake_rerank(query, texts):
        # texts arrive in fusion order [a, b] - score b higher to flip the order
        return [1.0, 9.0]

    results, _ = retrieve(
        "a real question",
        vector_search_fn=fake_vector_search,
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
        rerank_fn=fake_rerank,
    )
    assert results[0].id == b.id, "reranker should have promoted b above a"


def test_retrieve_labels_method_correctly_when_both_searches_agree() -> None:
    chunks = _real_chunks()
    real_chunk = chunks[0]

    results, _ = retrieve(
        "a real question",
        vector_search_fn=lambda v, k: [(real_chunk.id, 0.7)],
        keyword_search_fn=lambda q, k: [(real_chunk.id, 2.5)],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    assert results[0].method == "fused"


def test_retrieve_skips_stale_ids_missing_from_fetch_results() -> None:
    """Real, expected scenario: search returns an id the chunks table no
    longer has (stale index, deleted doc) - must be skipped, not crash."""
    chunks = _real_chunks()
    real_chunk = chunks[0]

    results, confidence = retrieve(
        "a real question",
        vector_search_fn=lambda v, k: [("stale-id-not-in-table", 0.9), (real_chunk.id, 0.7)],
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},  # never returns the stale id
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    assert len(results) == 1
    assert results[0].id == real_chunk.id


def test_retrieve_respects_top_k_final() -> None:
    chunks = _real_chunks()[:10]

    def fake_vector_search(vector, top_k):
        return [(c.id, 1.0 - i * 0.01) for i, c in enumerate(chunks)]

    results, _ = retrieve(
        "a real question",
        vector_search_fn=fake_vector_search,
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
        top_k_final=3,
    )
    assert len(results) == 3


def test_retrieve_preserves_full_chunk_provenance_fields() -> None:
    """Retrieved must carry every real Chunk field forward (url, domain,
    heading_path, etc.) - stage 06 needs full provenance, not just text
    and a score."""
    chunks = _real_chunks()
    real_chunk = chunks[0]

    results, _ = retrieve(
        "a real question",
        vector_search_fn=lambda v, k: [(real_chunk.id, 0.7)],
        keyword_search_fn=lambda q, k: [],
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    assert str(results[0].url) == str(real_chunk.url)
    assert results[0].domain == real_chunk.domain
    assert results[0].heading_path == real_chunk.heading_path
    assert results[0].text == real_chunk.text


# ---------------------------------------------------------------------------
# keyword_query - the language split between the two search halves
# ---------------------------------------------------------------------------


def test_keyword_query_goes_to_keyword_search_while_query_goes_to_the_embedder() -> None:
    """The two halves have different language requirements, and this is the
    parameter that lets a caller express that.

    Vector search is multilingual (BGE-m3 embeds the senior's own language
    into the same space as the English chunks). Keyword search is not -
    schema.sql builds an 'english' tsvector, so a Mandarin string produces
    an empty tsquery and matches nothing. Query understanding supplies an
    English rewrite for the keyword half while the vector half keeps the original.
    """
    embedded: list[str] = []
    keyword_searched: list[str] = []

    def embed_fn(texts: list[str]) -> list[list[float]]:
        embedded.extend(texts)
        return [[0.1] * 4 for _ in texts]

    def keyword_search_fn(query_text: str, _k: int):
        keyword_searched.append(query_text)
        return []

    chunks = _real_chunks()
    retrieve(
        "\u6211\u7684\u624b\u673a\u4e00\u76f4\u8981\u6c42\u8f93\u5165\u9a8c\u8bc1\u7801",
        vector_search_fn=lambda v, k: [(chunks[0].id, 0.7)],
        keyword_search_fn=keyword_search_fn,
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=embed_fn,
        keyword_query="two-factor authentication verification code",
    )

    assert embedded == ["\u6211\u7684\u624b\u673a\u4e00\u76f4\u8981\u6c42\u8f93\u5165\u9a8c\u8bc1\u7801"]
    assert keyword_searched == ["two-factor authentication verification code"]


def test_omitting_keyword_query_keeps_the_previous_behaviour_exactly() -> None:
    """Every existing caller passes no keyword_query and must be unaffected:
    the same string reaches both halves, as before."""
    keyword_searched: list[str] = []

    def keyword_search_fn(query_text: str, _k: int):
        keyword_searched.append(query_text)
        return []

    chunks = _real_chunks()
    retrieve(
        "how do I spot a scam text",
        vector_search_fn=lambda v, k: [(chunks[0].id, 0.7)],
        keyword_search_fn=keyword_search_fn,
        fetch_chunks_fn=lambda ids: {c.id: c for c in chunks if c.id in ids},
        embed_fn=lambda texts: [[0.1] * 4 for _ in texts],
    )
    assert keyword_searched == ["how do I spot a scam text"]
