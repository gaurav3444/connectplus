"""Stage 05 - Hybrid Retrieval (README_rag.md's own internal numbering;
the unified whole-project stage map calls this "stage 06").

Vector search and keyword search, fused with Reciprocal Rank Fusion (RRF),
optionally reranked with a cross-encoder. Emits top-k chunks with scores
and one confidence number - stage 08 (guardrails) refuses on it.

Design decisions made explicit here:

- Every external dependency is injectable - vector search, keyword search,
  chunk fetching, and reranking are all callables, not hardcoded calls.
  Same reasoning as every previous stage: this sandbox has no live
  Supabase connection and can't download BGE-m3 or bge-reranker-v2-m3, so
  the actual fusion/scoring/orchestration LOGIC is tested here against
  deterministic fakes built from real fixture data, while
  get_default_vector_search()/get_default_keyword_search()/
  get_default_reranker() are the real implementations - genuinely
  untested by me, same situation as stage 04's embedder and upserter.
- Query embedding reuses stage 04's EmbedFunction and
  get_default_embedder() rather than duplicating the "load BGE-m3" lazy-
  singleton logic - retrieval has to search the same embedding space
  indexing wrote into, so it makes sense for this to depend on stage 04's
  embedder directly rather than re-implementing an equivalent.
- Reranking is optional (rerank_fn=None skips it), not mandatory - this
  directly follows README_rag.md's own stage 05 DONE criterion: "Measure
  before and after the reranker; if it doesn't move the number, drop it."
  That measurement can't happen if reranking is hardwired in.
- method on each Retrieved chunk reflects genuine provenance, not a
  blanket label: "vector" or "keyword" if only one search found it,
  "fused" if both did - independent agreement from two different search
  methods is a real, meaningful signal, not just bookkeeping.
- Confidence comes from the reranker's own output directly (bge-reranker-
  v2-m3, via CrossEncoder's default activation, already returns a
  calibrated [0,1] relevance probability - confirmed via the official
  sentence-transformers docs) when reranking is used, or the top result's
  raw vector cosine similarity as a lower-fidelity substitute otherwise.
  A real, confirmed bug used to apply an extra sigmoid to the reranker's
  already-[0,1] output, double-compressing it - every result on a real
  nonsense query collapsed to score=0.500 regardless of how irrelevant
  each one actually was, since sigmoid(anything near zero) rounds to 0.5.
  Real BGE-m3 similarity scores for confirmed-relevant results (the
  vector-only fallback path) landed in the 0.53-0.78 range on this
  project's own real data (see the spot-check conversation), not 0.85+,
  so a fixed threshold tuned for that path would need calibrating against
  that range, not against percentage-match intuition.
- Reranking is the recommended default for real use, not just an equally-
  weighted option - confirmed necessary, not just theoretically better:
  on real data, RRF fusion without reranking ranked a generic scam-
  psychology chunk above the one chunk that specifically and precisely
  answered the query ("how scammers use AI"), because keyword search's
  ts_rank has no way to know "scam" is so common across this corpus that
  matching it carries little signal. Reranking corrected this. rerank_fn
  stays optional at the function level (see above) specifically so this
  before/after comparison can still be made - but callers building real
  features on top of retrieve() should pass a real reranker, not omit one.
- Per-chunk `score` (on each Retrieved) is deliberately NOT the shared RRF
  fusion value when reranking is off - that was a real, confirmed bug: it
  contradicted this module's own documented contract and looked like
  "very low confidence" (RRF scores cap near 0.03) to anyone reading it
  without that context. Each chunk's `score` is now its own real signal
  (vector similarity, or keyword ts_rank if only keyword found it) - see
  _own_raw_score()'s docstring for why these two scales can't be compared
  to each other, and why `confidence`, not `score`, is what any threshold
  decision should use.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import closing
from functools import lru_cache

from rag.s04_embed import DEFAULT_MODEL_NAME as EMBED_MODEL_NAME
from rag.s04_embed import EmbedFunction, get_default_embedder
from rag.schemas import Chunk, Retrieved

RERANKER_MODEL_NAME = "BAAI/bge-reranker-v2-m3"

DEFAULT_TOP_K_PER_METHOD = 20  # how many candidates each of vector/keyword search contributes
DEFAULT_TOP_K_FINAL = 5        # how many Retrieved chunks the caller actually gets back
RRF_K = 60                     # standard constant from the original RRF paper (Cormack et al.)

# (chunk_id, score) pairs, ranked best-first - the shape both search methods return
RankedIds = list[tuple[str, float]]

VectorSearchFunction = Callable[[list[float], int], RankedIds]
KeywordSearchFunction = Callable[[str, int], RankedIds]
ChunkFetchFunction = Callable[[list[str]], dict[str, Chunk]]
# (query, texts) -> relevance scores. For bge-reranker-v2-m3 specifically
# (this module's default), these already arrive as calibrated [0,1]
# probabilities - see the comment where rerank_fn is called in retrieve()
# for why that matters and isn't just a convention to trust blindly.
RerankFunction = Callable[[str, list[str]], list[float]]


@lru_cache(maxsize=1)
def get_default_reranker() -> RerankFunction:
    """Real bge-reranker-v2-m3, loaded once per process. Not used by any
    test in this repo - this sandbox can't download it to verify it
    actually works, so tests inject a stand-in reranker instead (see
    tests/test_s05_retrieve.py). This function is what production code
    (the CLI, once built) actually calls.
    """
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(RERANKER_MODEL_NAME)

    def rerank(query: str, texts: list[str]) -> list[float]:
        pairs = [(query, text) for text in texts]
        return model.predict(pairs).tolist()

    return rerank


def reciprocal_rank_fusion(rankings: list[RankedIds], k: int = RRF_K) -> dict[str, float]:
    """Standard RRF: for each ranked list a chunk appears in, it earns
    1/(k + rank) - rank is 1-based (the top result contributes the most).
    Scores from multiple lists sum, so a chunk found near the top of both
    vector AND keyword search outranks one found near the top of only
    one. Pure function, no external dependency - this is the one part of
    the whole stage fully verifiable without any fake standing in for
    something real.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, (chunk_id, _original_score) in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return scores


