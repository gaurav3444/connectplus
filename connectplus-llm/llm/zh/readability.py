"""A readability proxy for Chinese.

Why the standard metrics cannot be used
---------------------------------------
Flesch-Kincaid counts syllables per word and words per sentence. Chinese has
neither unit in the form the formula expects: it is not whitespace-delimited,
so "words per sentence" needs a segmenter before the metric can even start,
and every Han character is one syllable, so the syllable term is a constant.
Run it on Chinese and it returns a confident number computed from whitespace
that mostly is not there.

The Vietnamese lane hit the same wall for the opposite reason -- Vietnamese
writes one syllable per whitespace token, so its syllable term is *also*
constant. Both lanes therefore use a purpose-built proxy rather than a
borrowed formula. The signals differ because the writing systems differ.

What this module measures
-------------------------
=============================  =========================================
Signal                         What it catches
=============================  =========================================
Characters per sentence        Sentences too long to hold while acting
Long-sentence rate             A few monsters hiding behind a fine mean
Latin content rate             Untranslated English the reader can't read
Formal-register rate           Bureaucratic Chinese from translated .gov copy
=============================  =========================================

Honest limitations
------------------
This is a **proxy, not a validated instrument.** The thresholds are reasoned
from plain-language guidance for Chinese community health materials, not
derived from a reading study with older adults. It is fit for comparing two
prompt versions or two providers on the same questions, and unfit for
claiming an absolute reading age. The report should say exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

from .normalize import (count_han, latin_char_rate, sentences,
                        strip_citations)
from .termbase import termbase

__all__ = ["Readability", "score", "TARGETS", "WEIGHTS"]

# "good" scores full marks, "poor" scores zero, between them is linear.
TARGETS = {
    "chars_per_sentence": {"good": 22.0, "poor": 45.0},
    "long_sentence_rate": {"good": 0.10, "poor": 0.45},
    "latin_rate":         {"good": 0.03, "poor": 0.15},
    "formal_per_100":     {"good": 0.5,  "poor": 4.0},
}

# Weights sum to 1.0. Sentence length carries the most: it is the complaint
# seniors actually voice ("I lost my place halfway through").
WEIGHTS = {
    "chars_per_sentence": 0.35,
    "long_sentence_rate": 0.25,
    "latin_rate":         0.25,
    "formal_per_100":     0.15,
}

_LONG_SENTENCE = 30  # Han characters

# Above this share of Latin content the text is not really Chinese, and a
# readability score computed on it is meaningless. Weighted averaging alone
# was not enough: an answer that left half its content in English still
# scored "easy" because its sentences were short. Readability presumes the
# reader can read the characters at all.
_NOT_CHINESE_LATIN_RATE = 0.30
_LANGUAGE_INTEGRITY_CAP = 40.0


@dataclass(frozen=True)
class Readability:
    """A readability estimate with its working shown.

    Attributes:
        score: 0..100, higher is easier. Not a reading age.
        grade: ``easy``, ``ok`` or ``hard``.
        signals: The raw measurements, so a score can be argued with.
        capped: True when the language-integrity cap was applied, i.e. the
            text was too English for the other signals to mean anything.
    """

    score: float
    grade: str
    signals: dict
    capped: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def _signal_score(value: float, good: float, poor: float) -> float:
    """Map one measurement onto 0..1, linear between the two thresholds."""
    if value <= good:
        return 1.0
    if value >= poor:
        return 0.0
    return 1.0 - (value - good) / (poor - good)


def _formal_hits(text: str) -> int:
    """Count formal-register words that have a plain equivalent."""
    pairs = {k for k in termbase()["plain_language"] if not k.startswith("_")}
    return sum(text.count(word) for word in pairs)


def score(text: str) -> Readability:
    """Score a Chinese answer for plain-language readability.

    Args:
        text: The generated answer, citation markers included -- they are
            stripped internally.

    Returns:
        A :class:`Readability`.
    """
    clean = strip_citations(text or "")
    sents = sentences(clean)
    han = count_han(clean)

    if not sents or han == 0:
        return Readability(0.0, "hard",
                           {"chars_per_sentence": 0.0, "long_sentence_rate": 0.0,
                            "latin_rate": latin_char_rate(clean),
                            "formal_per_100": 0.0, "sentences": 0, "han_chars": han},
                           capped=True)

    per_sentence = [count_han(s) for s in sents]
    chars_per_sentence = sum(per_sentence) / len(per_sentence)
    long_rate = sum(1 for c in per_sentence if c > _LONG_SENTENCE) / len(per_sentence)
    latin_rate = latin_char_rate(clean)
    formal_per_100 = (_formal_hits(clean) / han) * 100

    signals = {
        "chars_per_sentence": round(chars_per_sentence, 1),
        "long_sentence_rate": round(long_rate, 3),
        "latin_rate": round(latin_rate, 3),
        "formal_per_100": round(formal_per_100, 2),
        "sentences": len(sents),
        "han_chars": han,
    }

    total = 0.0
    for name, weight in WEIGHTS.items():
        t = TARGETS[name]
        total += _signal_score(signals[name], t["good"], t["poor"]) * weight
    value = round(total * 100, 1)

    capped = False
    if latin_rate >= _NOT_CHINESE_LATIN_RATE and value > _LANGUAGE_INTEGRITY_CAP:
        value = _LANGUAGE_INTEGRITY_CAP
        capped = True

    grade = "easy" if value >= 70 else "ok" if value >= 45 else "hard"
    return Readability(value, grade, signals, capped)
