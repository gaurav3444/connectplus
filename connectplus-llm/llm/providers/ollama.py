"""Ollama provider - the offline fallback.

Exists so the CW2 demo survives a dead Gemini quota or no wifi in the room.

A caution worth carrying into the report: ``qwen2.5:7b`` is the README's
suggested local model and its Chinese is much stronger than its Vietnamese. The
fallback path must therefore be evaluated in Vietnamese specifically rather than
assumed to behave like the primary. That is what ``llm.eval --provider ollama``
is for, and a poor score there is a finding, not a defect to hide.
"""

from __future__ import annotations

import json
import os
from typing import Iterator

import requests

from .base import Provider, ProviderError

__all__ = ["OllamaProvider"]


class OllamaProvider(Provider):
    """A model served by a local Ollama daemon."""

    name = "ollama"

    def __init__(self, host: str | None = None, model: str | None = None,
                 timeout: int = 180) -> None:
        self.host = (host or os.getenv("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.timeout = timeout

    def _options(self, temperature: float, max_tokens: int) -> dict:
        return {"temperature": temperature, "num_predict": max_tokens, "top_p": 0.8}

    def complete(self, prompt: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024) -> str:
        try:
            r = requests.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False,
                      "options": self._options(temperature, max_tokens)},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError(
                f"Ollama unreachable at {self.host}. Is `ollama serve` running? ({exc})"
            ) from exc
        if r.status_code >= 400:
            raise ProviderError(f"Ollama returned {r.status_code}: {r.text[:300]}")
        return (r.json().get("response") or "").strip()

    def stream(self, prompt: str, *, temperature: float = 0.2,
               max_tokens: int = 1024) -> Iterator[str]:
        try:
            with requests.post(
                f"{self.host}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": True,
                      "options": self._options(temperature, max_tokens)},
                timeout=self.timeout,
                stream=True,
            ) as r:
                if r.status_code >= 400:
                    raise ProviderError(
                        f"Ollama stream returned {r.status_code}: {r.text[:300]}")
                for line in r.iter_lines(decode_unicode=True):
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
        except requests.RequestException as exc:
            raise ProviderError(f"Ollama stream failed: {exc}") from exc

    def healthy(self) -> bool:
        try:
            return requests.get(f"{self.host}/api/tags", timeout=5).status_code < 400
        except requests.RequestException:
            return False
