"""
Check whether typed text is Simplified Mandarin Chinese, using the model
trained by train.py.

Usage:
    python predict.py "怎么把手机上的字变大"
    python predict.py --interactive
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib

MODEL_PATH = Path(__file__).resolve().parent / "models" / "mandarin_detector.joblib"
POSITIVE_LABEL = "zh-Hans"


def load_model():
    if not MODEL_PATH.exists():
        raise SystemExit(f"No trained model at {MODEL_PATH}. Run train.py first.")
    return joblib.load(MODEL_PATH)


def check(model, text: str) -> dict:
    proba = model.predict_proba([text])[0]
    scores = {str(label): float(p) for label, p in zip(model.classes_, proba)}
    return {
        "text": text,
        "is_mandarin": scores.get(POSITIVE_LABEL, 0.0) >= 0.5,
        "confidence": round(max(scores.values()), 4),
        "scores": {k: round(v, 4) for k, v in scores.items()},
    }


def _print_result(result: dict) -> None:
    verdict = "MANDARIN" if result["is_mandarin"] else "NOT MANDARIN"
    print(f"{verdict}  (confidence {result['confidence']:.1%})  "
          f"scores={result['scores']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="text to check")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()

    model = load_model()

    if args.interactive or not args.text:
        print("Type text and press Enter to check it (Ctrl+C to quit).")
        try:
            while True:
                text = input("> ").strip()
                if text:
                    _print_result(check(model, text))
        except (KeyboardInterrupt, EOFError):
            print()
        return

    _print_result(check(model, args.text))


if __name__ == "__main__":
    main()
