"""
Build the training and evaluation data for the Chinese-language detector
from TVsub (DCU-Tencent Chinese-English Dialogue Corpus) -- real, informal,
short dialogue lines, many with dropped pronouns -- instead of the old
mandarin_detector project's CLUE/papluca sentences.

Source: https://github.com/longyuewangdcu/tvsub
Clone it inside this project folder (as `tvsub/`, next to `data/`) before
running this script:

    git clone --depth 1 https://github.com/longyuewangdcu/tvsub.git

Why TVsub instead of CLUE/papluca:
  Senior queries are short and informal and often drop the subject
  ("怎么了", "没什么") -- that is much closer to TV dialogue than to the
  newswire/social-media register CLUE and papluca are drawn from. The old
  mandarin_detector was trained on the wrong register for this app's real
  input; this one is trained on the right one.

Splits:
  TVsub ships its own disjoint train/dev/test files. We use that split
  rather than carving our own -- dataset.csv (train) and eval_set.csv
  (TVsub's dev split) never share a line, with zero risk of us
  accidentally leaking an example across the split ourselves.
  test_set.csv (TVsub's test split) is kept aside as the one number that
  should only be looked at once, after the model is otherwise finished.

Licence note: TVsub is "for research purpose" (CC BY-NC-ND). This script
reads the corpus from a local clone and writes out a small labelled
sample for training -- it does not redistribute or publish TVsub itself.
Do not commit the `tvsub/` clone (it's ~900MB); .gitignore already
excludes it.

Run once, after cloning TVsub as a sibling folder:
    python data/build_dataset.py
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TVSUB = ROOT.parent / "tvsub" / "data" / "orignal"  # sibling of data/, inside this project

DATASET_PATH = ROOT / "dataset.csv"
EVAL_PATH = ROOT / "eval_set.csv"
TEST_PATH = ROOT / "test_set.csv"

POSITIVE_LABEL = "zh"
NEGATIVE_LABEL = "other"

N_TRAIN_PER_CLASS = None  # None = use the entire cleaned, deduplicated pool, no sampling

MIN_LEN_ZH, MAX_LEN_ZH = 2, 60
MIN_LEN_EN, MAX_LEN_EN = 2, 200

random.seed(42)


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise SystemExit(
            f"{path} not found.\n"
            "Clone TVsub inside this project folder first:\n"
            "  git clone --depth 1 https://github.com/longyuewangdcu/tvsub.git"
        )
    with path.open(encoding="utf-8") as f:
        return [line.strip() for line in f]


def _clean_pool(lines: list[str], min_len: int, max_len: int) -> list[str]:
    seen: set[str] = set()
    pool: list[str] = []
    for text in lines:
        if min_len <= len(text) <= max_len and text not in seen:
            seen.add(text)
            pool.append(text)
    return pool


def _build_split(name: str, zh_path: Path, en_path: Path, n_per_class: int | None) -> list[tuple[str, str]]:
    zh_pool = _clean_pool(_read_lines(zh_path), MIN_LEN_ZH, MAX_LEN_ZH)
    en_pool = _clean_pool(_read_lines(en_path), MIN_LEN_EN, MAX_LEN_EN)
    random.shuffle(zh_pool)
    random.shuffle(en_pool)
    if n_per_class is not None:
        zh_pool = zh_pool[:n_per_class]
        en_pool = en_pool[:n_per_class]
    rows = [(t, POSITIVE_LABEL) for t in zh_pool] + [(t, NEGATIVE_LABEL) for t in en_pool]
    random.shuffle(rows)
    print(f"{name}: {len(rows)} rows ({len(zh_pool)} {POSITIVE_LABEL}, {len(en_pool)} {NEGATIVE_LABEL})")
    return rows


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "label"])
        writer.writerows(rows)


def main() -> None:
    train_rows = _build_split(
        "dataset.csv (train)",
        TVSUB / "train" / "train.zh", TVSUB / "train" / "train.en",
        N_TRAIN_PER_CLASS,
    )
    _write_csv(DATASET_PATH, train_rows)

    eval_rows = _build_split(
        "eval_set.csv (held-out, TVsub's own dev split)",
        TVSUB / "dev" / "dev.orignal.zh", TVSUB / "dev" / "dev.orignal.en",
        None,
    )
    _write_csv(EVAL_PATH, eval_rows)

    test_rows = _build_split(
        "test_set.csv (held-out, TVsub's own test split -- look at this once)",
        TVSUB / "test" / "test.orignal.zh", TVSUB / "test" / "test.orignal.en",
        None,
    )
    _write_csv(TEST_PATH, test_rows)


if __name__ == "__main__":
    main()
