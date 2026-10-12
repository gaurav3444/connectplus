"""Shared fixtures. Every test runs against the mock provider so the suite
needs no API key, no network and no GPU."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("LLM_PROVIDER", "mock")

from llm.providers import MockProvider  # noqa: E402
from llm.rag_stub import corpus, poisoned_chunk  # noqa: E402


@pytest.fixture
def provider():
    return MockProvider()


@pytest.fixture
def chunks():
    return corpus()[:3]


@pytest.fixture
def poison():
    return poisoned_chunk()
