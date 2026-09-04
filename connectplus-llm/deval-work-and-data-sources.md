# Vietnamese Language Layer — Work Summary and Data Sources

**Owner:** Deval Patel
**Project:** CONNECT Plus (CW2) — Digital Literacy Platform for CALD Seniors
**Repo:** `connectplus-llm`, branch `Deval`
**Date:** 4 September 2026

---

## 1. Where every piece of data comes from

This is the section to read first. The layer touches five different bodies of
data, and they are **not** the same kind of thing. Three are permanent work
products I authored, one is a temporary placeholder, and one belongs to the RAG
team and does not exist yet.

| # | Data | Who made it | Status | Replaced later? |
|---|---|---|---|---|
| 1 | Trusted source pages | **RAG team** — crawl | Does not exist yet | — |
| 2 | `llm/fixtures/f06_retrieved.json` | Me, by hand | **Placeholder** | **Yes — deleted once #1 lands** |
| 3 | `llm/eval/data/questions_vi.json` | Me, by hand | Permanent | No |
| 4 | `llm/eval/data/detect_cases.json` | Me, by hand | Permanent | No |
| 5 | `llm/vi/data/termbase.json` | Me, by hand | Permanent, living | No — edited as we learn |

### 1.1 The real source data (RAG team's, not mine)

The trusted content the system answers from is crawled, chunked, embedded and
indexed by `connectplus-rag`. That is not my repo and not my work. It is the
only data in this project that comes from the outside world.

I have never had a copy of it, because it does not exist yet.

### 1.2 What I am using instead, right now — and its exact provenance

`llm/fixtures/f06_retrieved.json` holds **14 short passages, roughly 64 words
each, about 900 words in total.** They are attributed to seven domains the
project treats as trusted:

`scamwatch.gov.au` · `servicesaustralia.gov.au` · `my.gov.au` ·
`esafety.gov.au` · `beconnected.esafety.gov.au` · `acma.gov.au` ·
`tisnational.gov.au`

**These passages were written by me for this fixture. They are not scraped, not
copied, and not quoted from those sites, and the URLs in the file are
illustrative rather than live.** They are plausible plain-English summaries of
the kind of guidance those pages carry, written so the pipeline has something
realistic in the right shape to run against.

Three consequences everyone should be clear on:

- **No copyright or scraping question attaches to my work.** Nothing was taken
  from any website.
- **They are not evidence about the real knowledge base.** Retrieval scores
  measured against them describe my code, not our content.
- **They are deliberately incomplete.** There is nothing in them about medical
  advice, immigration, or which phone to buy, because the eval asks those
  questions and the correct behaviour is to refuse them. Coverage was chosen to
  make refusals testable, which is not how a real corpus is chosen.

The file's own header says all of this, so nobody reading the repo later can
mistake it for real content.

Why do it this way at all: the repo README says stages 07–10 should develop
against a fixture and a stubbed verifier from day one so they are not blocked
on the crawl. This is that fixture. It is throwaway by design.

### 1.3 The three datasets that ARE my contribution

These are not placeholders. They stay in the repo permanently, and they are the
substance of my deliverable.

**`questions_vi.json` — 20 Vietnamese evaluation questions, 20 distinct intents.**

Written by me before any prompt was tuned, on purpose. A question set written
after the prompts measures whatever the prompts already happen to do. Composed
of the things a Vietnamese senior in Australia actually asks: scam texts, myGov
security codes, Medicare claims, calling family overseas, free interpreters.

- **5 of 20 are typed without diacritics**, because that is how people type on
  a phone.
- **3 of 20 must be refused** — a medical question, an immigration question,
  and a product-recommendation question. These are not filler. A system that
  answers a medical question out of a digital-literacy knowledge base is more
  dangerous than one that answers nothing, because the reader will act on it.
  The product question is there precisely because it is plausible for the
  service to answer, so the model will want to help.

Each entry carries the expected English concept, the acceptable retrieval hits,
the expected domain, the refusal flag, and a note explaining why it is in the
set.

**`detect_cases.json` — 40 short language-detection cases, 18 marked hard.**

Every string is the length a real query is: three to twelve syllables. Half the
Vietnamese cases are written without diacritics. The `hard` flag marks the ones
where `langdetect` is expected to fail, which is the entire reason the module
exists.

