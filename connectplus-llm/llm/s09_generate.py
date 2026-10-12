"""Stage 09 - generation.

Wraps the provider, turns citation markers into real citations, and owns the
refusal path.

The one rule that shapes this module: **the refusal must never fail.** A
refusal happens precisely when something has already gone wrong -- retrieval
came back thin, generation died, or verification rejected the draft. Routing
it through the same provider that may itself be the broken thing would turn
a safe outcome into a blank screen. So :func:`refusal` asks the model for
better wording and falls back to the lane's hand-written sentence the moment
anything is off, including when the answer comes back in the wrong language.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from .lang.detect import has_cjk, has_vietnamese_diacritics
from .lanes import get_lane
from .providers import Provider, ProviderError, get_provider
from .s08_prompt import build_answer_prompt, build_refusal_prompt
from .schemas import Chunk, Citation, LLMTrace, QueryUnderstanding
from .tracing import write_trace

__all__ = ["Generation", "generate", "stream", "extract_citations", "refusal"]

_MARKER_RE = re.compile(r"\[(\d{1,2})\]")


@dataclass
class Generation:
    """Raw output of a generation call, before verification.

    Attributes:
        text: The draft answer, in the senior's language.
        provider: Which provider actually served it, after any fallback.
        prompt_version: Template version used.
        poisoned_chunk_ids: Chunks whose text had to be sanitised. Worth
            surfacing: it is evidence about the knowledge base, not about
            this layer.
        error: Set when generation failed and ``text`` is empty.
    """

    text: str
    provider: str
    model: str
    prompt_version: str
    poisoned_chunk_ids: list[str] = field(default_factory=list)
    error: str = ""
    latency_ms: int = 0


def _looks_like(lang: str, text: str) -> bool:
    """Cheap check that a generated answer is in the language we asked for.

    Not a detector -- just the failure we actually see, which is a model
    answering in English because its training data for that instruction was
    English.
    """
    if lang in ("zh", "zh_hant"):
        return has_cjk(text)
    if lang == "vi":
        return has_vietnamese_diacritics(text)
    return True


async def generate(chunks: list[Chunk], understanding: QueryUnderstanding, *,
                   provider: Provider | None = None,
                   temperature: float = 0.2) -> Generation:
    """Produce a draft answer in the senior's language.

    Returns:
        A :class:`Generation`. On provider failure ``text`` is empty and
        ``error`` explains why; the caller takes the refusal path.
    """
    provider = provider or get_provider()
    prompt = build_answer_prompt(
        chunks, lang=understanding.lang,
        query_original=understanding.original,
        query_rewritten=understanding.rewritten_en,
    )
    started = time.perf_counter()
    try:
        text = await provider.complete(prompt.text, temperature=temperature,
                                       max_tokens=1024)
    except ProviderError as exc:
        elapsed = int((time.perf_counter() - started) * 1000)
        write_trace(LLMTrace(stage="09", provider=provider.name,
                             model=provider.model, prompt_version=prompt.version,
                             latency_ms=elapsed, ok=False,
                             fell_back=getattr(provider, "fell_back", False),
                             error=str(exc)[:200]))
        return Generation("", provider.name, provider.model, prompt.version,
                          prompt.sanitised_chunk_ids, str(exc), elapsed)

    elapsed = int((time.perf_counter() - started) * 1000)
    text = (text or "").strip()

    # A model that answered in the wrong language is not a usable answer.
    # Discard it and let the caller refuse, rather than showing a senior an
    # English wall of text they came here to avoid.
    if text and not _looks_like(understanding.lang, text):
        write_trace(LLMTrace(stage="09", provider=provider.name,
                             model=provider.model, prompt_version=prompt.version,
                             latency_ms=elapsed, ok=False,
                             fell_back=getattr(provider, "fell_back", False),
                             error="wrong output language"))
        return Generation("", provider.name, provider.model, prompt.version,
                          prompt.sanitised_chunk_ids,
                          f"model did not answer in {understanding.lang}", elapsed)

    write_trace(LLMTrace(stage="09", provider=provider.name, model=provider.model,
                         prompt_version=prompt.version, latency_ms=elapsed,
                         ok=bool(text),
                         fell_back=getattr(provider, "fell_back", False),
                         error=None if text else "empty generation"))
    return Generation(text, provider.name, provider.model, prompt.version,
                      prompt.sanitised_chunk_ids, "", elapsed)


async def stream(chunks: list[Chunk], understanding: QueryUnderstanding, *,
                 provider: Provider | None = None,
                 temperature: float = 0.2) -> AsyncIterator[str]:
    """Yield the draft answer in pieces, for the SSE endpoint.

    Note the ordering problem this creates, which stage 10 must solve:
    verification runs on the *finished* draft, so tokens streamed early are
    already on the reader's screen when a refusal verdict arrives. Stage 10
    should buffer until the verdict, or stream into a pending state the
    client can replace. This function does not decide that; it produces
    pieces.
    """
    provider = provider or get_provider()
    prompt = build_answer_prompt(
        chunks, lang=understanding.lang,
        query_original=understanding.original,
        query_rewritten=understanding.rewritten_en,
    )
    try:
        async for piece in provider.stream(prompt.text, temperature=temperature,
                                           max_tokens=1024):
            yield piece
    except ProviderError:
        yield get_lane(understanding.lang).fallback_refusal


def extract_citations(text: str,
                      chunks: list[Chunk]) -> tuple[list[Citation], list[int]]:
    """Turn ``[n]`` markers in the answer into citations.

    Args:
        text: The generated answer.
        chunks: The chunks that were in the prompt, in prompt order. Marker
            ``[1]`` refers to ``chunks[0]``.

    Returns:
        ``(citations, invalid_markers)``. ``invalid_markers`` holds numbers
        the model cited that do not exist -- a hallucinated citation. Scored
        separately from groundedness, because a right fact with a wrong
        source is still a source the reader cannot check.
    """
    seen: dict[int, Citation] = {}
    invalid: list[int] = []
    for raw in _MARKER_RE.findall(text or ""):
        n = int(raw)
        if 1 <= n <= len(chunks):
            if n not in seen:
                c = chunks[n - 1]
                seen[n] = Citation(n=n, url=c.url, title=c.title, domain=c.domain)
        elif n not in invalid:
            invalid.append(n)
    return [seen[k] for k in sorted(seen)], invalid


async def refusal(query_original: str, lang: str = "en", *,
                  provider: Provider | None = None) -> str:
    """Produce the message shown when there is no trustworthy answer.

    Tries the model for natural wording, then falls back hard. Any of these
    sends it to the lane's hand-written text: a provider error, an empty
    response, a suspiciously long response, or a response that came back in
    the wrong language.

    Returns:
        A refusal message. Always non-empty.
    """
    lane = get_lane(lang)
    fallback = lane.fallback_refusal
    try:
        provider = provider or get_provider()
        prompt = build_refusal_prompt(query_original, lang=lang)
        text = (await provider.complete(prompt.text, temperature=0.3,
                                        max_tokens=200) or "").strip()
    except ProviderError:
        return fallback

    if not text or len(text) > 400:
        return fallback
    if not _looks_like(lang, text):
        return fallback
    return text
