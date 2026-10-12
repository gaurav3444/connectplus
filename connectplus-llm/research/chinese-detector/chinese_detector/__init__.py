"""
Importable interface to the trained Chinese-language detector.

This is the piece connectplus-llm's query stage (stage05_query.py /
s07_query.py) imports, in place of `langdetect.detect(...)`:

    from chinese_detector import detect_language

    lang = detect_language(query_text)          # "zh" | "other"
    # or, with confidence, for logging / thresholds:
    result = classify(query_text)                # {"lang": ..., "confidence": ...}

Kept deliberately tiny and dependency-light (joblib + scikit-learn only,
no network calls) so it can be vendored into connectplus-llm as-is, or
installed as a local editable package the same way connectplus-rag is:

    pip install -e ../chinese-detector
"""

from .detector import MODEL_PATH, LanguageResult, classify, detect_language

__all__ = ["classify", "detect_language", "LanguageResult", "MODEL_PATH"]
