"""Stage 06 - Query Understanding.

Every test injects a fake llm_fn. No network, no API key, no provider
running locally - same approach as every other stage in this repo, and the
reason the whole suite passes offline.

What is NOT tested here, stated plainly: _gemini_llm() and _ollama_llm()
make real HTTP calls and have never been run by me. They are thin enough to
read in one screen, and get_default_llm() is the only thing that builds
them. Same honest caveat as stage 04's embedder and stage 05's database
functions carry.
"""

from __future__ import annotations

import json

import pytest

from rag.s06_query import (
    MAX_EXPANSIONS,
    PROMPT_VERSION,
    keyword_query_for,
    understand,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def fake_llm(rewritten: str, expansions: list[str] | None = None):
    """An llm_fn that always returns well-formed JSON."""

    def call(_prompt: str) -> str:
        return json.dumps({"rewritten": rewritten, "expansions": expansions or []})

    return call


def replying(text: str):
    """An llm_fn returning a fixed raw string, well-formed or not."""

    def call(_prompt: str) -> str:
        return text

    return call


def exploding(exc: Exception):
    def call(_prompt: str) -> str:
        raise exc

    return call


# ---------------------------------------------------------------------------
# language
# ---------------------------------------------------------------------------


def test_explicit_lang_is_authoritative_and_skips_detection() -> None:
    """The frontend knows which language the senior chose. That beats
    langdetect run over a six-word question, so an explicit lang must win
    even when it disagrees with what detection would have said."""
    result = understand("how do I spot a scam text", lang="zh-cn", llm_fn=fake_llm("scam text messages"))
    assert result.lang == "zh-cn"


def test_mandarin_query_is_detected_and_rewritten_into_english() -> None:
    """The core CALD use case, end to end through this stage: the senior
    types Mandarin, the stage reports zh so the generator can answer in
    Mandarin, and the rewrite comes out English so keyword search can
    actually match the English corpus."""
    result = understand(
        "我的手机一直要求输入验证码",
        llm_fn=fake_llm("two-factor authentication", ["verification code", "2FA"]),
    )
    assert result.lang.startswith("zh")
    assert result.rewritten == "two-factor authentication"
    assert result.original == "我的手机一直要求输入验证码"


def test_english_query_detects_as_english() -> None:
    result = understand(
        "how do I know if a text message is a scam", llm_fn=fake_llm("scam text message")
    )
    assert result.lang == "en"


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------


def test_the_stage_maps_own_example_case() -> None:
    """The stage map's card names this exact transformation as the point of
    the stage: a vague description becomes the real searchable term."""
    result = understand(
        "my phone keeps asking for a code",
        llm_fn=fake_llm("two-factor authentication", ["verification code"]),
    )
    assert result.rewritten == "two-factor authentication"
    assert result.expansions == ["verification code"]
    assert result.prompt_version == PROMPT_VERSION


def test_json_wrapped_in_a_code_fence_still_parses() -> None:
    """Models asked for "only JSON" wrap it in a fence anyway. Without this
    the stage would fall back to passthrough on every single call while
    still looking healthy - no error, no crash, just silently doing
    nothing."""
    fenced = '```json\n{"rewritten": "mygov account login", "expansions": ["Centrelink"]}\n```'
    result = understand("how do I get into mygov", llm_fn=replying(fenced))
    assert result.rewritten == "mygov account login"
    assert result.expansions == ["Centrelink"]


def test_bare_fence_without_the_json_tag_also_parses() -> None:
    result = understand("what is mygov", llm_fn=replying('```\n{"rewritten": "mygov"}\n```'))
    assert result.rewritten == "mygov"


def test_missing_expansions_key_is_fine() -> None:
    result = understand("what is mygov", llm_fn=replying('{"rewritten": "mygov"}'))
    assert result.expansions == []
    assert result.prompt_version == PROMPT_VERSION


def test_expansions_given_as_a_comma_string_are_split() -> None:
    """A real shape models produce instead of a list."""
    result = understand(
        "scam texts",
        llm_fn=replying('{"rewritten": "scam text", "expansions": "smishing, SMS fraud"}'),
    )
    assert result.expansions == ["smishing", "SMS fraud"]


def test_expansions_are_deduped_case_insensitively_and_capped() -> None:
    result = understand(
        "scam texts",
        llm_fn=fake_llm("scam text", ["smishing", "SMISHING", "sms fraud", "phishing", "fake sms"]),
    )
    assert len(result.expansions) <= MAX_EXPANSIONS
    assert result.expansions == ["smishing", "sms fraud", "phishing"]


def test_expansions_already_inside_the_rewrite_are_dropped() -> None:
    """Repeating a term already in `rewritten` adds no lexical recall and
    just pads the keyword query."""
    result = understand("scam texts", llm_fn=fake_llm("scam text message", ["scam", "smishing"]))
    assert result.expansions == ["smishing"]


def test_blank_and_whitespace_expansions_are_dropped() -> None:
    result = understand("scam texts", llm_fn=fake_llm("scam text", ["", "  ", "smishing"]))
    assert result.expansions == ["smishing"]


# ---------------------------------------------------------------------------
# fallback - this stage must never be able to break retrieval
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_reply",
    [
        "I'd be happy to help you with that!",          # prose, not JSON
        "{not json at all",                              # malformed
        '{"expansions": ["a"]}',                         # missing 'rewritten'
        '{"rewritten": ""}',                             # empty rewrite
        '{"rewritten": "   "}',                          # whitespace-only rewrite
        "",                                              # empty response
    ],
)
def test_unusable_llm_output_falls_back_to_the_original_query(bad_reply: str) -> None:
    result = understand("how do I spot a scam text", llm_fn=replying(bad_reply))
    assert result.rewritten == "how do I spot a scam text"
    assert result.expansions == []
    assert result.prompt_version == "", "fallback did not call an LLM, so it claims no prompt version"


def test_an_llm_that_raises_falls_back_instead_of_propagating() -> None:
    """A dead provider, a timeout, a missing API key. Query understanding
    is an enhancement - an exception here would take down the whole answer
    path over an optional step."""
    result = understand("how do I spot a scam text", llm_fn=exploding(RuntimeError("connection refused")))
    assert result.rewritten == "how do I spot a scam text"


def test_fallback_still_reports_the_detected_language() -> None:
    """Even when the rewrite fails, the generator downstream still needs to
    know which language to answer in."""
    result = understand("我的手机一直要求输入验证码", llm_fn=exploding(RuntimeError("boom")))
    assert result.lang.startswith("zh")
    assert result.rewritten == "我的手机一直要求输入验证码"


def test_blank_query_returns_immediately_without_calling_the_llm() -> None:
    """Matches retrieve()'s own blank-query behaviour, and there is nothing
    to rewrite."""
    calls: list[str] = []

    def counting_llm(prompt: str) -> str:
        calls.append(prompt)
        return "{}"

    result = understand("   ", llm_fn=counting_llm)
    assert calls == []
    assert result.rewritten == "   "
    assert result.lang == "unknown"


# ---------------------------------------------------------------------------
# handoff to stage 05
# ---------------------------------------------------------------------------


def test_keyword_query_joins_the_rewrite_with_its_expansions() -> None:
    understood = understand(
        "我的手机一直要求输入验证码",
        llm_fn=fake_llm("two-factor authentication", ["verification code", "2FA"]),
    )
    assert keyword_query_for(understood) == "two-factor authentication verification code 2FA"


def test_keyword_query_of_a_passthrough_is_just_the_original() -> None:
    understood = understand("scam text", llm_fn=exploding(RuntimeError("boom")))
    assert keyword_query_for(understood) == "scam text"
