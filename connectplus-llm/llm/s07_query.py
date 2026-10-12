"""Stage 07 - query understanding.

Turns what a Vietnamese senior typed into something the retriever can use.

Three problems, in order of how often they bite:

1. **The language is not obvious.** Handled in :mod:`llm.vi.detect`. The rule
   this stage enforces is that the app's stated language always wins.
2. **The question is not a query.** "Điện thoại cứ đòi mã" is a description of
   an experience. The retriever needs "two-factor authentication verification
   code". The LLM does this rewrite.
3. **The rewrite can fail.** Quota dies, the model returns Vietnamese, or it
   returns a paragraph. Every one of those has to degrade to something
   retrievable rather than poisoning the search. That is what the deterministic
   termbase expansion is for, and why :attr:`QueryUnderstanding.rewrite_source`
   records which path won.
"""

from __future__ import annotations

import re

from .providers import Provider, ProviderError, get_provider
from .s08_prompt import build_rewrite_prompt
from .schemas import QueryUnderstanding
from .vi.detect import detect
from .vi.normalize import has_vietnamese_diacritics
from .vi.termbase import expand

__all__ = ["understand", "validate_rewrite"]

_MAX_REWRITE_WORDS = 12
_ASCII_RE = re.compile(r"^[\x20-\x7e]+$")


def validate_rewrite(text: str) -> tuple[bool, str]:
    """Decide whether an LLM rewrite is usable as a retrieval query.

    A rewrite that fails any of these is worse than no rewrite: it sends the
    retriever after the wrong thing while looking like it worked.

    Args:
        text: Raw model output.

    Returns:
        ``(ok, reason)``. ``reason`` is empty when ``ok``.
    """
    text = (text or "").strip().strip('"').strip()
    if not text:
        return False, "empty"
    if has_vietnamese_diacritics(text):
        return False, "still Vietnamese"
    # Checked before the ASCII test so the reason reported is the real one -
    # a newline is not "non-ASCII output" and debugging on a wrong reason
    # wastes the person reading the eval notes.
    if "\n" in text:
        return False, "multiple lines"
    if not _ASCII_RE.match(text):
        return False, "non-ASCII output"
    words = text.split()
    if len(words) > _MAX_REWRITE_WORDS:
        return False, f"too long ({len(words)} words)"
    if text.lower().startswith(("i ", "here", "sure", "the english")):
        return False, "model narrated instead of answering"
    return True, ""


def understand(query: str, *, app_lang: str | None = None,
               provider: Provider | None = None) -> QueryUnderstanding:
    """Detect the language and produce an English retrieval query.

    Args:
        query: The question exactly as the user typed it.
        app_lang: Language the client already knows the user selected. When
            given, detection is skipped entirely.
        provider: Injected for testing. Defaults to ``get_provider()``.

    Returns:
        A :class:`~llm.schemas.QueryUnderstanding`. Never raises for provider
        problems - a dead provider degrades to the termbase path.
    """
    detection = detect(query, app_lang=app_lang)
    hints = expand(query)

    # An English question needs no rewrite; sending it through the model only
    # adds latency and a chance to mangle it.
    if detection.lang == "en":
        return QueryUnderstanding(
            original=query,
            rewritten_en=query.strip(),
            lang="en",
            lang_confidence=detection.confidence,
            lang_method=detection.method,
            expansion_terms=hints,
            rewrite_source="passthrough",
        )

    rewritten = ""
    source = ""
    try:
        provider = provider or get_provider()
        prompt = build_rewrite_prompt(query, hints)
        candidate = provider.complete(prompt.text, temperature=0.0, max_tokens=64)
        ok, _reason = validate_rewrite(candidate)
        if ok:
            rewritten = candidate.strip().strip('"').strip()
            source = "llm"
    except ProviderError:
        # Deliberately swallowed. A retrieval query built from the termbase is
        # a worse query, not a broken one, and the user still gets an answer.
        pass

    if not rewritten and hints:
        rewritten = " ".join(hints[:6])
        source = "termbase"

    if not rewritten:
        # Nothing matched and no model. Hand the retriever the raw text; a
        # multilingual embedding model may still do something with it.
        rewritten = query.strip()
        source = "passthrough"

    return QueryUnderstanding(
        original=query,
        rewritten_en=rewritten,
        lang=detection.lang if detection.lang != "und" else (app_lang or "vi"),
        lang_confidence=detection.confidence,
        lang_method=detection.method,
        expansion_terms=hints,
        rewrite_source=source,
    )
