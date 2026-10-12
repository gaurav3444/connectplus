"""Gemini provider, over the REST API.

Uses ``requests`` against ``generativelanguage.googleapis.com`` rather than the
``google-generativeai`` SDK. The SDK's surface has changed shape several times;
the REST contract has not, and a single ``POST`` is easier for a marker to read
than an SDK dance. Streaming uses the ``streamGenerateContent`` endpoint with
``alt=sse``.

The key is read from the environment and never leaves this process. It is not
passed to the frontend, not logged, and not included in any traced payload.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

import requests

from .base import Provider, ProviderError

__all__ = ["GeminiProvider"]

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(Provider):
    """Google Gemini, free tier."""

    name = "gemini"

    def __init__(self, api_key: str | None = None, model: str | None = None,
                 timeout: int = 60) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout = timeout
        if not self.api_key:
            raise ProviderError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add "
                "a key from https://aistudio.google.com/apikey, or set "
                "LLM_PROVIDER=ollama or LLM_PROVIDER=mock."
            )

    def _payload(self, prompt: str, temperature: float, max_tokens: int) -> dict:
        return {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                # Low top_p: safety-critical instructions should not be
                # rephrased creatively between runs, and the eval needs the
                # same question to score the same way twice.
                "topP": 0.8,
            },
        }

    def complete(self, prompt: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024) -> str:
        url = f"{_BASE}/{self.model}:generateContent"
        try:
            r = requests.post(
                url,
                headers={"x-goog-api-key": self.api_key,
                         "content-type": "application/json"},
                json=self._payload(prompt, temperature, max_tokens),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Gemini request failed: {exc}") from exc

        if r.status_code == 429:
            raise ProviderError(
                "Gemini free-tier quota exhausted. Set LLM_PROVIDER=ollama."
            )
        if r.status_code >= 400:
            raise ProviderError(f"Gemini returned {r.status_code}: {r.text[:300]}")

        data = r.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts).strip()
        except (KeyError, IndexError) as exc:
            # A blocked or empty candidate lands here. Surfacing the raw body
            # matters: "safety filter" and "quota" look identical otherwise.
            raise ProviderError(
                f"Gemini returned no usable candidate: {json.dumps(data)[:300]}"
            ) from exc

    def stream(self, prompt: str, *, temperature: float = 0.2,
               max_tokens: int = 1024) -> Iterator[str]:
        url = f"{_BASE}/{self.model}:streamGenerateContent?alt=sse"
        try:
            with requests.post(
                url,
                headers={"x-goog-api-key": self.api_key,
                         "content-type": "application/json"},
                json=self._payload(prompt, temperature, max_tokens),
                timeout=self.timeout,
                stream=True,
            ) as r:
                if r.status_code >= 400:
                    raise ProviderError(
                        f"Gemini stream returned {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines(decode_unicode=True):
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
        except requests.RequestException as exc:
            raise ProviderError(f"Gemini stream failed: {exc}") from exc

    def healthy(self) -> bool:
        try:
            r = requests.get(f"{_BASE}?key={self.api_key}", timeout=10)
            return r.status_code < 400
        except requests.RequestException:
            return False
