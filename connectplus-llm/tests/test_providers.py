"""Provider wrapper and selection."""

import pytest

from llm.providers import (MockProvider, ProviderError, get_provider)


def test_unknown_provider_is_rejected_by_name():
    with pytest.raises(ProviderError, match="Unknown provider"):
        get_provider("gpt5")


def test_gemini_without_a_key_fails_loudly_in_strict_mode(monkeypatch):
    """The eval sets strict=True. Silently scoring the mock while the report
    says 'gemini' would make the whole provider comparison worthless."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        get_provider("gemini", strict=True)


def test_auto_selection_reaches_the_mock_when_nothing_else_is_available(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:1")  # nothing listening
    assert get_provider().name == "mock"


def test_mock_is_deterministic(chunks):
    """The eval compares runs. A provider that answers differently each time
    makes every comparison noise."""
    from llm.s08_prompt import build_answer_prompt
    p = build_answer_prompt(chunks, query_original="q", query_rewritten="q")
    m = MockProvider()
    assert m.complete(p.text) == m.complete(p.text)


def test_stream_default_yields_the_completion(chunks):
    from llm.s08_prompt import build_answer_prompt
    p = build_answer_prompt(chunks, query_original="q", query_rewritten="q")
    m = MockProvider()
    assert "".join(m.stream(p.text)) == m.complete(p.text)


def test_mock_answer_uses_correct_register(chunks):
    from llm.s08_prompt import build_answer_prompt
    from llm.vi.termbase import audit
    p = build_answer_prompt(chunks, query_original="q", query_rewritten="q")
    assert not [v for v in audit(MockProvider().complete(p.text))
                if v.kind == "address"]
