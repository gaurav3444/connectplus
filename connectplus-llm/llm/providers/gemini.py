"""Gemini provider, async, over the REST API.

Uses ``httpx.AsyncClient`` against ``generativelanguage.googleapis.com``
rather than the ``google-generativeai`` SDK. The SDK's surface has changed
shape several times; the REST contract has not, and one ``POST`` is easier
for a reader to follow than an SDK dance.

Two things carried over from the version of this that has real traffic
behind it (57 live calls, zero malformed responses):

* **Structured output.** ``responseMimeType: application/json`` plus a
  declared schema, so the rewrite call returns a typed object instead of
  prose that has to be cleaned up with regular expressions.
* **Low ``topP``.** Safety-critical instructions should not be rephrased
  creatively between runs, and the eval needs the same question to score the
  same way twice.

The key is read from the environment and never leaves this process. It is not
passed to the frontend, not logged, and not included in any traced payload.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import AsyncIterator

import httpx

from .base import Provider, ProviderError, QuotaError

__all__ = ["GeminiProvider"]

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"

# Free-tier rate limits are a normal operating condition here, not an
# error. Wait and retry before giving up on the call.
_MAX_RETRIES = 4
_BACKOFF = (2.0, 6.0, 15.0, 30.0)

# The rewrite call's contract. Declaring it to the provider is what lets the
# caller drop most of its output-validation rules.
_REWRITE_SCHEMA = {
    "type": "object",
    "properties": {"query_rewritten": {"type": "string"}},
    "required": ["query_rewritten"],
}


class GeminiProvider(Provider):
    """Google Gemini, free tier."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: float = 60.0) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        if not self.api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add "
                "a key from https://aistudio.google.com/apikey, or set "
                "LLM_PROVIDER=ollama or LLM_PROVIDER=mock."
            )

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    # Only ya29. is reliably an OAuth access token. Everything else Google
    # hands out of AI Studio is an API key, and API keys go in the header
    # below -- including the newer AQ.… format, which an earlier version of
    # this file wrongly treated as OAuth and sent as a bearer token. That
    # produced a flat 401 on a perfectly good key.
    #
    # The lesson is in the default: assume API key, and special-case only
    # the prefix we are certain about. Guessing "not the format I know"
    # means OAuth is how you break every future key format Google ships.
    _OAUTH_PREFIXES = ("ya29.",)

    def _headers(self) -> dict:
        """Pick the auth scheme for the credential we were given.

        * **API key** -- ``x-goog-api-key``. Covers ``AIzaSy…`` and the
          newer ``AQ.…`` keys. Does not expire. This is the default.
        * **OAuth access token** (``ya29.…``) -- ``Authorization: Bearer``.
          Short-lived; some setups also need the billing project named,
          hence ``GOOGLE_CLOUD_PROJECT``.
        """
        headers = {"content-type": "application/json"}
        if self.uses_oauth:
            headers["Authorization"] = f"Bearer {self.api_key}"
            project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
            if project:
                headers["x-goog-user-project"] = project
        else:
            headers["x-goog-api-key"] = self.api_key
        return headers

    @property
    def uses_oauth(self) -> bool:
        """True only for credentials we are sure are short-lived tokens."""
        return self.api_key.startswith(self._OAUTH_PREFIXES)

    def _payload(self, prompt: str, temperature: float, max_tokens: int,
                 json_object: bool) -> dict:
        config: dict = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "topP": 0.8,
        }
        if json_object:
            config["responseMimeType"] = "application/json"
            config["responseSchema"] = _REWRITE_SCHEMA
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }

    @staticmethod
    def _raise_for_status(r: httpx.Response) -> None:
        if r.status_code == 429:
            raise QuotaError(
                "Gemini free-tier quota exhausted. Set LLM_PROVIDER=ollama."
            )
        if r.status_code in (500, 502, 503, 504):
            raise QuotaError(f"Gemini unavailable ({r.status_code}).")
        if r.status_code >= 400:
            raise ProviderError(f"Gemini returned {r.status_code}: {r.text[:300]}")

    async def complete(self, prompt: str, *, temperature: float = 0.2,
                       max_tokens: int = 1024,
                       json_object: bool = False) -> str:
        """Complete, retrying through the free tier's per-minute limit.

        The free tier allows only a handful of requests per minute. An eval
        run fires dozens back to back, so 429s are expected rather than
        exceptional -- in the first real run, 49 of 134 calls were rate
        limited, every one of them surfaced as a refusal, and the results
        table read like a content problem instead of a throughput one.

        Waiting is the correct response to a per-minute cap: the quota
        refills on its own. Only after the retries are exhausted does this
        become a QuotaError, which is what hands the call to the offline
        provider.
        """
        url = f"{_BASE}/{self.model}:generateContent"
        payload = self._payload(prompt, temperature, max_tokens, json_object)

        last: Exception | None = None
        r: httpx.Response | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                r = await self._http().post(url, headers=self._headers(),
                                            json=payload)
            except httpx.HTTPError as exc:
                # Network error on every attempt leaves no response to
                # inspect, so the loop must not fall through to one.
                last = QuotaError(f"Gemini request failed: {exc}")
                r = None
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_BACKOFF[attempt])
                continue

            if r.status_code == 429 or r.status_code in (500, 502, 503, 504):
                last = QuotaError(f"Gemini returned {r.status_code}")
                if attempt < _MAX_RETRIES - 1:
                    # Honour Retry-After when the API sends one.
                    wait = _BACKOFF[attempt]
                    header = r.headers.get("retry-after")
                    if header and header.isdigit():
                        wait = max(wait, min(int(header), 60))
                    await asyncio.sleep(wait)
                    continue
            break

        if r is None:
            raise last or QuotaError("Gemini unreachable.")
        self._raise_for_status(r)

        data = r.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError) as exc:
            # A blocked or empty candidate lands here. Surfacing the raw body
            # matters: a safety filter and an exhausted quota look identical
            # otherwise, and they need different responses.
            raise ProviderError(
                f"Gemini returned no usable candidate: {json.dumps(data)[:300]}"
            ) from exc

    async def stream(self, prompt: str, *, temperature: float = 0.2,
                     max_tokens: int = 1024) -> AsyncIterator[str]:
        url = f"{_BASE}/{self.model}:streamGenerateContent?alt=sse"
        try:
            async with self._http().stream(
                "POST", url, headers=self._headers(),
                json=self._payload(prompt, temperature, max_tokens, False),
            ) as r:
                if r.status_code >= 400:
                    await r.aread()
                    self._raise_for_status(r)
                async for line in r.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    try:
                        chunk = json.loads(body)
                        parts = chunk["candidates"][0]["content"]["parts"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    text = "".join(p.get("text", "") for p in parts)
                    if text:
                        yield text
        except httpx.HTTPError as exc:
            raise QuotaError(f"Gemini stream failed: {exc}") from exc

    async def healthy(self) -> bool:
        try:
            r = await self._http().get(_BASE, headers=self._headers(), timeout=10.0)
            return r.status_code < 400
        except httpx.HTTPError:
            return False
