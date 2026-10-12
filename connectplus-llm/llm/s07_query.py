"""Stage 07 - query understanding.

Turns what a senior typed into something the retriever can use.

Three problems, in the order they bite:

1. **The language is not obvious.** Selecting a language in CONNECT Plus is
   optional, so detection is real production load. Handled in
   :mod:`llm.lang.detect`; the rule this stage enforces is that the app's
   stated language always wins, and that an undecidable query returns
   ``supported=False`` so the caller can show the language picker rather
   than guess.
2. **The question is not a query.** "我收到一条奇怪的短信" is a description
   of an experience. The retriever needs "suspicious text message scam sms".
   The LLM does this rewrite.
3. **The rewrite can fail.** Quota dies, the model answers in the original
   language, or it returns a paragraph. Every one of those has to degrade to
   something retrievable rather than poisoning the search -- that is what the
   deterministic termbase expansion is for, and why ``rewrite_source``
   records which path won.

On validation: the rewrite is requested as a **JSON object**, not prose. A
typed result removes most of the output-cleaning rules that a plain-text
call needs -- the model cannot "narrate instead of answering" when the
contract is ``{"query_rewritten": "..."}``. What remains is the check that
actually still matters: that the result came back in English.
"""

from __future__ import annotations

import json
import re
import time

from .lang.detect import detect, has_cjk, has_vietnamese_diacritics
from .lanes import get_lane
from .providers import Provider, ProviderError, get_provider
from .s08_prompt import build_rewrite_prompt
from .schemas import LLMTrace, QueryUnderstanding
from .tracing import write_trace

__all__ = ["understand", "validate_rewrite", "parse_rewrite"]

_MAX_REWRITE_WORDS = 15
_ASCII_RE = re.compile(r"^[\x20-\x7e]+$")


def parse_rewrite(raw: str) -> str:
    """Pull ``query_rewritten`` out of a provider response.

    Accepts the structured object first, and falls back to treating the
    whole response as the query -- Ollama's JSON mode is less reliable than
    Gemini's, and a usable string wrapped in the wrong shape is still usable.
    """
    text = (raw or "").strip()
    if not text:
        return ""
    # Strip a markdown fence if a provider added one despite being asked not to.
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return text.strip('"').strip()
    if isinstance(obj, dict):
        return str(obj.get("query_rewritten", "")).strip()
    return text


def validate_rewrite(text: str) -> tuple[bool, str]:
    """Decide whether a rewrite is usable as a retrieval query.

    A rewrite that fails any of these is worse than no rewrite: it sends the
    retriever after the wrong thing while looking like it worked.

    Returns:
        ``(ok, reason)``. ``reason`` is empty when ``ok``.
    """
    text = (text or "").strip().strip('"').strip()
    if not text:
        return False, "empty"
    if has_cjk(text):
        return False, "still Chinese"
    if has_vietnamese_diacritics(text):
        return False, "still Vietnamese"
    # Checked before the ASCII test so the reported reason is the real one --
    # a newline is not "non-ASCII output", and debugging on a wrong reason
    # wastes the time of whoever reads the eval notes.
    if "\n" in text:
        return False, "multiple lines"
    if not _ASCII_RE.match(text):
        return False, "non-ASCII output"
    words = text.split()
    if len(words) > _MAX_REWRITE_WORDS:
        return False, f"too long ({len(words)} words)"
    return True, ""


async def understand(query: str, *, app_lang: str | None = None,
                     provider: Provider | None = None) -> QueryUnderstanding:
    """Detect the language and produce an English retrieval query.

    Args:
        query: The question exactly as the senior typed it.
        app_lang: Language the app already knows was selected. When given,
            detection is skipped entirely -- a stated fact beats a guess.
        provider: Injected for testing and the provider bake-off.

    Returns:
        A :class:`~llm.schemas.QueryUnderstanding`. Never raises for provider
        problems; a dead provider degrades to the termbase path.
        ``supported=False`` means the caller must not proceed to retrieval.
    """
    detection = detect(query, app_lang=app_lang)

    # Out of scope: no language, or a language with no lane. Refusing here
    # costs nothing and avoids best-effort answering in a language this
    # service was never built for.
    if not detection.supported:
        return QueryUnderstanding(
            original=query, rewritten_en="", lang=detection.lang,
            lang_confidence=detection.confidence, lang_method=detection.method,
            rewrite_source="", supported=False,
        )

    lane = get_lane(detection.lang)
    hints = lane.expand(query)

    # English needs no rewrite; a round trip only adds latency and risk.
    if detection.lang == "en":
        return QueryUnderstanding(
            original=query, rewritten_en=query.strip(), lang="en",
            lang_confidence=detection.confidence, lang_method=detection.method,
            expansion_terms=hints, rewrite_source="passthrough",
        )

    rewritten, source = "", ""
    provider = provider or get_provider()
    prompt = build_rewrite_prompt(query, hints, lang=detection.lang)
    started = time.perf_counter()
    try:
        raw = await provider.complete(prompt.text, temperature=0.0,
                                      max_tokens=120, json_object=True)
        candidate = parse_rewrite(raw)
        ok, reason = validate_rewrite(candidate)
        write_trace(LLMTrace(
            stage="07", provider=provider.name, model=provider.model,
            prompt_version=prompt.version,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=ok, fell_back=getattr(provider, "fell_back", False),
            error=None if ok else reason,
        ))
        if ok:
            rewritten, source = candidate.strip().strip('"').strip(), "llm"
    except ProviderError as exc:
        # Deliberately swallowed. A retrieval query built from the termbase
        # is a worse query, not a broken one, and the senior still gets an
        # answer.
        write_trace(LLMTrace(
            stage="07", provider=provider.name, model=provider.model,
            prompt_version=prompt.version,
            latency_ms=int((time.perf_counter() - started) * 1000),
            ok=False, fell_back=getattr(provider, "fell_back", False),
            error=str(exc)[:200],
        ))

    if not rewritten and hints:
        rewritten, source = " ".join(hints[:6]), "termbase"

    if not rewritten:
        # Nothing matched and no model. Hand the retriever the raw text; a
        # multilingual embedding model may still make something of it.
        rewritten, source = query.strip(), "passthrough"

    return QueryUnderstanding(
        original=query, rewritten_en=rewritten, lang=detection.lang,
        lang_confidence=detection.confidence, lang_method=detection.method,
        expansion_terms=hints, rewrite_source=source,
    )
