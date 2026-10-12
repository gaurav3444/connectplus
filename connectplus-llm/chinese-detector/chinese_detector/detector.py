"""
Loads the trained model once and exposes a small, stable prediction
interface. This is the only file connectplus-llm needs to know about.

Integration point: connectplus-llm's query stage does language detection
as step [1], before query rewriting and before calling
`rag.retrieve(query_en, lang)`. Today that step calls `langdetect.detect`.
Swap it for `detect_language` from this package -- same job (decide which
language the senior typed in), trained on real, short, informal dialogue
instead of a general-purpose statistical library.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "chinese_detector.joblib"

POSITIVE_LABEL = "zh"
OTHER_LABEL = "other"


@dataclass(frozen=True)
class LanguageResult:
    lang: str                 # "zh" | "other" -- matches the `lang` field on the Answer contract
    confidence: float         # 0..1, probability of the winning label
    scores: dict[str, float]  # both class probabilities, for logging / debugging


@lru_cache(maxsize=1)
def _load_model():
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"No trained model at {MODEL_PATH}.\n"
            "Run, from the chinese-detector project root:\n"
            "  python data/build_dataset.py\n"
            "  python train.py"
        )
    return joblib.load(MODEL_PATH)


def classify(text: str) -> LanguageResult:
    """Full result, with confidence -- use this where you need to log or
    threshold on how sure the detector is, e.g. before deciding to trust
    a language-routing decision for a safety-relevant query."""
    model = _load_model()
    proba = model.predict_proba([text])[0]
    scores = {str(label): float(p) for label, p in zip(model.classes_, proba)}
    lang = POSITIVE_LABEL if scores.get(POSITIVE_LABEL, 0.0) >= 0.5 else OTHER_LABEL
    return LanguageResult(lang=lang, confidence=round(max(scores.values()), 4), scores=scores)


def detect_language(text: str) -> str:
    """Drop-in replacement for `langdetect.detect(text)` in the query
    stage: returns "zh" or "other" instead of a langdetect ISO code."""
    return classify(text).lang
