"""Readability proxy for Traditional Chinese.

Re-exports :mod:`llm.zh.readability` unchanged. The proxy is built on
characters-per-sentence, long-sentence rate, Latin content rate and
formal-register rate -- none of which depend on which Chinese script
the characters happen to be. See :mod:`llm.zh_hant` for why this is a
re-export rather than a copy.
"""

from __future__ import annotations

from ..zh.readability import score, Readability

__all__ = ["score", "Readability"]
