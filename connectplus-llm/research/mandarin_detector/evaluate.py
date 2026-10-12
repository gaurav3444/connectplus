"""
The headline numbers: our trained classifier vs. the `langdetect` library,
on two held-out sets that were never used in training.

  1. eval_set.csv              -- a general, realistic mix of zh-Hans/other.
  2. hard_cases_traditional.csv -- the stress test: the SAME kind of
     Simplified sentences, written in Traditional script instead. The model
     only ever saw Simplified during training. This is the closest Mandarin
     analogue of "typed without diacritics" for Vietnamese: same language,
     unexpected but real script variant a senior's phone could easily
     produce.

Usage:
    python evaluate.py

Requires models/mandarin_detector.joblib (run train.py first) and
data/eval_set.csv + data/hard_cases_traditional.csv (run data/build_dataset.py
first).
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / "models" / "mandarin_detector.joblib"
EVAL_PATH = ROOT / "data" / "eval_set.csv"
HARD_CASES_PATH = ROOT / "data" / "hard_cases_traditional.csv"

POSITIVE_LABEL = "zh-Hans"
DetectorFactory.seed = 0  # langdetect is otherwise non-deterministic


def ours(model, text: str) -> str:
    proba = model.predict_proba([text])[0]
    scores = dict(zip(model.classes_, proba))
    return POSITIVE_LABEL if scores.get(POSITIVE_LABEL, 0.0) >= 0.5 else "other"


def baseline_langdetect(text: str) -> str:
    """Map langdetect's raw code onto our binary scheme."""
    try:
        code = detect(text)
    except LangDetectException:
        return "err"
    return POSITIVE_LABEL if code in ("zh-cn", "zh-tw") else "other"


def run_set(model, df: pd.DataFrame, label: str) -> None:
    print(f"\n{label}")
    print(f"{'expect':<8} {'ours':<8} {'langdetect':<12} text")
    print("-" * 70)

    ours_correct = 0
    lang_correct = 0
    for _, row in df.iterrows():
        expect, text = row["label"], row["text"]
        our_pred = ours(model, text)
        lang_pred = baseline_langdetect(text)
        ours_correct += our_pred == expect
        lang_correct += lang_pred == expect
        shown = text if len(text) <= 40 else text[:37] + "..."
        print(f"{expect:<8} {our_pred:<8} {lang_pred:<12} {shown}")

    n = len(df)
    print(f"\nours          {ours_correct}/{n} = {ours_correct / n:.1%}")
    print(f"langdetect    {lang_correct}/{n} = {lang_correct / n:.1%}")


def main() -> None:
    if not MODEL_PATH.exists():
        raise SystemExit(f"No trained model at {MODEL_PATH}. Run train.py first.")
    for path in (EVAL_PATH, HARD_CASES_PATH):
        if not path.exists():
            raise SystemExit(f"{path} not found. Run data/build_dataset.py first.")

    model = joblib.load(MODEL_PATH)
    eval_df = pd.read_csv(EVAL_PATH)
    hard_df = pd.read_csv(HARD_CASES_PATH)

    run_set(model, eval_df, f"General eval set ({len(eval_df)} held-out real examples)")
    run_set(model, hard_df,
            f"Hard cases: same Chinese, written in Traditional script "
            f"({len(hard_df)} held-out examples, never seen in training)")


if __name__ == "__main__":
    main()
