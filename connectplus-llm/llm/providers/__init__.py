"""Provider selection and the fallback chain.

``get_provider()`` is the only thing the stages import. Which model runs is
an environment variable; if that ever requires a code change above this
module, the wrapper is wrong.

Fallback order when ``LLM_PROVIDER`` is unset or the named provider will not
start: Gemini (a key is present) then Ollama (the daemon answers) then mock.
The demo degrades instead of dying, and every answer records which provider
actually served it, so a surprising eval row traces back to a silent
fallback rather than to a mystery.
"""

from __future__ import annotations

import os

from .base import Provider, ProviderError, QuotaError
from .gemini import GeminiProvider
from .mock import MockProvider
from .ollama import OllamaProvider

__all__ = ["Provider", "ProviderError", "QuotaError", "get_provider",
           "GeminiProvider", "OllamaProvider", "MockProvider",
           "FallbackProvider"]

_REGISTRY = {
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "mock": MockProvider,
    "stub": MockProvider,
}


class FallbackProvider(Provider):
    """Primary provider with a standby behind it.

    Wraps two providers so a quota failure mid-answer is a degraded answer
    rather than a refusal. ``name`` reports whichever one actually served
    the last call, so the trace never claims Gemini for an Ollama answer.
    """

    def __init__(self, primary: Provider, standby: Provider) -> None:
        self.primary = primary
        self.standby = standby
        self.name = primary.name
        self.model = primary.model
        self.fell_back = False

    def _use(self, provider: Provider, fell_back: bool) -> None:
        self.name = provider.name
        self.model = provider.model
        self.fell_back = fell_back

    async def complete(self, prompt: str, *, temperature: float = 0.2,
                       max_tokens: int = 1024,
                       json_object: bool = False) -> str:
        try:
            out = await self.primary.complete(
                prompt, temperature=temperature, max_tokens=max_tokens,
                json_object=json_object)
            self._use(self.primary, False)
            return out
        except QuotaError:
            out = await self.standby.complete(
                prompt, temperature=temperature, max_tokens=max_tokens,
                json_object=json_object)
            self._use(self.standby, True)
            return out

    async def stream(self, prompt: str, *, temperature: float = 0.2,
                     max_tokens: int = 1024):
        try:
            async for piece in self.primary.stream(
                    prompt, temperature=temperature, max_tokens=max_tokens):
                yield piece
            self._use(self.primary, False)
        except QuotaError:
            async for piece in self.standby.stream(
                    prompt, temperature=temperature, max_tokens=max_tokens):
                yield piece
            self._use(self.standby, True)

    async def healthy(self) -> bool:
        return await self.primary.healthy() or await self.standby.healthy()

    async def aclose(self) -> None:
        await self.primary.aclose()
        await self.standby.aclose()


def get_provider(name: str | None = None, *, strict: bool = False,
                 with_fallback: bool | None = None) -> Provider:
    """Build a provider.

    Args:
        name: ``gemini``, ``ollama`` or ``mock``. Defaults to
            ``$LLM_PROVIDER``.
        strict: Raise instead of falling back. The eval harness sets this --
            silently scoring the mock while the results table says "gemini"
            would make the whole comparison worthless.
        with_fallback: Wrap the provider so a quota failure degrades to the
            standby. Defaults to ``$LLM_ALLOW_FALLBACK`` (on unless set to
            a falsey string).

    Returns:
        A ready :class:`Provider`.

    Raises:
        ProviderError: If ``strict`` and the requested provider is unusable.
    """
    requested = (name or os.getenv("LLM_PROVIDER") or "").strip().lower()
    if with_fallback is None:
        with_fallback = os.getenv("LLM_ALLOW_FALLBACK", "true").lower() not in (
            "false", "0", "no", "off")

    if requested:
        if requested not in _REGISTRY:
            raise ProviderError(
                f"Unknown provider {requested!r}. Choose one of: "
                f"{', '.join(sorted(set(_REGISTRY)))}."
            )
        try:
            provider = _REGISTRY[requested]()
        except ProviderError:
            if strict:
                raise
            provider = None
        if provider is not None:
            if strict or requested in ("mock", "stub"):
                return provider
            return _wrap(provider, with_fallback)

    if strict:
        raise ProviderError("No provider requested and strict mode is on.")

    # Auto-selection.
    if os.getenv("GEMINI_API_KEY"):
        try:
            return _wrap(GeminiProvider(), with_fallback)
        except ProviderError:
            pass
    return MockProvider()


def _wrap(provider: Provider, with_fallback: bool) -> Provider:
    """Put the offline provider behind a network one."""
    if not with_fallback or provider.name in ("mock", "ollama"):
        return provider
    standby_name = os.getenv("LLM_FALLBACK", "ollama").strip().lower()
    standby_cls = _REGISTRY.get(standby_name, OllamaProvider)
    try:
        standby: Provider = standby_cls()
    except ProviderError:
        standby = MockProvider()
    return FallbackProvider(provider, standby)
