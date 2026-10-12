"""One append-only line per provider call.

Why this exists: it is the only thing in the project that can answer "did
that number come from a real model or from the stub?" after the fact. Every
row carries the provider, the model, the prompt version and the latency, so
an eval table can be audited rather than trusted.

Never write the prompt, the answer or the API key here. This file is meant
to be safe to paste into a report.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .schemas import LLMTrace

__all__ = ["write_trace", "trace_path", "read_traces", "summarise"]

_LOCK = threading.Lock()


def trace_path() -> Path:
    """Where traces are appended. Override with ``$TRACE_FILE``."""
    return Path(os.getenv("TRACE_FILE",
                          Path(__file__).resolve().parent.parent / "traces.jsonl"))


def write_trace(trace: LLMTrace) -> None:
    """Append one row. Never raises -- tracing must not break a request."""
    try:
        row = trace.as_dict()
        row["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = trace_path()
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_traces(limit: int | None = None) -> list[dict]:
    """Read traces back, newest last."""
    path = trace_path()
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:] if limit else rows


def summarise(rows: list[dict] | None = None) -> dict:
    """Counts and latencies by provider, for the report and the demo panel."""
    rows = read_traces() if rows is None else rows
    by: dict[str, dict] = {}
    for r in rows:
        key = f"{r.get('provider')}/{r.get('model')}"
        slot = by.setdefault(key, {"calls": 0, "ok": 0, "fell_back": 0,
                                   "latency_ms": []})
        slot["calls"] += 1
        slot["ok"] += bool(r.get("ok"))
        slot["fell_back"] += bool(r.get("fell_back"))
        if r.get("latency_ms"):
            slot["latency_ms"].append(r["latency_ms"])
    for slot in by.values():
        lat = slot.pop("latency_ms")
        slot["mean_latency_ms"] = round(sum(lat) / len(lat)) if lat else 0
    return {"total": len(rows), "by_provider": by}
