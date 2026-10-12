"""Provider interface.

One method, deliberately. The README's rule is that swapping Gemini for Ollama
must be an environment variable and never a code change; the way to keep that
true is to give the wrapper so little surface that nothing provider-specific
can leak into the stages above it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator

__all__ = ["Provider", "ProviderError"]


class ProviderError(RuntimeError):
    """Raised when a provider cannot produce a completion.

    Callers are expected to catch this and degrade - to the offline provider,
    or to the refusal path - rather than surfacing a stack trace to a senior.
    """


class Provider(ABC):
    """A text generator."""

    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, *, temperature: float = 0.2,
                 max_tokens: int = 1024) -> str:
        """Return the full completion for ``prompt``."""

    def stream(self, prompt: str, *, temperature: float = 0.2,
               max_tokens: int = 1024) -> Iterator[str]:
        """Yield the completion in pieces.

        The default implementation completes first and yields once. Providers
        with real streaming override it; stage 10 can then treat every provider
        as streaming without caring which is which.
        """
        yield self.complete(prompt, temperature=temperature, max_tokens=max_tokens)

    def healthy(self) -> bool:
        """Cheap reachability check used to pick the fallback."""
        return True
