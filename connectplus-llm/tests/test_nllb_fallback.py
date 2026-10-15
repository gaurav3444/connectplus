"""Tests for llm.providers.nllb_fallback.

Deliberately limited to the branches that do not touch torch/transformers:
those are lazily imported only inside translate_en_to_zh_hant, so these
tests exercise every condition under which that import must NOT happen,
which is also the only part of this module a machine with no GPU and no
fine-tuned checkpoint can verify. The translation quality itself is not a
software-testable claim and is out of scope here; see the module's own
docstring for where that responsibility sits.
"""

import pytest

from llm.providers.nllb_fallback import maybe_translate_fallback


def test_noop_for_non_zh_hant_lane():
    assert maybe_translate_fallback("Open the app.", lang="zh",
                                    provider_name="mock") == "Open the app."
    assert maybe_translate_fallback("Open the app.", lang="vi",
                                    provider_name="mock") == "Open the app."
    assert maybe_translate_fallback("Open the app.", lang="en",
                                    provider_name="mock") == "Open the app."


def test_noop_for_non_mock_provider():
    """Gemini and Ollama are expected to already answer in-language; this
    fallback exists specifically for the mock's known gap."""
    assert maybe_translate_fallback("Open the app.", lang="zh_hant",
                                    provider_name="gemini") == "Open the app."
    assert maybe_translate_fallback("Open the app.", lang="zh_hant",
                                    provider_name="ollama") == "Open the app."


def test_noop_when_model_dir_not_configured(monkeypatch):
    """The whole point: nothing changes for a teammate who has not opted
    in, and this must not attempt to import torch to find that out."""
    monkeypatch.delenv("CONNECTPLUS_NLLB_MODEL_DIR", raising=False)
    assert maybe_translate_fallback("Open the app.", lang="zh_hant",
                                    provider_name="mock") == "Open the app."


def test_noop_for_empty_text(monkeypatch):
    monkeypatch.setenv("CONNECTPLUS_NLLB_MODEL_DIR", "/nonexistent")
    assert maybe_translate_fallback("", lang="zh_hant", provider_name="mock") == ""


def test_lines_already_in_chinese_are_left_alone(monkeypatch):
    """Even with a model dir configured, a line that already has Han
    characters (the mock's own hand-written scaffolding) must not be
    re-translated -- only genuinely untranslated lines are touched. This is
    verifiable without a real model: a Chinese-only input has nothing for
    the function to send to translate_en_to_zh_hant at all, so it returns
    unchanged before that function would ever be called."""
    monkeypatch.setenv("CONNECTPLUS_NLLB_MODEL_DIR", "/nonexistent")
    text = "您好。以下是您可以做的步驟：\n\n請聯絡我們的輔導員 [1]。"
    assert maybe_translate_fallback(text, lang="zh_hant",
                                    provider_name="mock") == text
