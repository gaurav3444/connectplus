"""Configuration. Everything tunable lives here or in .env, nothing in the prompts."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
PROMPT_DIR = PROJECT_ROOT / "prompts"
FIXTURE_DIR = PROJECT_ROOT / "fixtures"
TRACE_LOG = PROJECT_ROOT / "traces.jsonl"

# .env is optional -- absent, the stub still works with no key and no wifi.
load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).strip().lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    provider: str = os.getenv("LLM_PROVIDER", "stub")
    fallback_provider: str = os.getenv("LLM_FALLBACK", "ollama")
    allow_fallback: bool = _env_bool("LLM_ALLOW_FALLBACK", True)

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")
    gemini_base: str = "https://generativelanguage.googleapis.com/v1beta"

    ollama_model: str = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
    ollama_base: str = os.getenv("OLLAMA_BASE", "http://localhost:11434")

    query_temperature: float = 0.0
    query_max_tokens: int = 200
    query_timeout_s: float = 15.0
    query_prompt_version: str = "query_v1"


settings = Settings()
