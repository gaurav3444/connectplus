"""Stage 06 - Query Understanding (this repo's file numbering; the unified
whole-project stage map calls this "stage 05" and calls this repo's
s05_retrieve "stage 06" - see README's mapping table. File numbers here are
build order, the stage map's are pipeline order, and they cross over at 05).

Detects the user's language and turns a vague goal into something
retrievable. The stage map's own example: "my phone keeps asking for a
code" -> "two-factor authentication". Plus light term expansion.

    IN   {query, lang?}
    OUT  {original, lang, rewritten, expansions[]}

Design decisions made explicit here:

- This stage lives in THIS repo, not connectplus-llm, by team decision -
  both READMEs originally assigned query understanding to the LLM side.
  Worth knowing because it means this repo now talks to an LLM, which it
  previously did not.
- No LLM SDK dependency. Gemini and Ollama are each a single HTTP POST,
  and httpx is already a dependency (stage 01 uses it). Adding
  google-generativeai to make one JSON request would be the wrong trade.
  LLMFunction below is the "one interface, selected by env var" the stage
  map's generation card asks for, and stage 07 can reuse the same type.
- llm_fn is injectable, exactly like every other stage's external
  dependency in this repo (stage 03's token counter, stage 04's embedder
  and upserter, stage 05's searches). The parsing, fallback and
  normalisation logic is fully tested with no network and no API key; the
  two real provider adapters are thin enough to read in one screen and are
  untested by me, same honest caveat as those other stages carry.
- `rewritten` is ALWAYS English. Not a stylistic choice - keyword search
  runs on an 'english' tsvector, so a Mandarin query matches literally
  nothing and hybrid retrieval silently degrades to vector-only. This
  stage is what makes the keyword half work for a CALD senior at all. The
  original language survives in `lang` so the generator still answers in it.
- An explicitly passed `lang` always beats detection. The stage map's own
  contract is {query, lang?} - the frontend knows which language the
  senior chose, and that is far more trustworthy than langdetect run over
  a six-word question.
- Every failure path degrades to passthrough, never raises. A dead LLM, a
  timeout, prose instead of JSON, a missing key - all return the original
  query as its own rewrite. Retrieval still runs. This stage improves
  retrieval; it must never be able to break it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Callable

import httpx

from rag.lang import detect_lang
from rag.schemas import UnderstoodQuery

logger = logging.getLogger("rag.query")

# prompt -> raw completion text. The whole LLM interface, deliberately.
LLMFunction = Callable[[str], str]

PROMPT_VERSION = "query-understanding-v1"

MAX_EXPANSIONS = 3
LLM_TIMEOUT_SECONDS = 20.0

PROMPT_TEMPLATE = """You rewrite questions from older adults into search queries for a \
digital-literacy help desk. The searchable material is Australian government pages about \
online safety, scams, myGov, and using phones and computers.

Rewrite the question below into a short English search query.

Rules:
- Answer in English, even when the question is in another language.
- Replace vague description with the real term. "my phone keeps asking for a code" \
becomes "two-factor authentication".
- Search keywords, not a sentence. No question mark, no "how do I".
- Add up to {max_expansions} extra English terms that a page about this might use instead.
- Do not answer the question. Only rewrite it.

Question: {query}

