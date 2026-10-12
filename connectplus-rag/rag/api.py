"""The two calls connectplus-llm makes, with the signatures agreed with it:

    from rag import retrieve, verify, REFUSAL_THRESHOLD

    chunks, confidence = retrieve(query_en, lang, k)
    if confidence < REFUSAL_THRESHOLD: ...  # refuse before generating
    draft = generate(chunks, lang)          # connectplus-llm
    verdict = verify(draft, chunks, lang=lang)

Stage 05 and stage 06 take every external dependency as a parameter, which
is what lets them be tested without a database or a model download. These
wrappers bind the production ones (Postgres from DATABASE_URL, the bge
reranker, the NLI model) so the caller passes plain values and nothing else.

Every call is logged on the "rag" logger - query, language, chunk ids,
confidence, verdict. A bad answer has to be traceable back to what it was
built from and why it was let through.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Any

from rag.browse import DocRow, find_subcategory, load_topics, resources_for
from rag.s05_retrieve import (
    DEFAULT_TOP_K_FINAL,
    ChunkFetchFunction,
    KeywordSearchFunction,
    VectorSearchFunction,
    get_default_reranker,
    make_postgres_chunk_fetcher,
    make_postgres_keyword_search,
    make_postgres_vector_search,
)
from rag.s05_retrieve import retrieve as _retrieve
from rag.s06_verify import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    MULTILINGUAL_NLI_MODEL_NAME,
    get_default_entailment,
    load_approved_domains,
)
from rag.s06_verify import verify as _verify
from rag.schemas import BrowseCategory, Chunk, Resource, Retrieved, Verdict

log = logging.getLogger("rag")

ENV_PATH = Path(__file__).parent.parent / ".env"

# The same number verify() refuses on, exported so connectplus-llm can skip
# generation early instead of generating an answer verify() will drop.
REFUSAL_THRESHOLD = DEFAULT_CONFIDENCE_THRESHOLD


def _entailment_for(lang: str):
    """English keeps the English model unless RAG_NLI_MODEL_EN overrides it
    (set it in .env to the multilingual model if the English one misbehaves
    with your installed transformers version). Other languages always use
    the multilingual model, which can read them."""
    if lang != "en":
        return get_default_entailment(MULTILINGUAL_NLI_MODEL_NAME)
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    override = os.environ.get("RAG_NLI_MODEL_EN")
    return get_default_entailment(override) if override else get_default_entailment()


def _database_url() -> str:
    """This repo's own .env, so connectplus-llm has nothing to configure for
    us. Missing raises rather than returning nothing: an empty result would
    reach the senior as "no trusted information" when the fault is config."""
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            f"DATABASE_URL is not set (checked the environment and {ENV_PATH}). "
            "Use Supabase's SESSION POOLER connection string - see .env.example."
        )
    return db_url


@lru_cache(maxsize=1)
def _search_fns() -> tuple[VectorSearchFunction, KeywordSearchFunction, ChunkFetchFunction]:
    """Postgres-bound search functions, built once per process."""
    db_url = _database_url()
    return (
        make_postgres_vector_search(db_url),
        make_postgres_keyword_search(db_url),
        make_postgres_chunk_fetcher(db_url),
    )


def retrieve(query_en: str, lang: str, k: int = DEFAULT_TOP_K_FINAL) -> tuple[list[Retrieved], float]:
    """Top-k chunks for an English query, and one 0..1 confidence number.

    `query_en` is already English: connectplus-llm translates and rewrites
    before calling. That matters because the keyword half searches an
    'english' tsvector, where a Mandarin query matches nothing.

    `lang` is the senior's language. It does not change the search - the
    sources are English whatever the question was asked in - and is logged
    so a bad Mandarin answer can be told apart from a bad English one.

    The reranker is always on. Without it `confidence` is a raw cosine
    similarity on a different scale from the one verify()'s threshold was
    set for, and on real data RRF alone ranked a generic chunk above the
    one that answered the question (see NO_RERANK_WARNING in main.py).
    """
    vector_search, keyword_search, fetch_chunks = _search_fns()
    chunks, confidence = _retrieve(
        query_en,
        vector_search_fn=vector_search,
        keyword_search_fn=keyword_search,
        fetch_chunks_fn=fetch_chunks,
        rerank_fn=get_default_reranker(),
        top_k_final=k,
    )
    log.info(
        "retrieve query_en=%r lang=%s k=%d confidence=%.3f chunk_ids=%s",
        query_en, lang, k, confidence, [c.id for c in chunks],
    )
    return chunks, confidence


def _answer_md(draft: Any) -> str:
    """The draft's text, whether connectplus-llm hands over the bare string
    or its Answer envelope (as a dict or an object)."""
    if isinstance(draft, str):
        return draft
    if isinstance(draft, Mapping):
        return str(draft["answer_md"])
    return str(draft.answer_md)


def verify(
    draft: Any, chunks: Sequence[Retrieved | Mapping[str, Any]], lang: str = "en"
) -> Verdict:
    """Grades a draft answer against the chunks it was generated from.

    `draft` is the answer text, or an Answer envelope carrying `answer_md`.
    `chunks` are exactly what retrieve() returned, in the same order: a
    `[n]` marker means the n-th chunk the generator was shown. Dicts are
    accepted too, for chunks that crossed a JSON boundary. `lang` does not
    change the checks (the sources are English); it is logged, as in
    retrieve().

    Confidence is recomputed from the chunks rather than trusted from the
    caller. With the reranker on, retrieve()'s confidence IS the top
    chunk's score, so nothing is lost - and a draft cannot raise its own
    confidence to get past the threshold.

    All four checks run, grounding included: the NLI model loads on the
    first call (a one-time ~500MB download). A failing verdict means drop
    the answer and offer a mentor. Never patch it and retry.
    """
    retrieved = [Retrieved.model_validate(c) for c in chunks]
    confidence = max((c.score for c in retrieved), default=0.0)
    as_chunks: list[Chunk] = list(retrieved)
    verdict = _verify(
        _answer_md(draft),
        as_chunks,
        confidence,
        # English answers keep the English model the threshold was set
        # against; every other language needs one that can read it.
        entail_fn=_entailment_for(lang),
    )
    log.info(
        "verify lang=%s passed=%s reason=%s grounded=%.3f confidence=%.3f chunk_ids=%s",
        lang, verdict.passed, verdict.reason, verdict.grounded_score,
        verdict.confidence, verdict.chunk_ids,
    )
    return verdict


def browse_topics() -> list[BrowseCategory]:
    """Screen 3a's first two levels: categories and their subcategories.
    Static - no database."""
    return list(load_topics())


def browse(category_id: str, subcategory_id: str) -> list[Resource]:
    """Screen 3a's third level: the approved-site sections filed under one
    subcategory, each with its pages in step order. An empty list is the
    designed empty state. Raises KeyError for an unknown id.

    Built from the pages already in the index - no search, no model.
    """
    sub = find_subcategory(category_id, subcategory_id)
    resources = resources_for(sub, _indexed_pages(), load_approved_domains())
    log.info("browse topic=%s/%s resources=%s", category_id, subcategory_id, [r.id for r in resources])
    return resources


# ponytail: one read of every indexed page (~1,600 rows) per process; restart
# after re-indexing. `python -m rag.main browse --build` snapshots the result
# into the browse_resources table, which is what the app reads.
@lru_cache(maxsize=1)
def _indexed_pages() -> tuple[DocRow, ...]:
    import psycopg2

    with closing(psycopg2.connect(_database_url())) as conn, conn.cursor() as cur:
        cur.execute("select distinct doc_id, url, domain, title from chunks")
        return tuple(
            {"doc_id": row[0], "url": row[1], "domain": row[2], "title": row[3]} for row in cur.fetchall()
        )
