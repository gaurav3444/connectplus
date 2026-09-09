"""Language detection, shared by stage 02 (documents) and stage 06 (queries).

Its own module rather than living in s02_extract, where it started, for a
concrete reason: importing s02_extract pulls in trafilatura, and stage 06
runs on the ONLINE path. connectplus-llm doing `from rag import understand`
should not have to install the offline crawl-and-extract stack to detect
the language of a question.

One implementation, deliberately - a query and the documents it retrieves
must never be labelled by two detectors that can disagree about what
"zh-cn" means.
"""

from __future__ import annotations

from langdetect import DetectorFactory, LangDetectException, detect

LANG_DETECT_SAMPLE_CHARS = 2000  # enough for a reliable call, fast even on a 40-page PDF

# langdetect is non-deterministic by default: it samples internally, so the
# same input can return different answers across runs. Seeding makes it
# reproducible, which matters more than it sounds - stage 06 runs this on
# short user queries (where the sampling variance is largest), and
# scripts/eval_queries.py has to produce the same hit@3 number twice in a
# row to be worth anything.
DetectorFactory.seed = 0


def detect_lang(text: str) -> str:
    """ISO 639-1 code (langdetect's own, so 'zh-cn' not 'zh'), or "unknown".

    Short input is the weak case: detection on a six-word question is much
    less reliable than on 2000 characters of page text. That is why
    understand() treats an explicitly supplied lang as authoritative and
    only falls back to this.
    """
    sample = text[:LANG_DETECT_SAMPLE_CHARS].strip()
    if not sample:
        return "unknown"
    try:
        return detect(sample)
    except LangDetectException:
        return "unknown"
