"""Vietnamese text normalisation.

Vietnamese seniors typing on a phone very often omit diacritics: they write
``toi bi lua dao`` rather than ``tôi bị lừa đảo``. Every lexicon lookup in this
package therefore happens on a *folded* form, so both spellings hit the same
entry. Nothing here calls a model; it is pure string work and is safe to run on
every request.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = [
    "fold",
    "syllables",
    "sentences",
    "has_vietnamese_diacritics",
    "VIETNAMESE_ONLY_CHARS",
]

# Combining marks that, in Latin script, are effectively Vietnamese-only.
# The acute, grave and tilde are NOT here: French, Spanish, Italian and
# Portuguese all use them, and treating a bare acute as Vietnamese makes an
# accented French word look like a Vietnamese sentence.
_HOOK_ABOVE = "\u0309"
_DOT_BELOW = "\u0323"
_HORN = "\u031b"          # the o-horn and u-horn
_VIETNAMESE_ONLY_MARKS = {_HOOK_ABOVE, _DOT_BELOW, _HORN}

# Precomposed letters that are Vietnamese-only in their own right.
VIETNAMESE_ONLY_CHARS = set("dD".replace("d", "\u0111").replace("D", "\u0110"))

# Marks shared with other Latin languages one at a time, but whose *stacking*
# is characteristic of Vietnamese: e + circumflex + acute is a single
# Vietnamese letter, and no French or Spanish word stacks two marks this way.
_SHARED_MARKS = {"\u0300", "\u0301", "\u0303", "\u0302", "\u0306"}

_WORD_RE = re.compile(r"[0-9A-Za-zÀ-ỹ]+", re.UNICODE)
_SENTENCE_SPLIT_RE = re.compile(r"[.!?;:\n]+")


def fold(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics, including ``đ`` -> ``d``.

    ``fold("Tôi bị lừa đảo") == fold("toi bi lua dao") == "toi bi lua dao"``

    Unicode decomposition handles the tone marks and vowel modifiers, but it
    does *not* decompose ``đ``/``Đ`` (they are single letters, not d + stroke),
    so those are replaced by hand first.
    """
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unicodedata.normalize("NFC", stripped).lower()


def has_vietnamese_diacritics(text: str) -> bool:
    """True if the text carries orthography only Vietnamese uses.

    Three signals, any one of which is decisive:

    1. The letter ``d`` with stroke.
    2. A hook-above, dot-below or horn - marks no other Latin-script language
       a CONNECT Plus user is likely to type puts on a vowel.
    3. Two marks stacked on one base letter, which is how Vietnamese writes a
       vowel quality plus a tone.

    A bare acute or grave is deliberately not enough. French, Spanish and
    Portuguese use those, and a name or loanword carrying one must not be
    mistaken for a Vietnamese sentence.

    A ``False`` here does not mean "not Vietnamese" - a query typed without
    diacritics returns ``False`` and goes to the lexicon path instead.
    """
    if any(ch in VIETNAMESE_ONLY_CHARS for ch in text):
        return True

    decomposed = unicodedata.normalize("NFD", text)
    marks_on_current_base = 0
    for ch in decomposed:
        if unicodedata.combining(ch):
            if ch in _VIETNAMESE_ONLY_MARKS:
                return True
            if ch in _SHARED_MARKS:
                marks_on_current_base += 1
                if marks_on_current_base >= 2:
                    return True
        else:
            marks_on_current_base = 0
    return False


def syllables(text: str) -> list[str]:
    """Split into orthographic syllables.

    Vietnamese writes every syllable as a separate whitespace-delimited token,
    so this is the unit that matters for readability - not the "word" of an
    English-style tokeniser. ``xác thực hai bước`` is four syllables and two
    semantic words; readability cares about the four.
    """
    return _WORD_RE.findall(text)


def sentences(text: str) -> list[str]:
    """Split into sentences on terminal punctuation and newlines.

    Deliberately crude. Vietnamese does not use abbreviation-final periods
    nearly as much as English, so the usual abbreviation false-splits are rare,
    and a readability proxy does not need better than this.
    """
    parts = (p.strip() for p in _SENTENCE_SPLIT_RE.split(text))
    return [p for p in parts if p]
