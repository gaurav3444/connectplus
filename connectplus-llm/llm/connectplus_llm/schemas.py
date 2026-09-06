"""
Data contracts for stage 07 (query understanding). Deliberately minimal:
retrieval only ever needs a string (`rag.retrieve(q_en, lang)`), so this
does not carry intents, entities, or anything else until something
downstream actually needs it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Lang = Literal["zh", "vi", "en"]  # the only three supported languages -- nothing else

LANGUAGE_NAMES: dict[str, str] = {
    "zh": "Chinese",
    "vi": "Vietnamese",
    "en": "English",
}


class QueryRequest(BaseModel):
    """Input to stage 07."""

    raw_query: str = Field(max_length=500)


class QueryPlan(BaseModel):
    """
    Output of stage 07. This is what `rag.retrieve(query_rewritten, lang)`
    consumes -- retrieval is not our job to build (that's connectplus-rag),
    but this is the contract it needs from us.
    """

    query_original: str
    query_rewritten: str = Field(max_length=120)
    lang: Lang | None  # None when the question is in none of the three supported languages

    # Set by us, not the model. True when the LLM was unavailable and this
    # came from the non-LLM fallback path instead.
    degraded: bool = False

    # Set by us. False when the question is not English, Chinese, or
    # Vietnamese -- refused before any LLM call, not best-effort translated.
    supported: bool = True

    @field_validator("query_rewritten")
    @classmethod
    def _must_look_english(cls, v: str) -> str:
        """
        Cheap guard against the model echoing the question back untranslated.
        Not a language detector -- just catches CJK, which is the failure
        we actually see when a translation call quietly fails to translate.
        """
        if any("一" <= ch <= "鿿" for ch in v):
            raise ValueError("query_rewritten contains CJK characters")
        return v.strip()


class LLMTrace(BaseModel):
    """One row per LLM call, written to traces.jsonl."""

    stage: str
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    repaired: bool
    fell_back: bool
    ok: bool
    error: str | None = None
