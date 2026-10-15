"""Traditional Chinese text primitives.

Re-exports :mod:`llm.zh.normalize` unchanged. Every function there is
built on the Han character and CJK sentence-final punctuation, which
are the same Unicode ranges in Simplified and Traditional text -- there
is nothing script-specific left to write here. See :mod:`llm.zh_hant`
for why this is a re-export rather than a copy.
"""

from __future__ import annotations

from ..zh.normalize import (
    han_chars, count_han, sentences, latin_runs,
    latin_char_rate, strip_citations,
)

__all__ = ["han_chars", "count_han", "sentences", "latin_runs",
           "latin_char_rate", "strip_citations"]
