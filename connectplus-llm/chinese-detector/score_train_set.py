"""
One-off: score the final trained model against its own training set
(data/dataset.csv), in chunks to keep memory bounded. This is the
standard "training accuracy" number -- how well the finished model fits
the data it was trained on -- to sit alongside evaluate.py's dev/test
numbers for a proper train/validation/test comparison.
"""

from __future__ import annotations

import sys

import pandas as pd

from chinese_detector.detector import _load_model  # one-off script, not part of the public API

sys.stdout.reconfigure(encoding="utf-8")

DATA_PATH = "data/dataset.csv"
CHUNK_ROWS = 100_000


def main() -> None:
    model = _load_model()
    total = 0
    correct = 0
    for chunk in pd.read_csv(DATA_PATH, chunksize=CHUNK_ROWS):
        chunk = chunk.dropna(subset=["text", "label"])
        preds = model.predict(chunk["text"].tolist())
        correct += int((preds == chunk["label"].to_numpy()).sum())
        total += len(chunk)
    print(f"Training-set accuracy: {correct}/{total} = {correct / total:.4f}")


if __name__ == "__main__":
    main()
