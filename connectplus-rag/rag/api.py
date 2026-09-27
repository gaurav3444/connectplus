"""The two calls connectplus-llm makes, with the signatures agreed with it:

    from rag import retrieve, verify

    chunks, confidence = retrieve(query_en, lang, k)
    draft = generate(chunks, lang)          # connectplus-llm
    verdict = verify(draft, chunks)

Stage 05 and stage 07 take every external dependency as a parameter, which
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
from functools import lru_cache
from pathlib import Path
from typing import Any

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
from rag.s07_verify import get_default_entailment
from rag.s07_verify import verify as _verify
from rag.schemas import Chunk, Retrieved, Verdict

log = logging.getLogger("rag")

ENV_PATH = Path(__file__).parent.parent / ".env"


@lru_cache(maxsize=1)
def _search_fns() -> tuple[VectorSearchFunction, KeywordSearchFunction, ChunkFetchFunction]:
    """Postgres-bound search functions, built once per process.

    Reads this repo's own .env, so connectplus-llm has nothing to configure
    for us. A missing DATABASE_URL raises rather than returning no chunks:
    an empty result would reach verify() as low confidence and the senior
    would be told "no trusted information" when the real fault is config.
    """
    from dotenv import load_dotenv

    load_dotenv(ENV_PATH)
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError(
            f"DATABASE_URL is not set (checked the environment and {ENV_PATH}). "
            "Use Supabase's SESSION POOLER connection string - see .env.example."
        )
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


def verify(draft: Any, chunks: Sequence[Retrieved | Mapping[str, Any]]) -> Verdict:
    """Grades a draft answer against the chunks it was generated from.

    `draft` is the answer text, or an Answer envelope carrying `answer_md`.
    `chunks` are exactly what retrieve() returned, in the same order: a
    `[n]` marker means the n-th chunk the generator was shown. Dicts are
    accepted too, for chunks that crossed a JSON boundary.

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
        entail_fn=get_default_entailment(),
    )
    log.info(
        "verify passed=%s reason=%s grounded=%.3f confidence=%.3f chunk_ids=%s",
        verdict.passed, verdict.reason, verdict.grounded_score,
        verdict.confidence, verdict.chunk_ids,
    )
    return verdict
