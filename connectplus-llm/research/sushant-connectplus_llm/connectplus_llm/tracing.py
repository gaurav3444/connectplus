"""One JSONL row per LLM call, so a bad query rewrite traces back to the
exact provider, prompt version, and latency that produced it."""

from __future__ import annotations

from .config import TRACE_LOG
from .schemas import LLMTrace


def write_trace(trace: LLMTrace) -> None:
    with open(TRACE_LOG, "a", encoding="utf-8") as f:
        f.write(trace.model_dump_json() + "\n")
