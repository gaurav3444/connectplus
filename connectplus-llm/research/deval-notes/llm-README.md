# Vietnamese language layer

Owner: **Deval Patel**. Branch: `Deval`.

This is the Vietnamese half of `connectplus-llm`: everything that decides
whether a Vietnamese senior gets an answer they can actually read and act on.
The pipeline the repo README describes is language-agnostic — it has no idea
whether Vietnamese comes out well or badly. This package is what makes that
answerable, and measurable.

## What runs today

```bash
pip install -r requirements.txt
cp .env.example .env            # optional; everything runs without a key

python -m llm.eval              # 20-question Vietnamese answer eval
python -m llm.eval detect       # language detection vs the langdetect baseline
python -m llm.main "toi bi lua dao" --lang vi
pytest -q                       # 88 tests, no key, no network, no GPU
```

`connectplus-rag` does not exist yet, so retrieval and verification come from
`llm/rag_stub/`. Swapping in the real thing is three lines at the top of
`llm/pipeline.py` and nothing else.

## Layout

| Path | What it is |
|---|---|
| `vi/normalize.py` | Diacritic folding, syllables, sentences |
| `vi/detect.py` | Language detection that survives missing diacritics |
| `vi/termbase.py` | Locked terms, register audit, deterministic query expansion |
| `vi/readability.py` | Readability proxy built for Vietnamese |
| `vi/data/termbase.json` | The word list. **Edit this, not the prompts.** |
| `s07_query.py` | Detection + LLM rewrite + validation + fallback |
| `s08_prompt.py` | Versioned templates, chunk fencing, injection defence |
| `s09_generate.py` | Provider wrapper, citations, the refusal path |
| `providers/` | Gemini, Ollama, deterministic mock |
| `prompts/` | Versioned jinja2 templates + `vi_style.md` |
| `rag_stub/` | Stand-in for `connectplus-rag` |
| `pipeline.py` | Orchestration, for stage 10 to call |
| `eval/` | The scored harness and both datasets |
| `fixtures/` | Fourteen fixture passages + one poisoned chunk |

## The four problems this solves

### 1. Seniors type without diacritics

`toi bi lua dao`, not `tôi bị lừa đảo`. `langdetect` reads that as English,
Indonesian or Somali, and a misdetection means a Vietnamese senior is answered
in English — the exact failure CONNECT Plus exists to prevent.

Measured on `eval/data/detect_cases.json` (40 short queries):

| | all 40 | the 18 hard cases |
|---|---|---|
| this module | **100%** | **100%** |
| `langdetect` | 70% | 33% |

Read that honestly: the detector and the case set were written together, so
this is a regression guard, not an unbiased accuracy estimate. The gap on the
hard cases is the real finding, and it is large.

Above all of it sits one rule: **the language the app already knows always
wins.** Detection only runs on free typed text.

### 2. A description of a problem is not a search query

*"Điện thoại cứ đòi mã"* has to become `two-factor authentication verification
code`. The LLM does the rewrite; `validate_rewrite()` throws it away if it
comes back in Vietnamese, narrated, multi-line or too long, and
`vi/data/termbase.json` provides a deterministic floor that still works with no
model at all. `rewrite_source` on every answer records which path won.

### 3. Register is a correctness problem, not a style one

Vietnamese has no neutral second person. Addressing a 75-year-old as `bạn`
instead of `ông`/`bà` is not informal, it is disrespectful — and `bạn` is what
every model reaches for, because it is what web copy uses. The termbase locks
address, locks safety-critical terms (`xác thực hai bước`, never
`xác minh 2 yếu tố`), keeps Australian service names in English so the reader
can find them on screen, and audits every generated answer against all three.

### 4. Flesch-Kincaid does not work in Vietnamese

It counts syllables per word. Vietnamese writes one syllable per whitespace
token, so that term is constant and the metric silently collapses to sentence
length — reporting fluent plain Vietnamese and dense bureaucratic Vietnamese as
equally readable.

`vi/readability.py` measures four things that do discriminate: syllables per
sentence, long-sentence rate, untranslated-English rate, and formal-register
rate. On two passages saying the same thing it separates plain language (100)
from officialese (25). It is a **proxy, not a validated instrument** — the
thresholds are reasoned from plain-language guidance, not from a reading study.
Use it to compare two prompt versions, not to claim a reading age.

## Safety, in this package

Both of the things the repo README says must be right here:

**Chunks are fenced as data.** `<<<SOURCE n>>>` markers, a prompt that says
everything inside them is data, fence-escape neutralisation, and injection
phrasing detection. The phrase list is for *detection* — a poisoned chunk is
reported by id so it reaches a human as a finding about the knowledge base. The
fence is what actually holds. `tests/test_injection.py` runs a poisoned fixture
through it, including a check that genuine advice containing the word
"instructions" survives untouched.

**The refusal path is a real path.** Refusals happen at three points —
retrieval confidence below threshold, generation failure, verification verdict
— and all three produce the identical user-visible message: plain Vietnamese,
correct address, mentor offer. `FALLBACK_REFUSAL_VI` is hand-written and never
generated, because a refusal fires exactly when the model may be the broken
thing. A model that answers the refusal prompt in English is discarded.

No provider key reaches the client. The frontend calls this service; this
service calls the provider.

## Current numbers

`python -m llm.eval --provider mock`, against the fixture corpus:

```
language_correct           100.0%  (n=20)
rewrite_contains_concept    88.2%  (n=17)
hit_at_3                   100.0%  (n=17)
refusal_correct            100.0%  (n=20)
citations_valid            100.0%  (n=17)
register_correct           100.0%  (n=20)
terms_correct              100.0%  (n=20)
readability_mean             40.0  (17 graded hard)
```

**These are plumbing numbers, not model quality.** The mock copies source text
rather than writing Vietnamese, which is why readability grades hard on every
answered question — the metric is correctly catching untranslated English. The
numbers that belong in the report come from `--provider gemini` and
`--provider ollama`.

`rewrite_contains_concept` at 88.2% is the deterministic termbase floor with no
model at all. Two questions lose a keyword when the expansion list is truncated
to six terms. A real rewrite should clear that.

## What is not done

- **The provider bake-off (D5).** Add a Gemini key to `.env`, then
  `python -m llm.eval --provider gemini --json out/gemini.json` and the same for
  `ollama`. Expect `qwen2.5:7b` to be weaker in Vietnamese than in Chinese; if
  the offline fallback scores badly that is a finding for the report, not a
  defect to hide.
- **Human validation (D6).** Twenty answers, one or two native speakers, rated
  for understandable / respectful / would-follow. The only evidence that any of
  this works for the actual reader.
- **Real retrieval.** Everything above `rag_stub` is written against the real
  signatures and should not need changing.
- **Stage 10.** The FastAPI SSE endpoint belongs to another owner.
  `pipeline.answer()` is the function for it to call. One ordering problem is
  left for it: verification runs on the finished draft, so tokens streamed
  early are already on screen when a refusal arrives. Buffer until the verdict,
  or stream into a state the client can replace.
