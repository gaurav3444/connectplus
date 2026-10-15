# connectplus-llm

Language and answer service for **CONNECT Plus**, a digital navigation and referral platform for culturally and linguistically diverse (CALD) seniors.

Takes a senior's question in their own language, works out what they actually need, pulls trusted source material from [`connectplus-rag`](../connectplus-rag), writes a plain-language answer, sends it back to `connectplus-rag` to be checked, and streams whatever survives to [`connect-plus-app`](../connect-plus-app).

This repo does the **understanding, translating and writing**. It does not decide what counts as trustworthy. That call belongs to `connectplus-rag`, and this service obeys the verdict.

`connectplus-rag` is imported as a Python package, not called over HTTP. One process, one port. Separate repos are for ownership and git history, not for deployment.

---

## Why this exists

The tutor requirement is a RAG + LLM component, but the product reason is narrower: seniors need trusted content *explained*, in their language, at their reading level, not a link to an English page they can't parse.

Three things this service is responsible for:

- **Crossing the language gap.** The senior asks in Mandarin; the trusted sources are in English. The query is translated and normalised for retrieval, and the answer is written directly in the senior's language rather than translated after the fact. One hop instead of two, and less drift in safety-critical wording.
- **Turning a vague goal into a retrievable one.** *"My phone keeps asking for a code"* is not a search query. It is two-factor authentication, and the retrieval layer needs to be told that.
- **Writing for the reader.** Short numbered steps, no jargon, plain language, citation markers on every claim. The prompt enforces it; the eval measures it.

It is explicitly **not** responsible for judging its own output. A model grading its own answer is the weakest link in a safety chain, so that check lives in a separate repo with the source text in hand.

## Flow

```
                 senior asks in Mandarin
                            │
  ┌─────────────────────────▼──────────────────────────┐
  │ connectplus-llm                                    │
  │                                                    │
  │ [1] detect language                                │
  │ [2] translate + rewrite query → EN, expand terms   │
  │                                                    │
  │     chunks, conf = rag.retrieve(q_en, lang)        │
  │                                                    │
  │ [3] build prompt (plain language, steps, cite)     │
  │ [4] generate answer, in the senior's language      │
  │                                                    │
  │     verdict = rag.verify(draft, chunks)            │
  │                                                    │
  │ [5] stream answer, or refusal + mentor offer       │
  └────────────────────────────────────────────────────┘
```

Two calls into `connectplus-rag`, both plain function calls in the same process:

```python
from rag import retrieve, verify

chunks, confidence = retrieve(query_en, lang)
draft = generate(chunks, lang)
verdict = verify(draft, chunks)
```

Retrieval happens **before** generation, not just verification after. Without it the model answers from its own training data and the verifier has nothing to grade it against: near everything comes back ungrounded, and the ones that pass are the plausible inventions. Chunks in, answer out, answer checked against those same chunks.

## Scope

| Stage | Module | What it does |
|---|---|---|
| 07 | `s07_query.py` | Language detection, translation, query rewriting, term expansion |
| 08 | `s08_prompt.py` | Versioned jinja2 templates, chunk fencing, target-language instruction |
| 09 | `s09_generate.py` | Provider wrapper (Gemini ⇄ Ollama), streamed generation |
| 10 | `s10_answer.py` | FastAPI `/ask` SSE endpoint, orchestrates retrieve → generate → verify |
| eval | `eval/` | ~20 fixed questions scored on hit@3, groundedness, readability, refusal |

Crawling, chunking, indexing, retrieval and verification live in `connectplus-rag`.

## Layout

```
llm/
  schemas.py         # Answer contract (mirrors connectplus-rag/schemas.py)
  fixtures/          # f05_query.json → f06_retrieved.json → f07_draft.json
  s07_query.py
  s08_prompt.py
  s09_generate.py
  s10_answer.py      # FastAPI app
  providers/         # gemini.py, ollama.py; one interface, chosen by env var
  prompts/           # versioned templates
  eval/
tests/
```

### Contract

