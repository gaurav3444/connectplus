"""Provider interface.

**Async by design, and that is not a style preference.** Stage 10 is FastAPI
with SSE streaming. A synchronous HTTP client inside an async endpoint blocks
the event loop for the whole generation -- every concurrent senior waits
behind one Gemini call -- unless every call is pushed through a threadpool.
``httpx.AsyncClient`` is the correct shape for the server this project is
actually building, so the interface is async all the way down.

Deliberately small surface: the README's rule is that swapping Gemini for
Ollama must be an environment variable and never a code change, and the way
to keep that true is to give the wrapper so little surface that nothing
provider-specific can leak into the stages above it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

__all__ = ["Provider", "ProviderError", "QuotaError"]


class ProviderError(RuntimeError):
    """A provider could not produce a completion.

    Callers are expected to catch this and degrade -- to the offline
    provider, or to the refusal path -- rather than surfacing a stack trace
    to a senior.
    """


class QuotaError(ProviderError):
    """Refused for quota or rate reasons. Triggers the fallback provider."""


class Provider(ABC):
    """A text generator."""

    name: str = "base"
    model: str = ""

    @abstractmethod
    async def complete(self, prompt: str, *, temperature: float = 0.2,
                       max_tokens: int = 1024,
                       json_object: bool = False) -> str:
        """Return the full completion.

        Args:
            prompt: The rendered prompt.
            temperature: Kept low by callers. Safety-critical instructions
                should read the same way twice, and the eval needs
                reproducibility.
            max_tokens: Output cap.
            json_object: Ask the provider for a JSON object rather than
                prose. Used by the query-rewrite call, where a typed result
                removes a whole class of output-cleaning rules.
        """

    async def stream(self, prompt: str, *, temperature: float = 0.2,
                     max_tokens: int = 1024) -> AsyncIterator[str]:
        """Yield the completion in pieces.

        The default completes first and yields once. Providers with real
        streaming override it, so stage 10 can treat every provider as
        streaming without caring which is which.
        """
        yield await self.complete(prompt, temperature=temperature,
                                  max_tokens=max_tokens)

    async def healthy(self) -> bool:
        """Cheap reachability check, used to pick the fallback."""
        return True

    async def aclose(self) -> None:
        """Release any held connections."""
        return None
