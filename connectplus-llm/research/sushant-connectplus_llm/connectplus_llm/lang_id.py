"""
Language identification for stage 07. Two tools, two different jobs:

  - chinese_detector (trained, verified, ~98%+ on held-out data) decides
    Chinese vs. not -- the one distinction worth a trained model, since
    it's the safety-critical routing decision and general-purpose
    detectors measurably struggle with short, informal Chinese text.

  - langdetect decides English vs. Vietnamese vs. out-of-scope, for
    anything chinese_detector says is not Chinese. This is a much easier,
    lower-stakes distinction (Latin-script languages with a diacritic
    difference), which is exactly what langdetect is reasonable at -- the
    old project's own comparison only found langdetect weak on Chinese,
    not on this.

Only three languages are in scope: Chinese, English, Vietnamese. Anything
else returns None -- the caller must refuse before any LLM call, not
best-effort translate something we were never asked to support.
"""

from __future__ import annotations

from chinese_detector import detect_language
from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

from .schemas import Lang

DetectorFactory.seed = 0  # langdetect is otherwise non-deterministic


def _contains_cjk(text: str) -> bool:
    """True if text has at least one real CJK Unified Ideograph. chinese_detector
    was only ever trained on Chinese vs. English -- it has no defined behaviour
    on a third script it has never seen (e.g. Korean Hangul), and can and does
    say "zh" for text that contains no Chinese characters at all. A text
    cannot be Chinese if it contains zero Chinese characters, regardless of
    what the classifier guesses from out-of-distribution n-grams, so this
    gates whether its "zh" verdict is trusted."""
    return any("一" <= ch <= "鿿" for ch in text)


def identify_language(text: str) -> Lang | None:
    """Returns "zh", "en", "vi", or None if the text is in none of those."""
    if _contains_cjk(text) and detect_language(text) == "zh":
        return "zh"

    try:
        code = detect(text)
    except LangDetectException:
        return None

    if code == "en":
        return "en"
    if code == "vi":
        return "vi"
    return None
