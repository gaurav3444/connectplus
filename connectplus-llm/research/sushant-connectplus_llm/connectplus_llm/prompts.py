"""Prompt loading. Prompts are files, not string literals, so an eval run
can name the exact version that produced it."""

from __future__ import annotations

from functools import lru_cache

from .config import PROMPT_DIR
from .schemas import LANGUAGE_NAMES, QueryRequest


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8")


def query_system() -> str:
    return _read("query_system_v1.txt")


def query_user(req: QueryRequest, lang: str) -> str:
    return (
        f"Language of the question: {LANGUAGE_NAMES[lang]}\n"
        f"Question: {req.raw_query}"
    )