def _method_for(chunk_id: str, vector_ids: set[str], keyword_ids: set[str]) -> str:
    in_vector = chunk_id in vector_ids
    in_keyword = chunk_id in keyword_ids
    if in_vector and in_keyword:
        return "fused"
    return "vector" if in_vector else "keyword"


def _own_raw_score(chunk_id: str, vector_scores: dict[str, float], keyword_scores: dict[str, float]) -> float:
    """The chunk's own real signal from whichever search(es) found it -
    never the shared RRF fusion value. Confirmed real bug this replaces:
    every result's `score` was set to the same internal RRF bookkeeping
    number (tiny values like 0.01-0.03), which contradicted this
    function's own documented contract and looked like "very low
    confidence" to anyone reading it without that context.

    Prefers vector similarity when a chunk was found by both methods
    (method="fused") - vector similarity is bounded and interpretable
    (roughly -1..1); keyword's ts_rank is an unbounded float shaped by
    term frequency and document length, with no fixed scale. This means
    `score` is only safely comparable *within* the same `method` - a
    vector score of 0.7 and a keyword score of 0.05 are not on the same
    scale and were never meant to be compared to each other. `confidence`
    (this function's caller's other return value), not any individual
    `score`, is the number designed for cross-query, threshold-style
    decisions.
    """
    if chunk_id in vector_scores:
        return vector_scores[chunk_id]
    return keyword_scores.get(chunk_id, 0.0)


