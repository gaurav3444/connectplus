# Mandarin (Simplified Chinese) Language Detector — full version

Real data on both sides, a held-out eval set, a Traditional-script hard-case
benchmark, and a comparison against an existing library (`langdetect`) —
the same structure as the Vietnamese detection work this mirrors.

## What's real vs. hand-written

Everything is real, downloaded data. Nothing here is hand-written:

- **Positive (`zh-Hans`)**: CLUE's `afqmc` — real Simplified Chinese
  sentences. Verified as Simplified (not Traditional) with `zhconv` before
  use: converting a sample toward Traditional changed 100% of examples and
  ~37% of characters, which only happens if the source was Simplified.
- **Negative (`other`)**: `papluca/language-identification`, filtered to
  `en` and `vi` — real English and Vietnamese sentences.

`data/build_dataset.py` splits all of this into three **disjoint** files so
the eval numbers below aren't measuring memorisation:

| File | Purpose | Rows |
|---|---|---|
| `data/dataset.csv` | training data | 150 zh-Hans + 150 other |
| `data/eval_set.csv` | held-out, general eval | 20 zh-Hans + 20 other |
| `data/hard_cases_traditional.csv` | held-out zh-Hans sentences, converted to **Traditional** script with `zhconv` | 20 |

## The hard case, and why it's the point

The model only ever sees **Simplified** Chinese in training. The hard-case
file takes held-out Simplified sentences and converts them to Traditional —
still Mandarin, still meant to be routed into the Chinese-language flow, but
written the way a Traditional-script phone (common in Hong Kong/Taiwanese
diaspora households) would actually produce it. This is the closest Mandarin
analogue of "Vietnamese typed without diacritics": same underlying language,
an unexpected but entirely realistic script variant.

`langdetect` fails this badly and not in a subtle way — spot-checked before
building this:

```
我忘记了我的密码怎么办  (Simplified)  -> zh-cn   (correct)
我忘記了我的密碼怎麼辦  (Traditional) -> ko      (Korean -- wrong language family)
```

## Setup

```bash
pip install -r requirements.txt
```

## Build the dataset (needs internet, run once)

```bash
python data/build_dataset.py
```

## Train

```bash
python train.py
```

Trains only on `data/dataset.csv` and reports an internal train/test split
score — a sanity check that the model learned something, not the real
number. The real number is next.

## Evaluate — the headline numbers

```bash
python evaluate.py
```

Runs both the trained model and `langdetect` against `eval_set.csv` and
`hard_cases_traditional.csv`, prints a per-example table, and a summary in
this shape:

```
ours          40/40 = 100.0%
langdetect    28/40 = 70.0%
```

## Check one piece of text

```bash
python predict.py "怎么把手机上的字变大"
python predict.py --interactive
```

## Honesty notes (same standard the rest of this project holds itself to)

- The eval and hard-case sets are held out from training, but they still
  come from the same two source datasets (afqmc, papluca) as the training
  data — same distribution, different rows. A number from a genuinely
  independent third source would be stronger evidence than this one.
- `langdetect` is a general-purpose, decades-old statistical library, not
  the strongest possible baseline. It's a fair comparator because it's
  exactly what a project would reach for by default (as the original
  Vietnamese work here does), not because it's the best alternative
  available today.
