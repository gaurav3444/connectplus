"""Language lane registry.

This module is the fix for the single biggest structural problem in the two
repos being merged: the original ``build_answer_prompt()`` took no ``lang``
argument and always loaded ``vi_answer.v1.jinja``, and ``refusal()`` fell
back to English for any language that was not Vietnamese. A Chinese senior's
question therefore produced a prompt instructing the model to write in
Vietnamese, and a refusal in English.

A **lane** is everything that is language-specific: the prompt templates,
the hand-written refusal, the terminology and register lock, the readability
proxy. Adding a language means adding a lane and a set of templates, and
changing nothing above this file.

Every lane must supply a hand-written refusal. It is never generated,
because a refusal fires exactly when the model may be the broken thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

__all__ = ["Lane", "get_lane", "available_lanes", "REFUSALS"]


class _TermbaseModule(Protocol):
    def glossary_block(self) -> str: ...
    def register_block(self) -> str: ...
    def protected_nouns(self) -> list[str]: ...
    def expand(self, query: str, limit: int = ...) -> list[str]: ...
    def audit(self, answer: str, *, source_text: str = ...) -> list: ...


# Hand-written, human-checked, never generated. Plain register, correct form
# of address, and every one ends with the mentor offer the style guide
# requires -- because the moment this text is shown is the moment the senior
# most needs a person rather than a system.
REFUSALS: dict[str, str] = {
    "zh": (
        "很抱歉，我们没有可靠的资料来回答这个问题，"
        "所以我们不能给您答案。"
        "我们可以帮您联系一位会说中文的辅导员来帮助您。"
        "您需要吗？"
    ),
    "zh_hant": (
        "很抱歉，我們沒有可靠的資料來回答這個問題，"
        "所以我們不能給您答案。"
        "我們可以幫您聯絡一位會說中文的輔導員來幫助您。"
        "您需要嗎？"
    ),
    "vi": (
        "Thưa ông/bà, chúng tôi không có thông tin đáng tin cậy về việc này, "
        "nên chúng tôi không thể trả lời. "
        "Chúng tôi có thể nối ông/bà với một người hướng dẫn nói tiếng Việt "
        "để giúp ông/bà. Ông/bà có muốn không ạ?"
    ),
    "en": (
        "We do not have trusted information about this, so we cannot answer. "
        "We can connect you with a mentor who can help. Would you like that?"
    ),
}


@dataclass(frozen=True)
class Lane:
    """Everything language-specific for one supported language.

    Attributes:
        code: ISO 639-1 code.
        name: English name, used in prompts.
        answer_template: Filename in ``llm/prompts/``.
        rewrite_template: Filename, or empty when the language needs no
            rewrite (English queries go straight to retrieval).
        refusal_template: Filename for the model-worded refusal. The
            hand-written fallback in :data:`REFUSALS` is what actually ships
            when anything is off.
        expand: Deterministic query expansion, used when the model is
            unavailable or its rewrite fails validation.
        audit: Post-generation terminology and register check.
        readability: Post-generation readability proxy.
    """

    code: str
    name: str
    answer_template: str
    rewrite_template: str
    refusal_template: str
    expand: Callable[..., list[str]]
    audit: Callable[..., list]
    readability: Callable[[str], object]

    @property
    def fallback_refusal(self) -> str:
        return REFUSALS[self.code]


def _noop_expand(query: str, limit: int = 8) -> list[str]:
    return []


def _noop_audit(answer: str, *, source_text: str = "") -> list:
    return []


def _build_registry() -> dict[str, Lane]:
    from .zh import termbase as zh_termbase, readability as zh_readability
    from .zh_hant import termbase as zh_hant_termbase, readability as zh_hant_readability
    from .vi import termbase as vi_termbase, readability as vi_readability

    return {
        "zh": Lane(
            code="zh", name="Chinese (Simplified)",
            answer_template="zh_answer.v1.jinja",
            rewrite_template="zh_query_rewrite.v1.jinja",
            refusal_template="zh_refusal.v1.jinja",
            expand=zh_termbase.expand,
            audit=zh_termbase.audit,
            readability=zh_readability.score,
        ),
        "zh_hant": Lane(
            code="zh_hant", name="Chinese (Traditional)",
            answer_template="zh_hant_answer.v1.jinja",
            rewrite_template="zh_hant_query_rewrite.v1.jinja",
            refusal_template="zh_hant_refusal.v1.jinja",
            expand=zh_hant_termbase.expand,
            audit=zh_hant_termbase.audit,
            readability=zh_hant_readability.score,
        ),
        "vi": Lane(
            code="vi", name="Vietnamese",
            answer_template="vi_answer.v1.jinja",
            rewrite_template="vi_query_rewrite.v1.jinja",
            refusal_template="vi_refusal.v1.jinja",
            expand=vi_termbase.expand,
            audit=vi_termbase.audit,
            readability=vi_readability.score,
        ),
        "en": Lane(
            code="en", name="English",
            answer_template="en_answer.v1.jinja",
            # An English question needs no rewrite. Sending it through the
            # model only adds latency and a chance to mangle it.
            rewrite_template="",
            refusal_template="en_refusal.v1.jinja",
            expand=_noop_expand,
            audit=_noop_audit,
            readability=lambda text: None,
        ),
    }


_REGISTRY: dict[str, Lane] | None = None


def get_lane(lang: str) -> Lane:
    """Return the lane for ``lang``.

    Raises:
        KeyError: If the language has no lane. Callers must refuse before
            this point rather than best-effort answering in a language the
            service was never built for.
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY[lang]


def available_lanes() -> list[str]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return list(_REGISTRY)