def retrieve(
    query: str,
    vector_search_fn: VectorSearchFunction,
    keyword_search_fn: KeywordSearchFunction,
    fetch_chunks_fn: ChunkFetchFunction,
    embed_fn: EmbedFunction | None = None,
    rerank_fn: RerankFunction | None = None,
    keyword_query: str | None = None,
    top_k_per_method: int = DEFAULT_TOP_K_PER_METHOD,
    top_k_final: int = DEFAULT_TOP_K_FINAL,
    rrf_k: int = RRF_K,
) -> tuple[list[Retrieved], float]:
    """Runs the full hybrid retrieval pipeline for one query. Returns
    (top_k_final Retrieved chunks, one overall confidence number).

    embed_fn defaults to get_default_embedder() (real BGE-m3) - the same
    model stage 04 indexed with, since a query has to land in the same
    embedding space as the chunks it's being compared against.
    rerank_fn defaults to None (no reranking) rather than
    get_default_reranker() - reranking is a measured, optional
    improvement per README's own DONE criterion, not a hardwired step.

    keyword_query, when given, is what the KEYWORD half searches for while
    the vector half still embeds `query`. This exists because the two
    halves have genuinely different language requirements, not as a
    convenience:

    - Vector search is multilingual. BGE-m3 embeds a Mandarin query into
      the same space as the English chunks it should match, so `query` in
      the senior's own language is exactly right here.
    - Keyword search is not. rag/config/schema.sql builds the tsvector
      with Postgres's 'english' configuration, and plainto_tsquery below
      parses with it too. A Mandarin query produces an EMPTY tsquery,
      matches nothing, and hybrid retrieval silently collapses to
      vector-only - half the system doing nothing, with no error to say so.

    Stage 06 (query understanding, rag/s06_query.py) produces an English
    `rewritten` query precisely so it can be passed here. Callers that
    omit keyword_query get the previous behaviour unchanged (query is used
    for both).

    Known and accepted: the index does contain non-English chunks
    (confirmed real - Vietnamese, Chinese, Hindi and Greek translated
    pages on both approved domains). Those are reachable through vector
    search only, since an 'english' tsvector cannot index them and
    Postgres cannot tokenise CJK text at all. Switching the column to
    'simple' would not fix that - an unspaced Chinese sentence becomes one
    single unmatched token either way.
    """
    embed_fn = embed_fn or get_default_embedder(EMBED_MODEL_NAME)

    if not query.strip():
        return [], 0.0

    query_vector = embed_fn([query])[0]
    vector_results = vector_search_fn(query_vector, top_k_per_method)
    keyword_results = keyword_search_fn(keyword_query or query, top_k_per_method)

    vector_ids = {cid for cid, _ in vector_results}
    keyword_ids = {cid for cid, _ in keyword_results}

    fused_scores = reciprocal_rank_fusion([vector_results, keyword_results], k=rrf_k)
    if not fused_scores:
        return [], 0.0

    fused_ranking = sorted(fused_scores.items(), key=lambda pair: pair[1], reverse=True)
    candidate_ids = [cid for cid, _ in fused_ranking[: max(top_k_per_method, top_k_final)]]
    chunks_by_id = fetch_chunks_fn(candidate_ids)
    # A candidate id search returned but that no longer exists in the
    # chunks table (stale index, deleted doc) is skipped, not an error -
    # search and the source of truth can drift apart in a real system.
    candidate_ids = [cid for cid in candidate_ids if cid in chunks_by_id]

    if rerank_fn is not None and candidate_ids:
        # bge-reranker-v2-m3 (via sentence-transformers CrossEncoder,
        # loaded with its default activation) already returns a
        # calibrated relevance probability in [0,1] - confirmed via the
        # official sentence-transformers docs, which explicitly list this
        # model among those that "return a score 0…1", distinct from
        # models like ms-marco that return raw logits needing an
        # explicit sigmoid. A real, confirmed bug lived here: applying
        # an extra sigmoid to this already-[0,1] value double-compressed it -
        # on a real nonsense query, 5 genuinely different, irrelevant
        # texts each got a tiny-but-different real probability (e.g.
        # 0.0001, 0.0003), and sigmoid(anything near 0) rounds to ~0.500
        # regardless of the real differences between them. That's exactly
        # the "all five results show score=0.500" symptom that surfaced
        # this. relevance_scores here are used directly, not re-sigmoided.
        relevance_scores = rerank_fn(query, [chunks_by_id[cid].text for cid in candidate_ids])
        scored = sorted(zip(candidate_ids, relevance_scores), key=lambda pair: pair[1], reverse=True)
        top_ids_scores = scored[:top_k_final]
        confidence = top_ids_scores[0][1] if top_ids_scores else 0.0
        final = [
            Retrieved(
                **chunks_by_id[cid].model_dump(),
                score=relevance_score,
                method=_method_for(cid, vector_ids, keyword_ids),
            )
            for cid, relevance_score in top_ids_scores
        ]
    else:
        top_ids = candidate_ids[:top_k_final]
        vector_scores = dict(vector_results)
        keyword_scores = dict(keyword_results)
        top_vector_similarity = vector_scores.get(top_ids[0], 0.0) if top_ids else 0.0
        confidence = max(0.0, min(1.0, top_vector_similarity))
        final = [
            Retrieved(
                **chunks_by_id[cid].model_dump(),
                score=_own_raw_score(cid, vector_scores, keyword_scores),
                method=_method_for(cid, vector_ids, keyword_ids),
            )
            for cid in top_ids
        ]

    return final, confidence


