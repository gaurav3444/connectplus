"""Provider selection.

``get_provider()`` is the only thing the stages import. Which model runs is an
environment variable; if that ever requires a code change above this module,
the wrapper is wrong.

Fallback order when ``LLM_PROVIDER`` is unset or its provider will not start:
Gemini (a key is present) -> Ollama (the daemon answers) -> mock. The demo
degrades instead of dying, and every :class:`~llm.schemas.Answer` records which
provider actually served it, so a surprising eval row can be traced to a silent
fallback.
"""

from __future__ import annotations

import os

from .base import Provider, ProviderError
from .gemini import GeminiProvider
from .mock import MockProvider
from .ollama import OllamaProvider

__all__ = ["Provider", "ProviderError", "get_provider",
           "GeminiProvider", "OllamaProvider", "MockProvider"]

_REGISTRY = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "mock": MockProvider,
}


def get_provider(name: str | None = None, *, strict: bool = False) -> Provider:
    """Build a provider.

    Args:
        name: ``gemini``, ``ollama`` or ``mock``. Defaults to ``$LLM_PROVIDER``.
        strict: When True, raise instead of falling back. The eval harness sets
            this - silently scoring the mock while the row says "gemini" would
            make the whole comparison worthless.

    Returns:
        A ready :class:`Provider`.

    Raises:
        ProviderError: If ``strict`` and the requested provider is unusable.
    """
    requested = (name or os.getenv("LLM_PROVIDER") or "").strip().lower()

    if requested:
        if requested not in _REGISTRY:
            raise ProviderError(
                f"Unknown provider {requested!r}. Choose one of: "
                f"{', '.join(_REGISTRY)}."
            )
        try:
            provider = _REGISTRY[requested]()
            if strict and not provider.healthy():
                raise ProviderError(
                    f"Provider {requested!r} is configured but not reachable."
                )
            return provider
        except ProviderError:
            if strict:
                raise

    # Auto-selection.
    if os.getenv("GEMINI_API_KEY"):
        try:
            return GeminiProvider()
        except ProviderError:
            pass
    ollama = OllamaProvider()
    if ollama.healthy():
        return ollama
    return MockProvider()
