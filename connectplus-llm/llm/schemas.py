"""Data contracts shared across the pipeline.

Two rules shape this file:

* ``Answer`` is what crosses the network to the app. Everything on it is
  either shown to the senior or needed to trace a bad answer back to the
  exact chunks, prompt and translation that produced it.
* ``PipelineTrace`` is what the eval and the demo need. It never crosses to
  a client.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Literal

__all__ = [
    "Lang", "SUPPORTED_LANGS", "LANGUAGE_NAMES",
    "Chunk", "Citation", "QueryUnderstanding", "Verdict", "Answer",
    "PipelineTrace", "LLMTrace",
]

Lang = Literal["zh", "zh_hant", "vi", "en"]

SUPPORTED_LANGS: tuple[str, ...] = ("zh", "zh_hant", "vi", "en")

LANGUAGE_NAMES: dict[str, str] = {
    "zh": "Chinese (Simplified)",
    "zh_hant": "Chinese (Traditional)",
    "vi": "Vietnamese",
    "en": "English",
}


@dataclass(frozen=True)
class Chunk:
    """One retrieved passage from the knowledge base."""

    id: str
    text: str
    url: str
    title: str
    domain: str
    score: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    """A ``[n]`` marker in the answer, resolved to its source."""

    n: int
    url: str
    title: str
    domain: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryUnderstanding:
    """Output of stage 07.

    ``rewrite_source`` records which path produced ``rewritten_en`` -- the
    model, the deterministic termbase, or raw passthrough. Without it a bad
    retrieval cannot be blamed on the right component.
    """

    original: str
    rewritten_en: str
    lang: str
    lang_confidence: float = 0.0
    lang_method: str = ""
    expansion_terms: list[str] = field(default_factory=list)
    rewrite_source: str = ""
    supported: bool = True

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Verdict:
    """The verification result handed back by ``connectplus-rag``.

    This service does not argue with it. A model must not grade its own
    output, so whatever ``verify`` says, stands.
    """

    grounded: bool
    confidence: float
    refused: bool = False
    refusal_reason: str = ""


@dataclass
class Answer:
    """What the app receives."""

    answer_md: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    refused: bool = False
    refusal_reason: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    prompt_version: str = ""
    provider: str = ""
    query_original: str = ""
    query_rewritten: str = ""
    lang: str = ""
    readability: dict | None = None
    term_violations: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["citations"] = [c.as_dict() if isinstance(c, Citation) else c
                          for c in self.citations]
        return d


@dataclass
class PipelineTrace:
    """Everything the eval and the demo panel need about one call."""

    lang_method: str = ""
    lang_confidence: float = 0.0
    lang_detail: str = ""
    rewrite_source: str = ""
    retrieval_confidence: float = 0.0
    retrieved_ids: list[str] = field(default_factory=list)
    refused_at: str = ""
    verdict_reason: str = ""
    poisoned_chunk_ids: list[str] = field(default_factory=list)
    generation_error: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class LLMTrace:
    """One row per provider call, appended to ``traces.jsonl``."""

    stage: str
    provider: str
    model: str
    prompt_version: str
    latency_ms: int
    ok: bool
    fell_back: bool = False
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)
