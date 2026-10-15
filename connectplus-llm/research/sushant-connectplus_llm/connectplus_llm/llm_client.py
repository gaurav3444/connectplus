"""
The thin wrapper. One interface, three providers, config swap -- so
"Gemini -> Ollama is a config swap" is true rather than aspirational.

Adapted from the pattern already proven working elsewhere in this project
(stage05/07's llm_client.py), trimmed to what stage 07's query-rewrite call
needs: no chunk_ids, no multi-field schema, just one short JSON call.
"""

from __future__ import annotations

import json
import re
import time
from typing import Protocol, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .config import settings
from .schemas import LLMTrace
from .tracing import write_trace

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    """Raised when a provider fails in a way the caller must handle."""


class QuotaError(LLMError):
    """Provider refused for quota/rate reasons. Triggers fallback."""


# --------------------------------------------------------------------------
# Provider interface
# --------------------------------------------------------------------------

class Provider(Protocol):
    name: str
    model: str

    async def generate(
        self, system: str, user: str, temperature: float,
        max_tokens: int, timeout_s: float,
    ) -> str:
        """Return raw text. Parsing and validation happen in the wrapper."""
        ...


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------

class GeminiProvider:
    name = "gemini"

    def __init__(self) -> None:
        self.model = settings.gemini_model
        if not settings.gemini_api_key:
            raise LLMError("GEMINI_API_KEY is not set")

    async def generate(self, system, user, temperature, max_tokens, timeout_s) -> str:
        url = f"{settings.gemini_base}/models/{self.model}:generateContent"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(
                url, json=payload,
                headers={"x-goog-api-key": settings.gemini_api_key},
            )
        if r.status_code in (429, 503) or r.status_code >= 500:
            raise QuotaError(f"gemini {r.status_code}")
        if r.status_code >= 400:
            raise LLMError(f"gemini {r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"unexpected gemini response shape: {exc}") from exc


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------

class OllamaProvider:
    name = "ollama"

    def __init__(self) -> None:
        self.model = settings.ollama_model

    async def generate(self, system, user, temperature, max_tokens, timeout_s) -> str:
        payload = {
            "model": self.model,
            "system": system,
            "prompt": user,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            r = await client.post(f"{settings.ollama_base}/api/generate", json=payload)
        if r.status_code >= 400:
            raise LLMError(f"ollama {r.status_code}: {r.text[:200]}")
        return r.json().get("response", "")


# --------------------------------------------------------------------------
# Stub
# --------------------------------------------------------------------------

class StubProvider:
    """
    Deterministic, offline, no keys. Lets this code be exercised end to end
    with no wifi. It is NOT a translator -- for English input it does naive
    keyword extraction; for non-English input with no real model, there is
    nothing honest to rewrite with, so it returns a generic fallback query
    rather than pretending to translate. Never treat stub output as a real
    result -- it exists to prove the plumbing works, not to produce answers.
    """

    name = "stub"
    model = "stub-v1"

    _STOPWORDS = {
        "a", "an", "the", "is", "it", "my", "me", "i", "to", "do", "how",
        "what", "why", "on", "in", "of", "and", "or", "for", "with",
        "keeps", "get", "got", "can", "cant", "does", "this", "that",
        "you", "your", "am", "was",
    }

    async def generate(self, system, user, temperature, max_tokens, timeout_s) -> str:
        # `user` is the rendered prompt; the raw query is the last non-empty line.
        raw_query = [ln for ln in user.splitlines() if ln.strip()][-1]
        raw_query = raw_query.split(":", 1)[-1].strip()

        tokens = [
            t for t in re.findall(r"[a-z']+", raw_query.lower())
            if t not in self._STOPWORDS and len(t) > 2
        ]
        query = " ".join(tokens)[:120] or "digital literacy help getting started"
        return json.dumps({"query_rewritten": query})


def build_provider(name: str) -> Provider:
    match name:
        case "gemini":
            return GeminiProvider()
        case "ollama":
            return OllamaProvider()
        case "stub":
            return StubProvider()
        case _:
            raise LLMError(f"unknown provider: {name}")


# --------------------------------------------------------------------------
# JSON extraction
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def extract_json(text: str) -> dict:
    """Models emit fences and prose despite being told not to. Strip, then
    take the outermost object."""
    cleaned = _FENCE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMError(f"no JSON object in output: {cleaned[:200]}")
    return json.loads(cleaned[start : end + 1])


# --------------------------------------------------------------------------
# The wrapper
# --------------------------------------------------------------------------

class LLM:
    """Calls a provider, validates against a schema, repairs once, falls
    back once. No refine loop -- a model checking its own work is not a
    guardrail, it is the same model that made the mistake, asked nicely."""

    def __init__(self, provider: Provider | None = None) -> None:
        self.primary = provider or build_provider(settings.provider)
        self._fallback: Provider | None = None

    def _get_fallback(self) -> Provider | None:
        if not settings.allow_fallback:
            return None
        if self._fallback is None:
            try:
                self._fallback = build_provider(settings.fallback_provider)
            except LLMError:
                return None
        return self._fallback

    async def complete(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        temperature: float,
        max_tokens: int,
        timeout_s: float,
        stage: str,
        prompt_version: str,
    ) -> T:
        started = time.perf_counter()
        provider = self.primary
        fell_back = False
        repaired = False
        last_error: Exception | None = None

        for attempt in range(2):  # attempt 0 = primary, attempt 1 = fallback
            try:
                raw = await provider.generate(system, user, temperature, max_tokens, timeout_s)
                try:
                    obj = schema.model_validate(extract_json(raw))
                except (ValidationError, LLMError, json.JSONDecodeError) as exc:
                    repaired = True
                    repair_user = (
                        f"{user}\n\n"
                        f"Your previous output was rejected: {str(exc)[:300]}\n"
                        f"Return only valid JSON matching the schema. "
                        f"No prose, no markdown fences."
                    )
                    raw = await provider.generate(system, repair_user, 0.0, max_tokens, timeout_s)
                    obj = schema.model_validate(extract_json(raw))

                self._trace(stage, provider, prompt_version, started, repaired, fell_back, True, None)
                return obj

            except (QuotaError, httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                fb = self._get_fallback()
                if attempt == 0 and fb is not None:
                    provider, fell_back = fb, True
                    continue
                break
            except (LLMError, ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                break

        self._trace(stage, provider, prompt_version, started, repaired, fell_back, False, str(last_error))
        raise LLMError(f"stage {stage} failed: {last_error}")

    @staticmethod
    def _trace(stage, provider, version, started, repaired, fell_back, ok, error) -> None:
        write_trace(LLMTrace(
            stage=stage,
            provider=provider.name,
            model=provider.model,
            prompt_version=version,
            latency_ms=int((time.perf_counter() - started) * 1000),
            repaired=repaired,
            fell_back=fell_back,
            ok=ok,
            error=error,
        ))
