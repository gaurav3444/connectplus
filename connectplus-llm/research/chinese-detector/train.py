"""
Train a classical ML text classifier that detects whether typed text is
Chinese, using real informal dialogue (TVsub) instead of the old
mandarin_detector's newswire-register data.

Trained incrementally, in chunks, via SGDClassifier.partial_fit --
scikit-learn's standard "out-of-core" pattern. Two earlier approaches were
tried and killed by the environment on this machine (7.8GB RAM):

  1. TfidfVectorizer + LogisticRegression, fit() on all 3.28M rows at
     once (x7, for 5-fold CV + a held-out fit + the final fit). Got all
     the way through the computation (~35 min) but was killed mid-way
     through writing the 243MB result to disk -- and 243MB exceeds
     GitHub's 100MB file limit anyway, so that model couldn't have
     shipped even if the save had succeeded.
  2. HashingVectorizer + SGDClassifier, but still via a single fit() on
     the full dataset -- fixed *feature* memory, but still needed the
     whole 3.28M-row matrix resident at once. Killed during the first
     of 5 CV folds.

Both failed for the same underlying reason: something needed the entire
dataset's vectorized matrix in memory simultaneously. This version never
does -- it reads the CSV in chunks and updates the model one chunk at a
time, so peak memory is bounded by one chunk (a few thousand rows), not
by the dataset (3.28M rows). Same data, all of it, no sampling.

Usage:
    python data/build_dataset.py     # once, needs the TVsub clone
    python train.py                  # train incrementally, save
    python evaluate.py               # headline numbers against langdetect

Output:
    models/chinese_detector.joblib
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "dataset.csv"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "chinese_detector.joblib"

POSITIVE_LABEL = "zh"
OTHER_LABEL = "other"
CLASSES = np.array([OTHER_LABEL, POSITIVE_LABEL])
N_FEATURES = 2**20  # fixed hash-bucket count -- memory does not grow with corpus size
CHUNK_ROWS = 50_000


def build_vectorizer() -> HashingVectorizer:
    return HashingVectorizer(analyzer="char_wb", ngram_range=(1, 4), n_features=N_FEATURES, alternate_sign=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk-rows", type=int, default=CHUNK_ROWS)
    args = ap.parse_args()

    if not DATA_PATH.exists():
        raise SystemExit(f"{DATA_PATH} not found. Run data/build_dataset.py first.")

    vectorizer = build_vectorizer()
    clf = SGDClassifier(loss="log_loss", random_state=42)

    total_rows = 0
    total_correct = 0  # prequential: score each chunk BEFORE training on it
    first_chunk = True

    print(f"Training incrementally in chunks of {args.chunk_rows} rows...", flush=True)
    for chunk in pd.read_csv(DATA_PATH, chunksize=args.chunk_rows):
        chunk = chunk.dropna(subset=["text", "label"])
        texts = chunk["text"].tolist()
        labels = chunk["label"].to_numpy()
        X = vectorizer.transform(texts)

        if not first_chunk:
            preds = clf.predict(X)
            total_correct += int((preds == labels).sum())

        clf.partial_fit(X, labels, classes=CLASSES if first_chunk else None)

        total_rows += len(texts)
        first_chunk = False
        print(f"  ...{total_rows} rows seen", flush=True)

    if total_rows > args.chunk_rows:
        prequential_n = total_rows - args.chunk_rows  # first chunk had no prior model to score with
        print(
            f"\nPrequential accuracy (each chunk scored by the model BEFORE it trained on that "
            f"chunk -- an honest, always-held-out-in-time estimate): "
            f"{total_correct}/{prequential_n} = {total_correct / prequential_n:.3f}",
            flush=True,
        )

    pipeline = Pipeline([("hash", vectorizer), ("clf", clf)])
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    print(f"\nTrained on {total_rows} rows total. Saved model to {MODEL_PATH}", flush=True)
    print("Run evaluate.py for the headline numbers against TVsub's held-out dev/test splits and langdetect.", flush=True)


if __name__ == "__main__":
    main()
