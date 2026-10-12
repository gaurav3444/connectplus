"""Ollama provider, async. The offline fallback.

Why it exists: the demo has to survive a dead quota or no wifi. The Gemini
free tier is the primary provider precisely because it is free, and free
tiers run out -- in the traces this design came from, the Gemini-to-Ollama
fallback fired three times in sixty calls and the pipeline kept going.

One finding worth carrying into the report rather than hiding: ``qwen2.5:7b``
is multilingual and runs on a laptop, but its Chinese is noticeably stronger
than its Vietnamese. If the Vietnamese lane scores badly on the offline
provider, that tells us demo day needs a different local model -- it is a
result, not a defect.
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator

import httpx

from .base import Provider, ProviderError, QuotaError

__all__ = ["OllamaProvider"]


class OllamaProvider(Provider):
    """A local model served by ``ollama serve``."""

    name = "ollama"

    def __init__(self, host: str | None = None, model: str | None = None,
                 timeout: float = 180.0) -> None:
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def _body(self, prompt: str, temperature: float, max_tokens: int,
              stream: bool, json_object: bool) -> dict:
        body = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {"temperature": temperature,
                        "num_predict": max_tokens,
                        "top_p": 0.8},
        }
        if json_object:
            # Ollama's own structured-output switch. Same purpose as
            # Gemini's responseMimeType: a typed result instead of prose.
            body["format"] = "json"
        return body

    async def complete(self, prompt: str, *, temperature: float = 0.2,
                       max_tokens: int = 1024,
                       json_object: bool = False) -> str:
        try:
            r = await self._http().post(
                f"{self.host}/api/generate",
                json=self._body(prompt, temperature, max_tokens, False, json_object),
            )
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Ollama unreachable at {self.host}. Is `ollama serve` running? ({exc})"
            ) from exc
        if r.status_code >= 400:
            raise ProviderError(f"Ollama returned {r.status_code}: {r.text[:300]}")
        return (r.json().get("response") or "").strip()

    async def stream(self, prompt: str, *, temperature: float = 0.2,
                     max_tokens: int = 1024) -> AsyncIterator[str]:
        try:
            async with self._http().stream(
                "POST", f"{self.host}/api/generate",
                json=self._body(prompt, temperature, max_tokens, True, False),
            ) as r:
                if r.status_code >= 400:
                    await r.aread()
                    raise ProviderError(
                        f"Ollama stream returned {r.status_code}: {r.text[:300]}")
                async for line in r.aiter_lines():
                    if not line:
                        continue
                    try:
                        piece = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if piece.get("response"):
                        yield piece["response"]
                    if piece.get("done"):
                        break
        except httpx.HTTPError as exc:
            raise ProviderError(f"Ollama stream failed: {exc}") from exc

    async def healthy(self) -> bool:
        try:
            r = await self._http().get(f"{self.host}/api/tags", timeout=5.0)
            return r.status_code < 400
        except httpx.HTTPError:
            return False
