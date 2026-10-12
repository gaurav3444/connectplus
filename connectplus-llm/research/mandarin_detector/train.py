"""
Train a classical ML text classifier that detects whether typed text is
Simplified Mandarin Chinese (zh-Hans) or not.

Character n-gram + logistic regression, not an LLM call -- language
identification is a solved, cheap, offline problem.

Usage:
    python data/build_dataset.py     # once, needs internet
    python train.py                  # train, evaluate on a held-out split, save
    python evaluate.py               # the real headline numbers -- see that file

Output:
    models/mandarin_detector.joblib
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "dataset.csv"
MODEL_DIR = ROOT / "models"
MODEL_PATH = MODEL_DIR / "mandarin_detector.joblib"

POSITIVE_LABEL = "zh-Hans"


def load_dataset() -> tuple[list[str], list[str]]:
    if not DATA_PATH.exists():
        raise SystemExit(f"{DATA_PATH} not found. Run data/build_dataset.py first.")
    df = pd.read_csv(DATA_PATH)
    df = df.dropna(subset=["text", "label"])
    return df["text"].tolist(), df["label"].tolist()


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 4), min_df=1)),
        ("clf", LogisticRegression(max_iter=1000)),
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cv", type=int, default=5)
    ap.add_argument("--test-size", type=float, default=0.2)
    args = ap.parse_args()

    texts, labels = load_dataset()
    n_pos = labels.count(POSITIVE_LABEL)
    print(f"Loaded {len(texts)} examples "
          f"({n_pos} {POSITIVE_LABEL}, {len(labels) - n_pos} other)")

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=args.test_size, random_state=42, stratify=labels,
    )

    pipeline = build_pipeline()

    cv_scores = cross_val_score(pipeline, X_train, y_train, cv=args.cv)
    print(f"\nCross-validation accuracy ({args.cv}-fold): "
          f"{cv_scores.mean():.3f} +/- {cv_scores.std():.3f}")

    pipeline.fit(X_train, y_train)
    y_pred = pipeline.predict(X_test)

    print(f"\nHeld-out test accuracy: {accuracy_score(y_test, y_pred):.3f}")
    print("\nClassification report:")
    print(classification_report(y_test, y_pred))
    print("Confusion matrix (rows = true label, columns = predicted label):")
    print(pd.DataFrame(
        confusion_matrix(y_test, y_pred, labels=pipeline.classes_),
        index=pipeline.classes_, columns=pipeline.classes_,
    ))
    print("\nNote: this is the internal train/test split, from the SAME pool "
          "used to fit the model. It measures whether the model learned "
          "anything at all, not real-world accuracy. Run evaluate.py for the "
          "headline numbers against a fully held-out eval set and a baseline.")

    pipeline.fit(texts, labels)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    print(f"\nSaved trained model to {MODEL_PATH}")


if __name__ == "__main__":
    main()
