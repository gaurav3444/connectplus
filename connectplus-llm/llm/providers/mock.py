"""Deterministic stand-in provider.

This is **not** a language model and does not pretend to be one. It is a
templating function that reads the same prompt a real provider would receive
and returns a well-formed, grounded, correctly-registered Vietnamese answer
built from the fenced source blocks.

It exists for three reasons:

* the test suite must pass on a machine with no API key and no GPU;
* the pipeline, the citation plumbing, the termbase audit and the readability
  metric can all be exercised and regression-tested without spending quota;
* a marker can clone the repo and run ``python -m llm.eval`` immediately.

Its scores in the eval are a **ceiling on the plumbing, not a measure of model
quality** - it cannot fail groundedness because it only ever copies source
text. Any report of model performance must come from ``--provider gemini`` or
``--provider ollama``.
"""

from __future__ import annotations

import re

from .base import Provider

__all__ = ["MockProvider", "SOURCE_BLOCK_RE"]

SOURCE_BLOCK_RE = re.compile(
    r"<<<SOURCE (?P<n>\d+)[^>]*>>>\n(?P<text>.*?)\n<<<END SOURCE (?P=n)>>>",
    re.DOTALL,
)
_QUERY_RE = re.compile(r"USER QUESTION:\s*(?P<q>.+)")
_EXPANSION_RE = re.compile(r"TERMBASE HINTS:\s*(?P<t>.+)")


class MockProvider(Provider):
    """Offline, deterministic, no network."""

    name = "mock"

    def complete(self, prompt: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024) -> str:
        if "TASK: REWRITE" in prompt:
            return self._rewrite(prompt)
        return self._answer(prompt)

    # -- rewrite -----------------------------------------------------------
    def _rewrite(self, prompt: str) -> str:
        """Return the termbase hints as the English query.

        A real provider reasons about the question. The mock leans entirely on
        the deterministic expansion, which is exactly the floor the design
        intends when the model is unavailable.
        """
        hints = _EXPANSION_RE.search(prompt)
        if hints and hints.group("t").strip() not in {"", "(none)"}:
            return hints.group("t").strip()
        q = _QUERY_RE.search(prompt)
        return q.group("q").strip() if q else ""

    # -- answer ------------------------------------------------------------
    def _answer(self, prompt: str) -> str:
        """Build a Vietnamese answer from the fenced sources.

        Every sentence carries a citation marker, address is ``ông/bà``, and
        the steps are numbered - the same shape the real prompt demands, so
        format-level tests are meaningful against the mock.
        """
        blocks = SOURCE_BLOCK_RE.findall(prompt)
        if not blocks:
            return (
                "Thưa ông/bà, chúng tôi không có thông tin đáng tin cậy về "
                "việc này."
            )

        lines = ["Thưa ông/bà, đây là các bước ông/bà có thể làm:", ""]
        for n, text in blocks[:3]:
            first = _first_sentence(text)
            lines.append(f"{n}. {first} [{n}]")
        lines += [
            "",
            "Nếu ông/bà cần giúp thêm, chúng tôi có thể nối ông/bà với một "
            f"người hướng dẫn nói tiếng Việt [{blocks[0][0]}].",
        ]
        return "\n".join(lines)


def _first_sentence(text: str, limit: int = 140) -> str:
    """First sentence of a source block, trimmed to keep sentences short."""
    text = " ".join(text.split())
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return cut[:limit].rstrip(" ,;")
