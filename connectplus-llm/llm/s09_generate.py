"""Stage 09 - generation.

Wraps the provider, turns citation markers into real citations, and owns the
refusal path.

The one rule that shapes this module: **the refusal must never fail.** A
refusal happens precisely when something has already gone wrong - retrieval
came back thin, or verification rejected the draft. Routing it through the same
provider that may itself be the thing that broke would turn a safe outcome into
a blank screen. So :func:`refusal` asks the model for nicer wording, and falls
back to a fixed, hand-written Vietnamese sentence the moment anything is off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

from .providers import Provider, ProviderError, get_provider
from .s08_prompt import build_answer_prompt, build_refusal_prompt
from .schemas import Chunk, Citation, QueryUnderstanding

__all__ = ["Generation", "generate", "stream", "extract_citations",
           "refusal", "FALLBACK_REFUSAL_VI"]

_MARKER_RE = re.compile(r"\[(\d{1,2})\]")

# Hand-written, checked by a human, never generated. Plain register, correct
# address, ends with the mentor offer as the style guide requires.
FALLBACK_REFUSAL_VI = (
    "Thưa ông/bà, chúng tôi không có thông tin đáng tin cậy về việc này, "
    "nên chúng tôi không thể trả lời. "
    "Chúng tôi có thể nối ông/bà với một người hướng dẫn nói tiếng Việt "
    "để giúp ông/bà. Ông/bà có muốn không ạ?"
)

FALLBACK_REFUSAL_EN = (
    "We do not have trusted information about this, so we cannot answer. "
    "We can connect you with a mentor who can help. Would you like that?"
)


@dataclass
class Generation:
    """Raw output of a generation call, before verification.

    Attributes:
        text: The draft answer, in the user's language.
        provider: Which provider actually served it, after any fallback.
        prompt_version: Template version used.
        poisoned_chunk_ids: Chunks whose text had to be sanitised. Worth
            surfacing: it is evidence about the knowledge base, not this layer.
        error: Set when generation failed outright and ``text`` is empty.
    """

    text: str
    provider: str
    prompt_version: str
    poisoned_chunk_ids: list[str] = field(default_factory=list)
    error: str = ""


def generate(chunks: list[Chunk], understanding: QueryUnderstanding, *,
             provider: Provider | None = None,
             temperature: float = 0.2) -> Generation:
    """Produce a draft answer in the user's language.

    Args:
        chunks: Retrieved source passages.
        understanding: Output of stage 07.
        provider: Injected for testing.
        temperature: Kept low. Safety-critical instructions should read the
            same way twice, and the eval needs reproducibility.

    Returns:
        A :class:`Generation`. On provider failure ``text`` is empty and
        ``error`` explains why; the caller takes the refusal path.
    """
    provider = provider or get_provider()
    prompt = build_answer_prompt(
        chunks,
        query_original=understanding.original,
        query_rewritten=understanding.rewritten_en,
    )
    try:
        text = provider.complete(prompt.text, temperature=temperature,
                                 max_tokens=1024)
    except ProviderError as exc:
        return Generation("", provider.name, prompt.version,
                          prompt.sanitised_chunk_ids, str(exc))
    return Generation(text.strip(), provider.name, prompt.version,
                      prompt.sanitised_chunk_ids)


def stream(chunks: list[Chunk], understanding: QueryUnderstanding, *,
           provider: Provider | None = None,
           temperature: float = 0.2) -> Iterator[str]:
    """Yield the draft answer in pieces, for the SSE endpoint in stage 10.

    Note the ordering problem this creates and that stage 10 must solve:
    verification runs on the *finished* draft, so tokens streamed early are
    already on the reader's screen when a refusal verdict arrives. Stage 10
    should buffer until the verdict, or stream into a pending state the client
    can replace. This function does not decide that; it just produces pieces.
    """
    provider = provider or get_provider()
    prompt = build_answer_prompt(
        chunks,
        query_original=understanding.original,
        query_rewritten=understanding.rewritten_en,
    )
    try:
        yield from provider.stream(prompt.text, temperature=temperature,
                                   max_tokens=1024)
    except ProviderError:
        yield FALLBACK_REFUSAL_VI if understanding.lang == "vi" else FALLBACK_REFUSAL_EN


def extract_citations(text: str, chunks: list[Chunk]) -> tuple[list[Citation], list[int]]:
    """Turn ``[n]`` markers in the answer into citations.

    Args:
        text: The generated answer.
        chunks: The chunks that were in the prompt, in prompt order. Marker
            ``[1]`` refers to ``chunks[0]``.

    Returns:
        ``(citations, invalid_markers)``. ``invalid_markers`` holds numbers the
        model cited that do not exist - a hallucinated citation. The eval scores
        this separately from groundedness, because a right fact with a wrong
        source is still a source the reader cannot check.
    """
    seen: dict[int, Citation] = {}
    invalid: list[int] = []
    for raw in _MARKER_RE.findall(text):
        n = int(raw)
        if 1 <= n <= len(chunks):
            if n not in seen:
                c = chunks[n - 1]
                seen[n] = Citation(n=n, url=c.url, title=c.title, domain=c.domain)
        elif n not in invalid:
            invalid.append(n)
    return [seen[k] for k in sorted(seen)], invalid


def refusal(query_original: str, lang: str = "vi", *,
            provider: Provider | None = None) -> str:
    """Produce the message shown when there is no trustworthy answer.

    Tries the model for natural wording, then falls back hard. Any of these
    sends it to the fallback: a provider error, an empty response, a response
    that is suspiciously long, or - for Vietnamese - a response that came back
    without a single Vietnamese diacritic, which means the model answered in
    the wrong language.

    Args:
        query_original: The question, only so the wording can acknowledge it.
        lang: Target language.
        provider: Injected for testing.

    Returns:
        A refusal message. Always non-empty.
    """
    fallback = FALLBACK_REFUSAL_VI if lang == "vi" else FALLBACK_REFUSAL_EN
    try:
        provider = provider or get_provider()
        prompt = build_refusal_prompt(query_original)
        text = (provider.complete(prompt.text, temperature=0.3,
                                  max_tokens=200) or "").strip()
    except ProviderError:
        return fallback

    if not text or len(text.split()) > 80:
        return fallback
    if lang == "vi":
        from .vi.normalize import has_vietnamese_diacritics
        if not has_vietnamese_diacritics(text):
            return fallback
    return text
