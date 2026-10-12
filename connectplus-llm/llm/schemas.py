"""The answer contract.

Mirrors ``connectplus-rag/schemas.py``. Every field on :class:`Answer` beyond
the answer text itself exists so a bad answer can be traced back to the exact
chunks, prompt version, provider and query rewrite that produced it. A RAG
system without that trail cannot be debugged - "the model said something wrong"
is not an actionable bug report.

Plain dataclasses rather than pydantic: this layer has no HTTP boundary of its
own (stage 10 owns the API), so validation belongs there, not here.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

__all__ = ["Chunk", "Citation", "Verdict", "QueryUnderstanding", "Answer"]


@dataclass(frozen=True)
class Chunk:
    """One retrieved passage of trusted source text."""

    id: str
    url: str
    title: str
    domain: str
    text: str
    score: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    """A numbered reference shown to the user beneath the answer."""

    n: int
    url: str
    title: str
    domain: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Verdict:
    """The verification result returned by ``connectplus-rag``.

    This layer never produces one of these from its own judgement of its own
    output. It receives one and obeys it.
    """

    grounded: bool
    confidence: float
    refused: bool = False
    refusal_reason: str = ""
    unsupported_claims: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class QueryUnderstanding:
    """Output of stage 07.

    Attributes:
        original: The query exactly as typed.
        rewritten_en: English query handed to retrieval.
        lang: Language the answer must be written in.
        lang_confidence: 0..1 from detection, or 1.0 when the app supplied it.
        lang_method: Which rule decided the language.
        expansion_terms: Deterministic English terms from the termbase.
        rewrite_source: ``llm``, ``termbase`` or ``passthrough`` - which path
            produced ``rewritten_en``. Logged so a retrieval miss can be blamed
            on the right component.
    """

    original: str
    rewritten_en: str
    lang: str
    lang_confidence: float
    lang_method: str
    expansion_terms: list[str] = field(default_factory=list)
    rewrite_source: str = "llm"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Answer:
    """The envelope streamed to ``connect-plus-app``."""

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
    lang: str = "vi"
    # Vietnamese layer additions - not in the base contract, carried alongside
    # it so the eval harness and the report can read them per answer.
    readability: dict[str, Any] = field(default_factory=dict)
    term_violations: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["citations"] = [c.as_dict() if isinstance(c, Citation) else c
                          for c in self.citations]
        return d