```python
Answer = {
    answer_md,
    citations: [ { n, url, title, domain } ],
    confidence,                    # 0..1, from retrieval
    refused, refusal_reason,       # set from the rag verdict
    chunk_ids, prompt_version, provider,
    query_original, query_rewritten, lang,
}
```

`chunk_ids`, `prompt_version`, `provider` and both query forms are on the envelope so a bad answer traces back to the exact chunks, prompt and translation that produced it. Every call is logged.

## Safety, in this repo

Verification is `connectplus-rag`'s job, but two things must be right *here* or verification can't save them:

- **Chunks are fenced as data in the prompt.** Source pages come from the open web. A page saying *"ignore previous instructions"* must not steer the model. Test it with a poisoned fixture chunk.
- **The refusal path is a real path, not an error.** When the verdict is a refusal, the user gets a plain sentence and a mentor offer. Not a stack trace, not a blank screen, and not a retry that quietly lowers the bar.

No provider key ever reaches the client bundle. The frontend calls this service; this service calls the provider.

## Stack

| Concern | Choice | Why |
|---|---|---|
| API | FastAPI + SSE | Streaming is one generator function; the app needs tokens as they arrive |
| LLM | Gemini free tier, Ollama local fallback | Free. The local fallback means the demo survives a dead quota or no wifi |
| Translation | The same LLM, in the query-rewrite call | It's already there and already multilingual. No translation API, no extra key |
| Language detection | `langdetect` | The app already knows the user's chosen language; this is a fallback for typed input |
| Prompts | jinja2, versioned files | Prompt version ships on every answer; diffs are reviewable |
| Tests | pytest | Enough for a prototype |

Swapping Gemini → Ollama is an env var. If it ever needs a code change, the wrapper is wrong.

## Setup

```bash
python -m venv .venv && .venv/Scripts/activate     # Windows
pip install -r requirements.txt
pip install -e ../connectplus-rag                   # retrieval + verification
cp .env.example .env
```

For the offline fallback:

```bash
ollama pull qwen2.5:7b       # multilingual, runs on a laptop
```

```
LLM_PROVIDER=gemini          # gemini | ollama
GEMINI_API_KEY=
OLLAMA_MODEL=qwen2.5:7b
```

`connectplus-rag` reads its own `.env` for the Supabase connection, so there is nothing to configure here for it.

## Run

One process. `connectplus-rag` runs inside it; the knowledge base must already be ingested.

```bash
uvicorn llm.s10_answer:app --reload --port 8000
```

```bash
curl -N -X POST localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"query":"我收到一条奇怪的短信","lang":"zh"}'
```

Streams the answer, then a final event carrying citations, confidence, chunk ids and the verdict.

Single question from the CLI, no server:

```bash
python -m llm.main "my phone keeps asking for a code" --lang zh
```

## Eval

The eval harness is what turns "we built RAG" into "we can show it works" in the report.

```bash
python -m llm.eval          # prints the scored table
```

Scores ~20 fixed questions on hit@3, groundedness, citation validity, readability grade and refusal correctness. **Re-run it on every prompt, translation or chunking change**, including changes made in `connectplus-rag`. It's the only signal that says whether a change helped.

Write the question set before the prompts. Cheap, and it stops the prompts being tuned to whatever was tried last.

## Verifying

- **07.** Ten vague real-world phrasings, in Mandarin, each produce a rewritten query that retrieves the right English page.
- **08.** A poisoned fixture chunk fails to steer the output.
- **09.** The same question answers on both providers; the answer contains no fact absent from the supplied chunks.
- **10.** A refusal verdict renders as a plain sentence plus a mentor offer, streamed, with no error surfaced to the user.

Then by hand, the behaviour that matters most:

```
Ask something the knowledge base can't cover
  → "I don't have trusted information on that" + a mentor offer
  → not a plausible invention
```

Check the citation links in a real answer resolve to live pages on approved domains.

## Status

Prototype for CW2 (Digital Literacy Platform for CALD Seniors). Runs locally; no deployment or CI in scope.

Stages 07-10 develop against `fixtures/f06_retrieved.json` and a stubbed verifier from day one, so they are not blocked on the crawl or the client's domain list.