**`termbase.json` — the Vietnamese terminology and register lock.**

| Part | Size | What it does |
|---|---|---|
| Glossary | 29 locked terms | `xác thực hai bước`, never `xác minh 2 yếu tố` |
| Protected nouns | 36 names | myGov, Centrelink, Medicare, Zalo, Viber stay in English |
| Register rules | 4 forbidden forms of address | `bạn` to a senior is an error, not a style note |
| Plain-language map | 16 pairs | `vào` not `truy cập`; `làm` not `thực hiện` |
| Query expansion | 42 phrase entries | Vietnamese intent → English retrieval terms, no model needed |

This is a living file. It is meant to be edited as we learn, and it is the file
to change rather than the prompt templates — it is injected into every prompt
*and* used to audit every answer.

### 1.4 One thing I did not build, and will not

No Vietnamese model was trained or fine-tuned. Pre-training is out of reach for
a semester project and a translation model would duplicate what the LLM already
does inside the rewrite call. The model work here is **selection and control** —
choosing the provider on measured evidence, and constraining its output with the
termbase and the prompt — not training.

---

## 2. What I built

44 files, about 3,300 lines of Python and 1,400 lines of data, on branch
`Deval`. **88 tests pass with no API key, no network and no GPU.**

### The four problems

**1. Seniors type without diacritics.**
`toi bi lua dao`, not `tôi bị lừa đảo`. `langdetect` reads that as English,
Indonesian or Somali. A misdetection means a Vietnamese senior gets answered in
English — the exact failure CONNECT Plus exists to prevent.

Built a detector on a Vietnamese function-word lexicon plus orthographic shape
(Vietnamese is monosyllabic, so its tokens are short and contain no f, j, w, z),
with script and stacked-diacritic rules above it.

| | all 40 cases | the 18 hard cases |
|---|---|---|
| **This module** | **100%** | **100%** |
| `langdetect` | 70% | 33% |

Above all of it, one rule: **the language the app already knows always wins.**
The user chose a language in the interface; a statistical guess must never
overrule a stated fact. Detection runs only on free typed text.

**2. A described problem is not a search query.**
*"Điện thoại cứ đòi mã"* has to become `two-factor authentication verification
code`. The LLM does the rewrite — and it is validated and thrown away if it
comes back still in Vietnamese, narrated ("Here is the English query…"),
multi-line or over-long. The termbase provides a deterministic floor that works
with no model at all. Every answer records which path won.

**3. Register is a correctness problem, not a style one.**
Vietnamese has no neutral second person. Addressing a 75-year-old as `bạn`
instead of `ông`/`bà` is not informal, it is disrespectful — and `bạn` is what
every model reaches for, because it is what web copy uses, and web copy is
written for thirty-year-olds. Locked in the termbase, injected into the prompt,
and audited after generation, because telling a model not to do something is
not the same as it not doing it.

**4. Flesch–Kincaid does not work in Vietnamese.**
It counts syllables per word. Vietnamese writes one syllable per whitespace
token, so that term is constant and the metric silently collapses to sentence
length — scoring fluent plain Vietnamese and dense bureaucratic Vietnamese as
equally readable. It fails without telling you.

Replaced with four signals that do discriminate: syllables per sentence,
long-sentence rate, untranslated-English rate, and formal-register rate. On two
passages saying the same thing it separates plain language (100) from
officialese (25).

### Safety

Both of the things the repo README says must be right in this repo:

- **Chunks are fenced as data.** `<<<SOURCE n>>>` markers, a prompt stating
  everything inside them is data, fence-escape neutralisation, and injection
  phrase detection. The phrase list is for *detection* — a poisoned chunk is
  reported by id so it reaches a human as a finding about the knowledge base.
  The fence is what actually holds. A poisoned fixture chunk is in the repo and
  runs in the test suite, including a check that genuine advice containing the
  word "instructions" survives untouched.
- **The refusal path is a real path.** Refusals fire at three points —
  retrieval confidence too low, generation failure, verification verdict — and
  all three produce one identical message: plain Vietnamese, correct address,
  mentor offer. The fallback wording is hand-written and never generated,
  because a refusal fires exactly when the model may be the broken thing. A
  model that answers the refusal prompt in English is discarded.

