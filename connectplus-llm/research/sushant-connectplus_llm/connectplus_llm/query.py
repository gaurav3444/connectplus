"""
Stage 07 -- query understanding.

Identify language (Chinese, English, or Vietnamese -- nothing else),
translate + rewrite the senior's question into an English, retrieval-ready
search query. Rewriter, not answerer: this module never generates advice,
only the search query that goes into `rag.retrieve(query_rewritten, lang)`
-- which is not built here.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import prompts
from .config import settings
from .lang_id import identify_language
from .llm_client import LLM, LLMError
from .schemas import Lang, QueryPlan, QueryRequest

_STOPWORDS = {
    "a", "an", "the", "is", "it", "my", "me", "i", "to", "do", "how",
    "what", "why", "on", "in", "of", "and", "or", "for", "with",
    "keeps", "get", "got", "can", "cant", "does", "this", "that",
    "you", "your", "am", "was",
}


class _RewriteResult(BaseModel):
    """
    What the LLM actually produces. QueryPlan carries more (lang, the
    original query, the degraded/supported flags) that WE set, not the
    model -- so the model's output is validated against this narrower
    schema, not QueryPlan directly.
    """

    query_rewritten: str = Field(max_length=120)


def unsupported_plan(req: QueryRequest) -> QueryPlan:
    """No LLM call at all -- refusing out-of-scope input costs nothing and
    doesn't risk a best-effort translation of a language we were never
    asked to support."""
    return QueryPlan(
        query_original=req.raw_query,
        query_rewritten="",
        lang=None,
        degraded=False,
        supported=False,
    )


async def understand(req: QueryRequest, llm: LLM | None = None) -> QueryPlan:
    """Returns a QueryPlan always. Never raises to the caller -- retrieval
    must still be able to run even when the model is unavailable."""
    lang = identify_language(req.raw_query)
    if lang is None:
        return unsupported_plan(req)

    llm = llm or LLM()

    try:
        result = await llm.complete(
            system=prompts.query_system(),
            user=prompts.query_user(req, lang),
            schema=_RewriteResult,
            temperature=settings.query_temperature,
            max_tokens=settings.query_max_tokens,
            timeout_s=settings.query_timeout_s,
            stage="07",
            prompt_version=settings.query_prompt_version,
        )
        return QueryPlan(
            query_original=req.raw_query,
            query_rewritten=result.query_rewritten,
            lang=lang,
            degraded=False,
        )
    except LLMError:
        return degraded_plan(req, lang)


def degraded_plan(req: QueryRequest, lang: Lang) -> QueryPlan:
    """
    Non-LLM fallback. Retrieval still runs, on the best query we can build
    without a model.

    English gets naive keyword extraction. Chinese and Vietnamese get a
    generic fallback query rather than mangled, diacritic-stripped text --
    there is nothing honest to translate with, so sending a generic query
    lets retrieval return an orienting topic list rather than failing the
    request outright.
    """
    if lang == "en":
        tokens = [
            t for t in re.findall(r"[a-z']+", req.raw_query.lower())
            if t not in _STOPWORDS and len(t) > 2
        ]
        query = " ".join(tokens)[:120] or "digital literacy help getting started"
    else:
        query = "digital literacy help getting started"

    return QueryPlan(
        query_original=req.raw_query,
        query_rewritten=query,
        lang=lang,
        degraded=True,
    )
