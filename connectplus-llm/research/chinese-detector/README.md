# chinese-detector

A trained classifier that decides whether typed text is Chinese, to
replace the `langdetect` call in `connectplus-llm`'s query stage. Fresh
project — not an update of the earlier `mandarin_detector` prototype, and
trained on different, more realistic data.

## Why this exists

`connectplus-llm`'s query stage needs to know what language a senior
typed *before* it can rewrite the query into English for retrieval. It
currently reaches for `langdetect`. The tutor asked for a trained model
instead — and separately, `langdetect` is a general-purpose statistical
library tuned on clean, longer text, which is the wrong register for this
app: senior queries are short, informal, and often drop the subject
("怎么了", "没问题"). That's exactly where general-purpose detectors are
weakest.

## The data

[TVsub](https://github.com/longyuewangdcu/tvsub) — the DCU-Tencent
Chinese-English Dialogue Corpus, 2.15M sentence pairs extracted from TV
subtitles. Chosen over the earlier project's CLUE/papluca sentences
because it's dialogue, not newswire: short, colloquial, and full of
dropped pronouns — the closest available match to how a senior actually
types.

Because it's a *parallel* corpus, one source gives both classes for free:
the Chinese side is the positive class, the English side (same corpus, no
separate dataset needed) is the negative class.

TVsub ships its own disjoint train/dev/test files. `build_dataset.py`
uses that split rather than carving a new one, so there's no risk of us
accidentally leaking a line between what the model trains on and what it's
scored against:

| File | Source | Rows | Used for |
|---|---|---|---|
| `data/dataset.csv` | TVsub `train`, entire cleaned/deduplicated pool, no sampling | 3,279,816 (1,648,530 zh / 1,631,286 other) | training |
| `data/eval_set.csv` | TVsub `dev` | 2,056 | development eval |
| `data/test_set.csv` | TVsub `test` | 2,222 | final check, look at once |

This went through three sizes before landing here: 1,000/class → 20,000/class (to kill sampling variance: 5-fold CV variance dropped from ±0.003 to ±0.000) → the entire cleaned pool, every row, no cap at all. The jump to the full 3.28M rows is what forced the model/training-method change described below — it's also the reason that change happened, not an unrelated detour.

**Licence note:** TVsub is distributed "for research purpose" (CC
BY-NC-ND). This project reads it from a local clone to produce a small
labelled training sample — it doesn't redistribute the corpus itself.
Don't commit the `tvsub/` clone (~900MB; already in `.gitignore`), and
keep that in mind before making any derived dataset file public.

## The model

Character n-grams (1–4), hashed into a fixed 2^20-bucket feature space
(`HashingVectorizer`), fed to an `SGDClassifier` trained **incrementally**
via `partial_fit` in 50,000-row chunks — not `TfidfVectorizer` +
`LogisticRegression` fit on the whole dataset at once, which is what an
earlier, smaller version of this project used. That combination works
fine at 20,000 rows; it does not work at 3.28M rows on a machine with
7.8GB of RAM. Two attempts at the full dataset were killed by the
environment before this one:

1. `TfidfVectorizer` + `LogisticRegression`, one `fit()` call on all 3.28M
   rows (repeated 7x for 5-fold CV + a held-out check + the final fit).
   Ran ~35 minutes and completed the computation, but was killed while
   writing the 243MB result to disk — and 243MB exceeds GitHub's 100MB
   file-size limit anyway, so that model couldn't have been committed
   even if the save had succeeded.
2. `HashingVectorizer` + `SGDClassifier`, but still via one `fit()` call
   on the full matrix. Bounded the *feature* space but still needed all
   3.28M rows resident in memory at once; killed partway through the
   first of 5 CV folds.

Both failed for the same reason: something needed the entire dataset's
vectorized matrix in memory simultaneously. The version that actually
works reads the CSV in chunks and updates the model one chunk at a time
(scikit-learn's standard "out-of-core" pattern), so peak memory is
bounded by one chunk, not by the dataset. Same data — all 3.28M rows, no
sampling — just trained in a shape that fits in RAM.

One consequence: 5-fold cross-validation (which needs several full passes
over the data) was dropped for this full-data run, since it would turn
one pass into seven. In its place, `train.py` reports **prequential
accuracy** — each chunk is scored by the model *before* it trains on that
chunk, which is an honest, always-forward-in-time estimate with no extra
passes needed: **99.8%** across the full run. The numbers that actually
matter — held-out accuracy against TVsub's dev/test splits, below — are
unaffected by any of this; `evaluate.py` never changed.

## Results

Headline comparison against `langdetect`, on TVsub's own held-out splits
(never seen in training), trained on the full 3.28M-row dataset:

```
Dev split (2,056 lines):   ours 99.9%   langdetect 84.8%
Test split (2,222 lines):  ours 98.1%   langdetect 81.9%
```

(Marginally below the earlier 20,000-row model's 100.0%/99.1% — expected
and not a concern: this task is close to ceiling regardless of training
size, and the honest generalisation number, prequential accuracy on 3.2M
held-in-time rows, was 99.8%. The full run's real value isn't a higher
score, it's training on every row that was available instead of a sample.)

`langdetect`'s drop against real dialogue (vs. the ~70–95% it usually
gets quoted at on clean corpora) is itself the point — short, informal,
context-dependent text is exactly where a general-purpose detector
struggles, and exactly what this app's users actually type.

**Honesty note:** the eval and test splits come from the same TV-subtitle
distribution as the training data (same shows, same register) — a
genuinely independent third source (e.g. real anonymised query logs, once
they exist) would be stronger evidence than this number alone.

## Setup

```bash
pip install -r requirements.txt
git clone --depth 1 https://github.com/longyuewangdcu/tvsub.git   # ~900MB, needed once
```

## Build the dataset, train, evaluate

```bash
python data/build_dataset.py    # labels the entire cleaned TVsub pool into train/eval/test
python train.py                 # trains incrementally in chunks, saves models/chinese_detector.joblib
python evaluate.py              # the headline numbers above
```

`train.py` prints progress every 50,000 rows and flushes immediately, so
`tail -f` (or just re-`cat`-ing the file) shows real progress rather than
going silent until the end — worth knowing given the training file above.

## Check a single piece of text

```bash
python predict.py "怎么把手机上的字变大"
python predict.py --interactive
```

## Integrating into connectplus-llm

This is the piece that matters for the pipeline: `chinese_detector` is a
small, self-contained importable package (`joblib` + `scikit-learn` only,
no network calls), not just CLI scripts.

```python
from chinese_detector import detect_language, classify

lang = detect_language(query_text)          # "zh" | "other" -- drop-in for langdetect.detect(...)
result = classify(query_text)               # LanguageResult(lang, confidence, scores) -- for logging/thresholds
```

To use it from `connectplus-llm`, either install it the same way that
project already installs `connectplus-rag`:

```bash
pip install -e ../chinese-detector
```

or copy the `chinese_detector/` folder and `models/chinese_detector.joblib`
straight into `connectplus-llm`. Either way, it replaces the `langdetect`
call in the query stage's step [1] (detect language) — the output feeds
the same place `lang` already goes: the query-rewrite step, and the
`lang` field on the `Answer` contract that travels with every response.

Scope note: this is binary (Chinese vs. everything else), matching the
project's current 2-language scope (English + Mandarin). If Vietnamese or
a third language is ever added, this needs a negative class for that
language and a retrain — flag it before assuming this model covers it.

## Layout

```
chinese-detector/
  data/
    build_dataset.py
    dataset.csv / eval_set.csv / test_set.csv   # generated, not source data
  chinese_detector/        # the importable package -- this is what gets consumed downstream
    __init__.py
    detector.py
  models/
    chinese_detector.joblib
  train.py
  evaluate.py
  predict.py
  tvsub/                   # cloned corpus, gitignored, ~900MB
```
