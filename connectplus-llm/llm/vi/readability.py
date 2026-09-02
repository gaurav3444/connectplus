"""A readability proxy for Vietnamese.

Why the standard metrics cannot be used
---------------------------------------
The eval harness scores "readability grade", and the obvious tool is
Flesch-Kincaid. It does not work here, and it does not fail loudly - it returns
a confident number that means nothing.

Flesch-Kincaid counts syllables per *word*. Vietnamese orthography writes every
syllable as its own whitespace-separated token, so by that definition every
Vietnamese word has exactly one syllable and the syllable term collapses to a
constant. The grade then reduces to sentence length alone, and reports fluent
plain Vietnamese and dense bureaucratic Vietnamese as equally readable.

What this module does instead
-----------------------------
Four signals that do discriminate, chosen because each maps to something a
senior actually struggles with:

===========================  ===========================================
Signal                       What it catches
===========================  ===========================================
Syllables per sentence       Sentences too long to hold while acting on them
Long-sentence rate           A few monsters hiding behind a fine average
Loanword rate                Untranslated English the reader cannot decode
Formal-register rate         Sino-Vietnamese officialese from .gov.au pages
===========================  ===========================================

Honest limitations
------------------
This is a **proxy, not a validated instrument.** The thresholds below are
reasoned from Vietnamese community-health and Be Connected style guidance
(short sentences, everyday vocabulary, one instruction per sentence), not
derived from a reading study. It is fit for the job it has - comparing two
prompt versions or two providers on the same questions - and unfit for
claiming an absolute reading age. The report should say so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .normalize import fold, syllables, sentences
from .termbase import termbase, protected_nouns

__all__ = ["Readability", "score", "TARGETS"]

# Targets, in the units of each signal. "good" scores full marks; anything at
# or past "poor" scores zero for that signal; between them is linear.
TARGETS = {
    "syllables_per_sentence": {"good": 18.0, "poor": 32.0},
    "long_sentence_rate": {"good": 0.10, "poor": 0.45},
    "loanword_rate": {"good": 0.02, "poor": 0.12},
    "formal_per_100": {"good": 0.5, "poor": 4.0},
}

# Weights sum to 1.0. Sentence length carries the most because it is the
# signal seniors report most often ("I lost my place halfway through").
WEIGHTS = {
    "syllables_per_sentence": 0.35,
    "long_sentence_rate": 0.25,
    "loanword_rate": 0.25,
    "formal_per_100": 0.15,
}

_LONG_SENTENCE = 20  # syllables

# Above this share of untranslated English, the text is not really Vietnamese
# and a readability score computed on it is meaningless. Weighted averaging
# alone was not enough here: an answer that left half its content in English
# still scored "easy" because its sentences were short. Readability presumes
# the reader can read the words at all.
_NOT_VIETNAMESE_LOANWORD_RATE = 0.25
_LANGUAGE_INTEGRITY_CAP = 40.0

# Shape of a legal Vietnamese syllable once diacritics are folded away.
# Initial cluster, vowel nucleus, optional final consonant. Deliberately
# permissive - it is used to spot obvious English, not to validate spelling.
_VI_SYLLABLE_RE = re.compile(
    r"^(?:ngh|ng|nh|ch|gh|gi|kh|ph|th|tr|qu|[bcdghklmnprstvx])?"
    r"[aeiouy]{1,3}"
    r"(?:ch|ng|nh|[cmnpt])?$"
)


@dataclass(frozen=True)
class Readability:
    """Readability measurement of one Vietnamese answer.

    Attributes:
        score: 0..100, higher is easier to read.
        grade: ``easy``, ``ok`` or ``hard``.
        syllables_per_sentence: Mean sentence length in syllables.
        long_sentence_rate: Share of sentences over 20 syllables.
        loanword_rate: Share of tokens that are not Vietnamese-shaped and not
            approved proper nouns.
        formal_per_100: Formal-register words per 100 syllables.
        n_sentences: Sentence count.
        n_syllables: Syllable count.
        offenders: The specific tokens and words that cost marks, so a bad
            score can be acted on rather than just reported.
    """

    score: float
    grade: str
    syllables_per_sentence: float
    long_sentence_rate: float
    loanword_rate: float
    formal_per_100: float
    n_sentences: int
    n_syllables: int
    offenders: dict

    def as_dict(self) -> dict:
        return asdict(self)


def _signal_score(value: float, good: float, poor: float) -> float:
    """Map a raw signal onto 0..1, where 1 is at or better than ``good``."""
    if value <= good:
        return 1.0
    if value >= poor:
        return 0.0
    return 1.0 - (value - good) / (poor - good)


def _is_loanword(token: str, allowed: set[str]) -> bool:
    """True if a token is neither Vietnamese-shaped nor an approved name."""
    folded = fold(token)
    if not folded.isalpha():
        return False          # numbers, step markers
    if folded in allowed:
        return False          # myGov, Centrelink, Wi-Fi, OTP ...
    if len(folded) <= 1:
        return False
    return _VI_SYLLABLE_RE.match(folded) is None


def score(text: str) -> Readability:
    """Measure how hard a Vietnamese answer is to read.

    Args:
        text: The generated answer. Markdown is tolerated; list markers and
            emphasis are stripped before measuring.

    Returns:
        A :class:`Readability`. An empty or whitespace-only answer scores 0
        and is graded ``hard`` rather than raising - a blank answer is a
        failure, not an exception.
    """
    clean = re.sub(r"[*_#`>\[\]()]", " ", text or "")
    sents = sentences(clean)
    sylls = syllables(clean)

    if not sents or not sylls:
        return Readability(0.0, "hard", 0.0, 0.0, 0.0, 0.0, 0, 0,
                           {"note": "empty answer"})

    per_sentence = [len(syllables(s)) for s in sents]
    mean_len = sum(per_sentence) / len(per_sentence)
    long_rate = sum(1 for n in per_sentence if n > _LONG_SENTENCE) / len(per_sentence)

    allowed = {fold(n) for noun in protected_nouns() for n in noun.split()}
    loan_tokens = [t for t in sylls if _is_loanword(t, allowed)]
    loan_rate = len(loan_tokens) / len(sylls)

    folded_text = fold(clean)
    formal_hits = [w for w in termbase()["plain_language"]["prefer_plain"]
                   if fold(w) in folded_text]
    formal_per_100 = len(formal_hits) / len(sylls) * 100

    raw = {
        "syllables_per_sentence": mean_len,
        "long_sentence_rate": long_rate,
        "loanword_rate": loan_rate,
        "formal_per_100": formal_per_100,
    }
    total = sum(
        WEIGHTS[k] * _signal_score(v, TARGETS[k]["good"], TARGETS[k]["poor"])
        for k, v in raw.items()
    )
    final = round(total * 100, 1)

    # Language-integrity gate. See _NOT_VIETNAMESE_LOANWORD_RATE.
    capped = loan_rate >= _NOT_VIETNAMESE_LOANWORD_RATE
    if capped:
        final = min(final, _LANGUAGE_INTEGRITY_CAP)

    grade = "easy" if final >= 75 else "ok" if final >= 55 else "hard"

    return Readability(
        score=final,
        grade=grade,
        syllables_per_sentence=round(mean_len, 1),
        long_sentence_rate=round(long_rate, 2),
        loanword_rate=round(loan_rate, 3),
        formal_per_100=round(formal_per_100, 2),
        n_sentences=len(sents),
        n_syllables=len(sylls),
        offenders={
            "loanwords": sorted(set(loan_tokens))[:10],
            "formal_words": formal_hits,
            "longest_sentence_syllables": max(per_sentence),
            "capped_for_untranslated_english": capped,
        },
    )
