"""A readability proxy for Vietnamese.

ATTRIBUTION: the Vietnamese lane is **Deval Patel's work**. This is a slim
stand-in so the integrated pipeline runs; replace it with his
``llm/vi/readability.py`` on merge. The reasoning below is his and is
reproduced so the stand-in behaves the same way.

Why Flesch-Kincaid cannot be used
----------------------------------
It counts syllables per word. Vietnamese orthography writes every syllable
as its own whitespace-separated token, so by that definition every word has
exactly one syllable, the syllable term collapses to a constant, and the
grade reduces to sentence length alone. It then reports fluent plain
Vietnamese and dense bureaucratic Vietnamese as equally readable, and it
fails without telling you.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .termbase import PLAIN_LANGUAGE, PROTECTED_NOUNS

__all__ = ["Readability", "score", "TARGETS", "WEIGHTS"]

TARGETS = {
    "syllables_per_sentence": {"good": 18.0, "poor": 32.0},
    "long_sentence_rate":     {"good": 0.10, "poor": 0.45},
    "loanword_rate":          {"good": 0.02, "poor": 0.12},
    "formal_per_100":         {"good": 0.5,  "poor": 4.0},
}

WEIGHTS = {
    "syllables_per_sentence": 0.35,
    "long_sentence_rate":     0.25,
    "loanword_rate":          0.25,
    "formal_per_100":         0.15,
}

_LONG_SENTENCE = 20  # syllables
_NOT_VIETNAMESE_LOANWORD_RATE = 0.25
_LANGUAGE_INTEGRITY_CAP = 40.0

_CITATION_RE = re.compile(r"\[\d{1,2}\]")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;\n]+")
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'\-\.]*")
_VI_CHARS = "àáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"


@dataclass(frozen=True)
class Readability:
    score: float
    grade: str
    signals: dict
    capped: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _signal_score(value: float, good: float, poor: float) -> float:
    if value <= good:
        return 1.0
    if value >= poor:
        return 0.0
    return 1.0 - (value - good) / (poor - good)


def _syllables(text: str) -> list[str]:
    """Vietnamese writes one syllable per whitespace token."""
    return [t for t in re.findall(r"[^\W\d_]+", text, re.UNICODE) if t]


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text or "")]
    return [p for p in parts if p and _syllables(p)]


def score(text: str) -> Readability:
    """Score a Vietnamese answer for plain-language readability."""
    clean = _CITATION_RE.sub("", text or "")
    sents = _sentences(clean)
    syls = _syllables(clean)

    if not sents or not syls:
        return Readability(0.0, "hard",
                           {"syllables_per_sentence": 0.0, "long_sentence_rate": 0.0,
                            "loanword_rate": 0.0, "formal_per_100": 0.0,
                            "sentences": 0, "syllables": 0}, capped=True)

    per_sentence = [len(_syllables(s)) for s in sents]
    syl_per_sentence = sum(per_sentence) / len(per_sentence)
    long_rate = sum(1 for n in per_sentence if n > _LONG_SENTENCE) / len(per_sentence)

    protected = {n.lower() for n in PROTECTED_NOUNS}
    latin = [r for r in _LATIN_RUN_RE.findall(clean)
             if len(r) > 2 and r.lower() not in protected]
    # A token with no Vietnamese-only character and no Vietnamese shape is a
    # loanword the reader has to decode rather than read.
    loan = [t for t in latin if not any(c in _VI_CHARS for c in t.lower())
            and len(t) > 4]
    loanword_rate = len(loan) / len(syls) if syls else 0.0

    formal_hits = sum(clean.lower().count(k) for k in PLAIN_LANGUAGE)
    formal_per_100 = (formal_hits / len(syls)) * 100

    signals = {
        "syllables_per_sentence": round(syl_per_sentence, 1),
        "long_sentence_rate": round(long_rate, 3),
        "loanword_rate": round(loanword_rate, 3),
        "formal_per_100": round(formal_per_100, 2),
        "sentences": len(sents),
        "syllables": len(syls),
    }

    total = 0.0
    for name, weight in WEIGHTS.items():
        t = TARGETS[name]
        total += _signal_score(signals[name], t["good"], t["poor"]) * weight
    value = round(total * 100, 1)

    capped = False
    if loanword_rate >= _NOT_VIETNAMESE_LOANWORD_RATE and value > _LANGUAGE_INTEGRITY_CAP:
        value = _LANGUAGE_INTEGRITY_CAP
        capped = True

    grade = "easy" if value >= 70 else "ok" if value >= 45 else "hard"
    return Readability(value, grade, signals, capped)
