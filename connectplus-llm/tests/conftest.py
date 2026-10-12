"""Shared test fixtures.

LLM tests (test_pipeline, test_zh_*, test_detect, ...) use `provider`,
`chunks` and `poisoned`. Nothing here touches the network or needs an API key.
RAG's own tests live in connectplus-rag.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm.providers import MockProvider             # noqa: E402
from llm.rag_stub import corpus, poisoned_chunk    # noqa: E402


@pytest.fixture
def provider():
    return MockProvider()


@pytest.fixture
def chunks():
    """Three ordinary passages, in prompt order."""
    return list(corpus()[:3])


@pytest.fixture
def poisoned():
    """A chunk carrying an injection attempt."""
    return poisoned_chunk()


@pytest.fixture(autouse=True)
def _no_trace_file(tmp_path, monkeypatch):
    """Keep test runs out of the real traces.jsonl."""
    monkeypatch.setenv("TRACE_FILE", str(tmp_path / "traces.jsonl"))
