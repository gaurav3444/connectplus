"""
The headline numbers: our trained classifier vs. the `langdetect` library,
on TVsub's own held-out dev and test splits -- neither was seen in
training.

Usage:
    python evaluate.py

Requires models/chinese_detector.joblib (run train.py first) and
data/eval_set.csv + data/test_set.csv (run data/build_dataset.py first).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252, which can't print Chinese
from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

from chinese_detector import MODEL_PATH, detect_language

ROOT = Path(__file__).resolve().parent
EVAL_PATH = ROOT / "data" / "eval_set.csv"
TEST_PATH = ROOT / "data" / "test_set.csv"

POSITIVE_LABEL = "zh"
DetectorFactory.seed = 0  # langdetect is otherwise non-deterministic


def ours(text: str) -> str:
    return detect_language(text)


def baseline_langdetect(text: str) -> str:
    """Map langdetect's raw code onto our binary scheme."""
    try:
        code = detect(text)
    except LangDetectException:
        return "err"
    return POSITIVE_LABEL if code in ("zh-cn", "zh-tw") else "other"


def run_set(df: pd.DataFrame, label: str, show_rows: bool = True) -> None:
    print(f"\n{label}")
    if show_rows:
        print(f"{'expect':<8} {'ours':<8} {'langdetect':<12} text")
        print("-" * 70)

    ours_correct = 0
    lang_correct = 0
    for _, row in df.iterrows():
        expect, text = row["label"], row["text"]
        our_pred = ours(text)
        lang_pred = baseline_langdetect(text)
        ours_correct += our_pred == expect
        lang_correct += lang_pred == expect
        if show_rows:
            shown = text if len(text) <= 40 else text[:37] + "..."
            print(f"{expect:<8} {our_pred:<8} {lang_pred:<12} {shown}")

    n = len(df)
    print(f"\nours          {ours_correct}/{n} = {ours_correct / n:.1%}")
    print(f"langdetect    {lang_correct}/{n} = {lang_correct / n:.1%}")


def main() -> None:
    if not MODEL_PATH.exists():
        raise SystemExit(f"No trained model at {MODEL_PATH}. Run train.py first.")
    if not EVAL_PATH.exists() or not TEST_PATH.exists():
        raise SystemExit("eval_set.csv / test_set.csv not found. Run data/build_dataset.py first.")

    eval_df = pd.read_csv(EVAL_PATH)
    run_set(eval_df, f"Dev split ({len(eval_df)} held-out real dialogue lines)")

    test_df = pd.read_csv(TEST_PATH)
    run_set(test_df, f"Test split ({len(test_df)} held-out real dialogue lines, look at once)", show_rows=False)


if __name__ == "__main__":
    main()