Reply with only this JSON object and nothing else:
{{"rewritten": "...", "expansions": ["...", "..."]}}"""


def get_default_llm() -> LLMFunction:
    """The real LLM, chosen by the LLM_PROVIDER env var - "swapping must be
    config, never code", per the stage map's generation card.

    Untested by me: this sandbox has no API key and no local Ollama, so
    tests inject a fake llm_fn instead (see tests/test_s06_query.py). Same
    situation as stage 04's embedder and stage 05's database functions.
    """
    provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if provider == "ollama":
        return _ollama_llm()
    if provider == "gemini":
        return _gemini_llm()
    raise ValueError(f"Unknown LLM_PROVIDER {provider!r} - expected 'gemini' or 'ollama'.")


def _gemini_llm() -> LLMFunction:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set - see .env.example.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def call(prompt: str) -> str:
        response = httpx.post(
            url,
            headers={"x-goog-api-key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]

    return call


def _ollama_llm() -> LLMFunction:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.1")

    def call(prompt: str) -> str:
        response = httpx.post(
            f"{host}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["response"]

    return call


def _strip_code_fence(text: str) -> str:
    """Unwraps ```json ... ``` if present.

    Not defensive programming for its own sake: models asked for "only
    JSON" routinely wrap it in a fence anyway, and that single detail is
    the difference between this stage working and it falling back to
    passthrough on every call while still looking healthy.
    """
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    return (fenced.group(1) if fenced else text).strip()


def _parse_llm_reply(reply: str) -> tuple[str, list[str]]:
    """(rewritten, expansions) from the model's raw text.

    Raises on anything unusable, so understand() has exactly one place to
    catch and fall back rather than handling each failure shape separately
    at the call site.
    """
    payload = json.loads(_strip_code_fence(reply))
    rewritten = str(payload["rewritten"]).strip()
    if not rewritten:
        raise ValueError("LLM returned an empty 'rewritten'")

    raw_expansions = payload.get("expansions") or []
    if isinstance(raw_expansions, str):  # a real shape models produce: "a, b, c"
        raw_expansions = raw_expansions.split(",")

    seen: set[str] = set()
    expansions: list[str] = []
    for term in raw_expansions:
        cleaned = str(term).strip()
        key = cleaned.lower()
        # Drop terms already inside `rewritten` - repeating them adds no
        # lexical recall and just pads the keyword query.
        if not cleaned or key in seen or key in rewritten.lower():
            continue
        seen.add(key)
        expansions.append(cleaned)
        if len(expansions) == MAX_EXPANSIONS:
            break

    return rewritten, expansions


def understand(
    query: str,
    lang: str | None = None,
    llm_fn: LLMFunction | None = None,
) -> UnderstoodQuery:
    """Turns a raw question into an UnderstoodQuery. Never raises.

    `lang`, when supplied, is taken as authoritative and no detection runs
    - see the module docstring. llm_fn defaults to get_default_llm(),
    resolved lazily so importing this module never requires an API key.

    Pass `rewritten` to retrieve() as its `query`, and
    keyword_query_for(result) as its `keyword_query`.
    """
    resolved_lang = lang or "unknown"

    if not query.strip():
        return UnderstoodQuery(original=query, lang=resolved_lang, rewritten=query)

    if lang is None:
        resolved_lang = detect_lang(query)

    try:
        llm_fn = llm_fn or get_default_llm()
        reply = llm_fn(PROMPT_TEMPLATE.format(query=query, max_expansions=MAX_EXPANSIONS))
        rewritten, expansions = _parse_llm_reply(reply)
    except Exception as exc:
        # Deliberately broad. Everything from "no API key" to "the model
        # replied in prose" lands here, and the correct response to all of
        # it is identical: search for what the user actually typed. A worse
        # query still retrieves; an exception here would take down the
        # whole answer path over an optional enhancement.
        logger.warning(
            "query understanding fell back to passthrough: %s: %s", type(exc).__name__, exc
        )
        return UnderstoodQuery(original=query, lang=resolved_lang, rewritten=query)

    return UnderstoodQuery(
        original=query,
        lang=resolved_lang,
        rewritten=rewritten,
        expansions=expansions,
        prompt_version=PROMPT_VERSION,
    )


def keyword_query_for(understood: UnderstoodQuery) -> str:
    """The string to hand retrieve() as keyword_query: the English rewrite
    plus its expansion terms. One function so the CLI, the eval harness and
    connectplus-llm cannot each assemble it slightly differently.
    """
    return " ".join([understood.rewritten, *understood.expansions])
