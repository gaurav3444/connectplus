"""Deterministic stand-in provider.

This is **not** a language model and does not pretend to be one. It reads the
same prompt a real provider would receive and returns a well-formed,
grounded, correctly-registered answer assembled from the fenced source
blocks.

It exists for three reasons:

* the test suite must pass with no API key, no network and no GPU;
* the pipeline, citation plumbing, termbase audit and readability metric can
  all be exercised and regression-tested without spending quota;
* anyone can clone the repo and run the demo immediately.

**Read its eval scores correctly.** They are a ceiling on the plumbing, not a
measure of model quality -- it cannot fail groundedness because it only ever
copies source text. It also copies that text *in English*, which is why every
answered question grades ``hard`` on readability: the language-integrity cap
is correctly catching untranslated English. That is the metric working, not
breaking. Any claim about model performance must come from ``--provider
gemini`` or ``--provider ollama``.
"""

from __future__ import annotations

import json
import re

from .base import Provider

__all__ = ["MockProvider", "SOURCE_BLOCK_RE"]

SOURCE_BLOCK_RE = re.compile(
    r"<<<SOURCE (?P<n>\d+)[^>]*>>>\n(?P<text>.*?)\n<<<END SOURCE (?P=n)>>>",
    re.DOTALL,
)
_LANG_RE = re.compile(r"^LANG:\s*(\w+)", re.MULTILINE)
_HINTS_RE = re.compile(r"TERMBASE HINTS:\s*(?P<t>.+)")
_QUESTION_RE = re.compile(r"(?:QUESTION|读者的问题|USER QUESTION)[:：]\s*(?P<q>.+)")

# Scaffolding in each language, with the correct form of address. Format-level
# tests against the mock are therefore meaningful: 您 and ông/bà are really
# present, so the register audit is exercised rather than trivially passed.
_SCAFFOLD = {
    "zh": {
        "opening": "您好。以下是您可以做的步骤：",
        "mentor": "如果您还需要帮助，我们可以帮您联系一位会说中文的辅导员",
        "empty": "很抱歉，我们没有可靠的资料来回答这个问题。",
    },
    "zh_hant": {
        "opening": "您好。以下是您可以做的步驟：",
        "mentor": "如果您還需要幫助，我們可以幫您聯絡一位會說中文的輔導員",
        "empty": "很抱歉，我們沒有可靠的資料來回答這個問題。",
    },
    "vi": {
        "opening": "Thưa ông/bà, đây là các bước ông/bà có thể làm:",
        "mentor": "Nếu ông/bà cần giúp thêm, chúng tôi có thể nối ông/bà với một người hướng dẫn nói tiếng Việt",
        "empty": "Thưa ông/bà, chúng tôi không có thông tin đáng tin cậy về việc này.",
    },
    "en": {
        "opening": "Here are the steps you can take:",
        "mentor": "If you need more help, we can connect you with a mentor",
        "empty": "We do not have trusted information about this.",
    },
}


class MockProvider(Provider):
    """Offline, deterministic, no network."""

    name = "mock"
    model = "deterministic-stub"

    async def complete(self, prompt: str, *, temperature: float = 0.2,
                       max_tokens: int = 1024,
                       json_object: bool = False) -> str:
        if "TASK: REWRITE" in prompt:
            return self._rewrite(prompt, json_object)
        if "TASK: REFUSE" in prompt:
            return self._refuse(prompt)
        return self._answer(prompt)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _lang(prompt: str) -> str:
        m = _LANG_RE.search(prompt)
        return m.group(1) if m else "en"

    # -- rewrite -----------------------------------------------------------
    def _rewrite(self, prompt: str, json_object: bool) -> str:
        """Return the termbase hints as the English query.

        A real provider reasons about the question. The mock leans entirely
        on the deterministic expansion, which is exactly the floor the design
        intends when no model is available -- so a mock run measures the
        termbase, and a Gemini run measures the model.
        """
        hints = _HINTS_RE.search(prompt)
        if hints and hints.group("t").strip() not in {"", "(none)"}:
            query = " ".join(hints.group("t").replace(",", " ").split())[:110]
        else:
            q = _QUESTION_RE.search(prompt)
            query = q.group("q").strip() if q else ""
        return json.dumps({"query_rewritten": query}, ensure_ascii=False)

    # -- refusal -----------------------------------------------------------
    def _refuse(self, prompt: str) -> str:
        """Return empty so the caller uses its hand-written fallback.

        Deliberate: the refusal text must be human-written, and the cleanest
        way for the stub to honour that is to decline to write one.
        """
        return ""

    # -- answer ------------------------------------------------------------
    def _answer(self, prompt: str) -> str:
        """Assemble an answer from the fenced sources.

        Every sentence carries a citation marker and the form of address is
        correct for the language, so the citation plumbing and the register
        audit are both genuinely exercised.
        """
        lang = self._lang(prompt)
        s = _SCAFFOLD.get(lang, _SCAFFOLD["en"])
        blocks = SOURCE_BLOCK_RE.findall(prompt)
        if not blocks:
            return s["empty"]

        lines = [s["opening"], ""]
        for n, text in blocks[:3]:
            lines.append(f"{n}. {_first_sentence(text)} [{n}]")
        lines += ["", f"{s['mentor']} [{blocks[0][0]}]."]
        return "\n".join(lines)


def _first_sentence(text: str, limit: int = 140) -> str:
    """First sentence of a source block, trimmed to keep sentences short."""
    text = " ".join((text or "").split())
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return cut[:limit].rstrip(" ,;")
