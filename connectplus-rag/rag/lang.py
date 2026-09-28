"""Language detection for stage 02 (documents).

Its own module rather than living in s02_extract, where it started, so
anything on the online path can label text without importing trafilatura
and the rest of the offline crawl-and-extract stack.
"""

from __future__ import annotations

from langdetect import DetectorFactory, LangDetectException, detect

LANG_DETECT_SAMPLE_CHARS = 2000  # enough for a reliable call, fast even on a 40-page PDF

# langdetect is non-deterministic by default: it samples internally, so the
# same input can return different answers across runs. Seeding makes it
# reproducible, which matters more than it sounds - the same page has
# to get the same label on every re-run of extract, or the index churns.
DetectorFactory.seed = 0


def detect_lang(text: str) -> str:
    """ISO 639-1 code (langdetect's own, so 'zh-cn' not 'zh'), or "unknown".

    Short input is the weak case: detection on a six-word question is much
    less reliable than on 2000 characters of page text, so a caller that
    already knows the language should trust that over this.
    """
    sample = text[:LANG_DETECT_SAMPLE_CHARS].strip()
    if not sample:
        return "unknown"
    try:
        return detect(sample)
    except LangDetectException:
        return "unknown"
