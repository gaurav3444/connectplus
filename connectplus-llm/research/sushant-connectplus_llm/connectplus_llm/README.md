# connectplus-llm / llm — stage 07: query understanding

Identify the language of a senior's question, translate, and rewrite it
into an English, retrieval-ready search query. Nothing else — this does
not retrieve, generate an answer, or verify anything. Retrieval and
verification are `connectplus-rag`'s job.

**Only three languages are supported: English, Chinese, Vietnamese.**
Anything else is refused before any LLM call — not best-effort translated.

```
senior asks in Mandarin / English / Vietnamese
        │
        ▼
[1] identify language       -- chinese_detector for Chinese; langdetect
                                for English vs. Vietnamese vs. out-of-scope
[2] translate + rewrite     -- LLM call, this repo (skipped entirely if
                                the language isn't one of the three)
        │
        ▼
query_rewritten (English) + lang   -- ready for rag.retrieve(), not built here
```

## Setup

```bash
pip install -r requirements.txt
pip install -e ../chinese-detector      # step [1] -- already trained, see its own README
cp .env.example .env                    # optional -- stub works with no key
```

To use real Gemini instead of the offline stub:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
```

## Run

```bash
python scripts/demo_query.py                       # all 14 fixture questions
pytest tests/ -v                                    # 13 offline tests, no key needed
uvicorn scripts.demo_server:app --port 8000         # interactive demo -> http://localhost:8000
```

## Files

```
connectplus_llm/
  schemas.py       QueryRequest, QueryPlan (the contract retrieve() will need), LLMTrace
  config.py        provider selection, timeouts, prompt version
  lang_id.py       identify_language() -- chinese_detector + langdetect, the 3-language gate
  llm_client.py    provider protocol -- Gemini, Ollama, stub -- + repair retry + fallback
  prompts.py       loads prompts/query_system_v1.txt, builds the user turn
  query.py         understand() -- identify + rewrite; degraded_plan() -- non-LLM fallback;
                    unsupported_plan() -- refusal path, no LLM call
  tracing.py       one JSONL row per call

prompts/query_system_v1.txt   the actual rewrite instructions -- edit here, not in code
fixtures/query_fixtures.json  14 vague phrasings (5 en, 5 zh, 3 vi, 1 out-of-scope),
                               per the README's own stage-07 verification requirement
tests/test_query.py           13 offline tests against the stub
scripts/demo_query.py         runs all fixtures, prints original -> rewritten
scripts/demo_server.py        FastAPI backend for demo.html
demo.html                     interactive browser demo -- must be opened via the server
                               (http://localhost:8000), NOT as a file:// path, or the
                               fetch call to /understand has nowhere to resolve to
```

## Why chinese_detector alone wasn't enough

`chinese_detector` was trained only on Chinese vs. English — it has no
defined behaviour on a third script it has never seen. In testing, it
returned "zh" for Korean input (Hangul), a false positive, because it had
never been trained to reject anything. Fix: `identify_language()` only
trusts a "zh" verdict when the text actually contains at least one real
CJK Unified Ideograph character — a text cannot be Chinese if it contains
zero Chinese characters, regardless of what the classifier guesses from
out-of-distribution n-grams. Everything that isn't Chinese-with-CJK-
characters goes through `langdetect` to decide English vs. Vietnamese vs.
out of scope. This is a different, much easier task than "is this Chinese"
(the old project's own comparison only found `langdetect` weak on Chinese,
not on this), and it's the right tool for a distinction this low-stakes.

## What's verified so far

- Language identification: correct on 5/5 English, 5/5 Chinese, 3/3
  Vietnamese fixtures, and correctly refuses the 1 out-of-scope (Korean)
  fixture without making an LLM call.
- Real Gemini translation/rewriting verified live for all three supported
  languages (not just the offline stub) — see the worked examples in
  `LLM_Stage07_Status_Report.docx`.
- Degraded (no-LLM) fallback path verified for all three languages:
  English gets naive keyword extraction; Chinese and Vietnamese get an
  honest generic fallback query rather than mangled or untranslated text.
- **Not yet verified:** real translation quality by a native speaker. The
  results look correct on inspection, which is not the same standard.
- **Not yet tested:** the Ollama fallback path. Only Gemini-works and
  stub-works are proven; Ollama isn't installed on the dev machine.

## What's explicitly out of scope here

Retrieval, generation, verification, and anything in `connectplus-rag` —
not this repo's job, not built, not stubbed beyond the one-line contract
(`query_rewritten: str`, `lang: "zh" | "en" | "vi" | None`) that retrieval
will need. Any language other than English, Chinese, or Vietnamese is also
explicitly out of scope, by design, not by omission.