def make_postgres_vector_search(connection_string: str) -> VectorSearchFunction:
    """Real pgvector cosine-similarity search. Not used by any test in
    this repo - this sandbox has no live database to verify it against.
    Untested by me; you are the first to run this against a real database,
    same situation as stage 04's make_postgres_upserter.
    """
    # ponytail: one connection per call, opened and closed properly.
    # psycopg2's `with conn` only ends the TRANSACTION, not the connection -
    # without closing() every call leaked a connection, which a Supabase
    # free-tier pooler runs out of fast. Move to a shared pool if per-query
    # connection setup ever becomes the latency bottleneck.
    import psycopg2

    def search(query_vector: list[float], top_k: int) -> RankedIds:
        # Explicit pgvector literal ("[0.1,0.2,...]"), not relying on
        # psycopg2's default list-to-array adaptation - same reasoning as
        # scripts/spot_check_index.py.
        vector_literal = "[" + ",".join(str(x) for x in query_vector) + "]"
        with closing(psycopg2.connect(connection_string)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                select id, 1 - (embedding <=> %s::vector) as similarity
                from chunks
                order by embedding <=> %s::vector
                limit %s
                """,
                (vector_literal, vector_literal, top_k),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    return search


def make_postgres_keyword_search(connection_string: str) -> KeywordSearchFunction:
    """Real Postgres full-text search against the tsvector column built
    in rag/config/schema.sql. Untested by me, same caveat as above.
    """
    import psycopg2

    def search(query_text: str, top_k: int) -> RankedIds:
        with closing(psycopg2.connect(connection_string)) as conn, conn.cursor() as cur:
            cur.execute(
                """
                select id, ts_rank(tsv, plainto_tsquery('english', %s)) as rank
                from chunks
                where tsv @@ plainto_tsquery('english', %s)
                order by rank desc
                limit %s
                """,
                (query_text, query_text, top_k),
            )
            return [(row[0], row[1]) for row in cur.fetchall()]

    return search


def make_postgres_chunk_fetcher(connection_string: str) -> ChunkFetchFunction:
    """Fetches full Chunk records for a list of ids - the two search
    functions above only return (id, score) pairs, since a scoring query
    doesn't need to pull every column. Untested by me, same caveat as above.
    """
    import psycopg2

    columns = [
        "id", "doc_id", "url", "domain", "title", "lang", "fetched_at",
        "heading_path", "text", "token_count", "order_idx",
    ]

    def fetch(chunk_ids: list[str]) -> dict[str, Chunk]:
        if not chunk_ids:
            return {}
        with closing(psycopg2.connect(connection_string)) as conn, conn.cursor() as cur:
            cur.execute(
                f"select {', '.join(columns)} from chunks where id = any(%s)",
                (chunk_ids,),
            )
            rows = cur.fetchall()
        return {
            row[0]: Chunk(**dict(zip(columns, row)))
            for row in rows
        }

    return fetch