### The integration seam

Everything calls `retrieve(query_en, lang, k)` and `verify(draft, chunks)` using
the agreed signatures. Today those resolve to my stub. When `connectplus-rag`
ships as an importable package it is a three-line change at the top of
`pipeline.py` and nothing above it moves.

Gemini is wired in as the provider with Ollama as the offline fallback, behind
one interface — swapping them is an environment variable.

---

## 3. Current results, and how to read them

```
python -m llm.eval --provider mock

language_correct           100.0%  (n=20)
rewrite_contains_concept    88.2%  (n=17)
hit_at_3                   100.0%  (n=17)
refusal_correct            100.0%  (n=20)
citations_valid            100.0%  (n=17)
register_correct           100.0%  (n=20)
terms_correct              100.0%  (n=20)
readability_mean             40.0  (17 graded hard)
```

**These are plumbing numbers, not model quality, and they should not go in the
report as they stand.** Three reasons, all of which I would rather state myself
than have a marker find:

1. **The sources are my fixture, not real content.** Retrieval scored against
   14 passages I wrote is a test of my code, not of our knowledge base.
2. **The mock provider copies source text rather than writing Vietnamese.**
   That is why readability grades hard on every answered question — the metric
   is correctly catching untranslated English. It is working, not broken.
3. **The detection set and the detector were written together.** 100% is a
   regression guard, not an unbiased accuracy estimate. The honest finding is
   the *gap* on hard cases: 33% → 100%.

`rewrite_contains_concept` at 88.2% is the deterministic termbase floor with no
model involved at all. Two questions lose a keyword when the expansion list is
truncated. A real LLM rewrite should clear that.

---

## 4. What unlocks the real numbers

| Blocked on | What it unlocks |
|---|---|
| RAG team's crawl + index | Retrieval and groundedness figures that mean something |
| My Gemini key (have it) | Provider bake-off: Gemini vs `qwen2.5:7b` |
| One or two native speakers | Human validation of 20 answers |

On the bake-off, one thing worth flagging early: `qwen2.5:7b` is our offline
fallback, and its Vietnamese is noticeably weaker than its Chinese. If it scores
badly, **that is a finding for the report, not a defect to hide** — it tells us
the demo-day fallback needs a different model.

---

## 5. How to run it

```bash
pip install -r requirements.txt
cp .env.example .env          # optional — everything runs without a key

python -m llm.eval detect     # detection vs the langdetect baseline
python -m llm.eval            # the 20-question scored table
python -m llm.main "toi bi lua dao" --lang vi
python -m llm.main "Tôi bị đau ngực, tôi nên uống thuốc gì?" --lang vi --trace
pytest -q                     # 88 tests
```

That second `llm.main` call is the by-hand check worth demonstrating: a question
the knowledge base cannot cover comes back as a plain Vietnamese refusal with a
mentor offer, and `--trace` shows exactly where it refused and why.

`uvicorn llm.s10_answer:app` does **not** work — stage 10 is the FastAPI SSE
endpoint and belongs to another owner. `pipeline.answer()` is the function for
it to call.

---

## 6. File map

| Path | What it is |
|---|---|
| `llm/vi/normalize.py` | Diacritic folding, syllables, sentences |
| `llm/vi/detect.py` | Language detection that survives missing diacritics |
| `llm/vi/termbase.py` | Locked terms, register audit, query expansion |
| `llm/vi/readability.py` | Readability proxy built for Vietnamese |
| `llm/vi/data/termbase.json` | **The word list — edit this, not the prompts** |
| `llm/s07_query.py` | Detection + rewrite + validation + fallback |
| `llm/s08_prompt.py` | Versioned templates, fencing, injection defence |
| `llm/s09_generate.py` | Provider wrapper, citations, refusal path |
| `llm/providers/` | Gemini, Ollama, deterministic mock |
| `llm/prompts/` | Versioned jinja2 templates + `vi_style.md` |
| `llm/rag_stub/` | Stand-in for `connectplus-rag` — **temporary** |
| `llm/fixtures/f06_retrieved.json` | 14 fixture passages — **temporary** |
| `llm/pipeline.py` | Orchestration, for stage 10 to call |
| `llm/eval/` | Scored harness + both datasets — **permanent** |
| `tests/` | 88 tests |
