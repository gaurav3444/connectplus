"""Chinese text primitives: characters, sentences, Latin content.

Chinese is not whitespace-delimited, so almost nothing carried over from the
Vietnamese lane works here. Counting "words" by splitting on spaces returns 1
for an entire paragraph. Every measure in this package is therefore built on
the Han character and the sentence, which are the units Chinese actually has.
"""

from __future__ import annotations

import re

__all__ = ["han_chars", "count_han", "sentences", "latin_runs",
           "latin_char_rate", "strip_citations"]

_HAN_RE = re.compile(r"[一-鿿㐀-䶿]")

# Chinese sentence-final punctuation, plus the Western equivalents that turn
# up in machine-translated government copy.
_SENTENCE_END = "。！？；!?;\n"
_SENTENCE_SPLIT_RE = re.compile(r"[。！？；!?;\n]+")

# A run of Latin letters, which in a Chinese answer is either a protected
# noun (myGov) or untranslated English the reader cannot decode.
_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'\-\.]*")

_CITATION_RE = re.compile(r"\[\d{1,2}\]")


def strip_citations(text: str) -> str:
    """Remove ``[1]`` markers before measuring anything.

    Citation markers are required by the prompt and would otherwise inflate
    every Latin-content measure in the readability score.
    """
    return _CITATION_RE.sub("", text or "")


def han_chars(text: str) -> list[str]:
    """Every Han ideograph in the text."""
    return _HAN_RE.findall(text or "")


def count_han(text: str) -> int:
    return len(han_chars(text))


def sentences(text: str) -> list[str]:
    """Split on Chinese and Western sentence-final punctuation.

    Numbered list items each count as their own sentence, which is what we
    want: the prompt asks for one instruction per step, and a step that runs
    long should be penalised like any other long sentence.
    """
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text)]
    return [p for p in parts if p and _HAN_RE.search(p)]


def latin_runs(text: str) -> list[str]:
    """Runs of Latin letters, e.g. ``["myGov", "Centrelink"]``."""
    return _LATIN_RUN_RE.findall(text or "")


def latin_char_rate(text: str) -> float:
    """Share of letter-ish characters that are Latin rather than Han.

    The signal that catches an answer which quietly stayed in English. Ratio
    rather than count, so a long answer is not penalised for one brand name.
    """
    text = strip_citations(text)
    han = count_han(text)
    latin = sum(len(r) for r in latin_runs(text))
    total = han + latin
    return (latin / total) if total else 0.0
