"""Stage 07 - query understanding and its failure modes."""

import pytest

from llm.providers.base import Provider, ProviderError
from llm.s07_query import understand, validate_rewrite


class Echo(Provider):
    """Returns whatever it was constructed with, ignoring the prompt."""
    name = "echo"

    def __init__(self, reply):
        self.reply = reply

    def complete(self, prompt, *, temperature=0.2, max_tokens=1024):
        return self.reply


class Dead(Provider):
    name = "dead"

    def complete(self, prompt, *, temperature=0.2, max_tokens=1024):
        raise ProviderError("no quota")


@pytest.mark.parametrize("bad,reason", [
    ("", "empty"),
    ("tin nhắn lừa đảo", "still Vietnamese"),
    ("Here is the English query: scam sms", "model narrated instead of answering"),
    ("scam " * 20, "too long"),
    ("scam\nmessage", "multiple lines"),
])
def test_bad_rewrites_are_rejected(bad, reason):
    """A wrong rewrite is worse than no rewrite: it sends retrieval after the
    wrong thing while looking like it worked."""
    ok, got = validate_rewrite(bad)
    assert not ok
    assert reason.split()[0] in got


def test_good_rewrite_is_accepted():
    assert validate_rewrite("scam text message australia") == (True, "")


def test_llm_rewrite_is_used_when_valid():
    u = understand("Tôi bị lừa đảo", app_lang="vi",
                   provider=Echo("scam text message australia"))
    assert u.rewrite_source == "llm"
    assert u.rewritten_en == "scam text message australia"


def test_invalid_llm_rewrite_falls_back_to_the_termbase():
    """The deterministic floor. A model that answers in Vietnamese, or
    narrates, must not poison the retrieval query."""
    u = understand("Tôi bị lừa đảo", app_lang="vi",
                   provider=Echo("tin nhắn lừa đảo"))
    assert u.rewrite_source == "termbase"
    assert "scam" in u.rewritten_en


def test_dead_provider_still_produces_a_retrievable_query():
    u = understand("Điện thoại cứ đòi mã", app_lang="vi", provider=Dead())
    assert u.rewrite_source == "termbase"
    assert "two-factor authentication" in u.rewritten_en


def test_unmatched_query_with_no_model_passes_through():
    u = understand("Hôm nay trời đẹp quá", app_lang="vi", provider=Dead())
    assert u.rewrite_source == "passthrough"
    assert u.rewritten_en == "Hôm nay trời đẹp quá"


def test_english_question_skips_the_rewrite(provider):
    """No model call, no latency, no chance to mangle a query that is already
    in the language the sources are written in."""
    u = understand("how do I block this number", provider=provider)
    assert u.lang == "en"
    assert u.rewrite_source == "passthrough"


def test_expansion_terms_are_always_recorded(provider):
    u = understand("Tôi quên mật khẩu myGov", app_lang="vi", provider=provider)
    assert u.expansion_terms
