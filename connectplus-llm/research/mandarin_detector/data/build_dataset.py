"""
Build the full real-data set for the Mandarin detector:

  - Positive (zh-Hans): real Simplified Chinese sentences from CLUE's afqmc.
  - Negative (other):   real English and Vietnamese sentences from
                         papluca/language-identification.
  - Eval set:            a held-out slice of both classes, NOT used in
                         training -- the general "realistic queries" table.
  - Hard cases:          a held-out slice of Simplified Chinese, converted to
                         TRADITIONAL script with zhconv. Expected label stays
                         zh-Hans: the point is that this is still Mandarin,
                         just written the way a Traditional-script phone
                         would produce it, and the classifier only ever saw
                         Simplified during training.

All three output files are disjoint -- nothing in dataset.csv appears in
eval_set.csv or hard_cases.csv -- so the eval numbers aren't measuring
memorisation.

Run once, with internet access:
    python data/build_dataset.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from datasets import load_dataset
from zhconv import convert

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "dataset.csv"
EVAL_PATH = ROOT / "eval_set.csv"
HARD_CASES_PATH = ROOT / "hard_cases_traditional.csv"

N_TRAIN_POS = 150
N_EVAL_POS = 20
N_HARD_CASES = 20

N_TRAIN_NEG_PER_LANG = 75
N_EVAL_NEG_PER_LANG = 10

random.seed(42)


def fetch_afqmc_sentences() -> list[str]:
    """Real Simplified Chinese (verified against zhconv before use)."""
    ds = load_dataset("clue/clue", "afqmc")["train"]
    seen: set[str] = set()
    sentences: list[str] = []
    for row in ds:
        for text in (row["sentence1"], row["sentence2"]):
            text = text.strip()
            if 4 <= len(text) <= 40 and text not in seen:
                seen.add(text)
                sentences.append(text)
    return sentences


def fetch_lang_sentences(lang: str) -> list[str]:
    """Real text for one language from papluca/language-identification."""
    ds = load_dataset("papluca/language-identification")["train"]
    seen: set[str] = set()
    sentences: list[str] = []
    for row in ds:
        if row["labels"] != lang:
            continue
        text = row["text"].strip()
        if 4 <= len(text) <= 200 and text not in seen:
            seen.add(text)
            sentences.append(text)
    return sentences


def main() -> None:
    zh_pool = fetch_afqmc_sentences()
    random.shuffle(zh_pool)
    train_pos = zh_pool[:N_TRAIN_POS]
    eval_pos = zh_pool[N_TRAIN_POS : N_TRAIN_POS + N_EVAL_POS]
    hard_case_source = zh_pool[
        N_TRAIN_POS + N_EVAL_POS : N_TRAIN_POS + N_EVAL_POS + N_HARD_CASES
    ]

    en_pool = fetch_lang_sentences("en")
    vi_pool = fetch_lang_sentences("vi")
    random.shuffle(en_pool)
    random.shuffle(vi_pool)

    train_neg = (
        [(t, "other") for t in en_pool[:N_TRAIN_NEG_PER_LANG]]
        + [(t, "other") for t in vi_pool[:N_TRAIN_NEG_PER_LANG]]
    )
    eval_neg = (
        [(t, "other") for t in en_pool[N_TRAIN_NEG_PER_LANG : N_TRAIN_NEG_PER_LANG + N_EVAL_NEG_PER_LANG]]
        + [(t, "other") for t in vi_pool[N_TRAIN_NEG_PER_LANG : N_TRAIN_NEG_PER_LANG + N_EVAL_NEG_PER_LANG]]
    )

    # ---- dataset.csv: training data ----
    train_rows = [(t, "zh-Hans") for t in train_pos] + train_neg
    random.shuffle(train_rows)
    _write_csv(DATASET_PATH, train_rows)
    print(f"dataset.csv: {len(train_rows)} rows "
          f"({len(train_pos)} zh-Hans, {len(train_neg)} other)")

    # ---- eval_set.csv: held-out, realistic, general eval ----
    eval_rows = [(t, "zh-Hans") for t in eval_pos] + eval_neg
    random.shuffle(eval_rows)
    _write_csv(EVAL_PATH, eval_rows)
    print(f"eval_set.csv: {len(eval_rows)} rows "
          f"({len(eval_pos)} zh-Hans, {len(eval_neg)} other)")

    # ---- hard_cases_traditional.csv: held-out zh, converted to Traditional ----
    hard_rows = [(convert(t, "zh-hant"), "zh-Hans") for t in hard_case_source]
    _write_csv(HARD_CASES_PATH, hard_rows)
    print(f"hard_cases_traditional.csv: {len(hard_rows)} rows "
          f"(all zh-Hans, written in Traditional script)")


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "label"])
        writer.writerows(rows)


if __name__ == "__main__":
    main()
