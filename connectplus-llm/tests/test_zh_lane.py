"""The Chinese lane: terminology, register, readability, expansion.

These are the tests for the half of the product that did not exist before
this merge.
"""

import pytest

from llm.zh import normalize
from llm.zh.readability import score
from llm.zh.termbase import audit, expand, glossary_block, register_block


# --------------------------------------------------------------------------
# Register -- the correctness problem, not a style note
# --------------------------------------------------------------------------

def test_familiar_address_is_an_error():
    """Addressing a senior as 你 is disrespectful, and it is what a model
    reaches for because web copy is written for thirty-year-olds."""
    violations = audit("你好，请点这个链接。")
    address = [v for v in violations if v.kind == "address"]
    assert address, "你 must be caught"
    assert address[0].severity == "error"
    assert address[0].expected == "您"


def test_respectful_address_passes():
    assert not [v for v in audit("您好，我们可以帮您。") if v.kind == "address"]


def test_plural_familiar_is_reported_once():
    """你们 contains 你. Reporting both would double-count one mistake."""
    address = [v for v in audit("你们好") if v.kind == "address"]
    assert len(address) == 1
    assert address[0].found == "你们"


def test_register_block_names_the_required_address():
    block = register_block()
    assert "您" in block and "你" in block


# --------------------------------------------------------------------------
# Locked terminology
# --------------------------------------------------------------------------

def test_locked_term_substitution_is_an_error():
    """A senior may be matching what they read against what is on screen,
    so a synonym is a correctness problem rather than a style preference."""
    violations = [v for v in audit("请设置二次验证。") if v.kind == "term"]
    assert violations
    assert violations[0].expected == "双重认证"


def test_common_login_typo_is_caught():
    """登陆 means 'to land'. It is the most common Chinese typo for 登录."""
    violations = [v for v in audit("请登陆您的账户。") if v.kind == "term"]
    assert any(v.expected == "登录" for v in violations)


def test_glossary_block_is_rendered_for_the_prompt():
    block = glossary_block()
    assert "双重认证" in block
    assert "不要用" in block


# --------------------------------------------------------------------------
# Untranslated English
# --------------------------------------------------------------------------

def test_untranslated_english_is_an_error():
    violations = [v for v in audit("您好，请检查 suspicious message。")
                  if v.kind == "untranslated"]
    assert violations
    assert violations[0].severity == "error"


def test_protected_nouns_are_not_flagged():
    """myGov and Centrelink must stay in English -- they name the thing on
    the senior's screen."""
    violations = [v for v in audit("请登录 myGov 和 Centrelink 查看。")
                  if v.kind == "untranslated"]
    assert not violations


def test_citation_markers_do_not_count_as_english():
    assert not [v for v in audit("您好，请小心 [1]。") if v.kind == "untranslated"]


# --------------------------------------------------------------------------
# Query expansion -- the deterministic floor
# --------------------------------------------------------------------------

def test_expansion_produces_english_retrieval_terms():
    terms = expand("我收到一条奇怪的短信")
    assert terms
    assert all(t.isascii() for t in terms)


def test_service_names_survive_verbatim():
    """The single most important thing the RAG team needs from us: if the
    index normalises myGov away, every service query fails."""
    assert "myGov" in expand("myGov密码忘记了怎么办")
    assert "Centrelink" in expand("Centrelink的电话打不通")


def test_longer_keys_win():
    """忘记密码 is more specific than 密码 and must rank first."""
    terms = expand("我忘记密码了")
    assert "forgot password" in terms


def test_expansion_returns_nothing_for_an_unrelated_question():
    assert expand("今天天气怎么样") == []


# --------------------------------------------------------------------------
# Readability
# --------------------------------------------------------------------------

def test_plain_chinese_scores_better_than_officialese():
    """The whole reason this metric exists: Flesch-Kincaid would rate these
    two the same, because Chinese is not whitespace-delimited and every Han
    character is one syllable."""
    plain = score("您好。请不要点这个链接。如果不放心，请打电话给银行。")
    formal = score(
        "若您收到上述信息，须立即进行核实并予以处理，"
        "相关事宜请前往官方网站查询并获取进一步的操作指引如下。")
    assert plain.score > formal.score


def test_untranslated_english_caps_the_score():
    """An answer that stayed in English must not score 'easy' just because
    its sentences are short. Readability presumes the reader can read it."""
    english = score("Open the app. Tap settings. Then tap security. Done now.")
    assert english.capped is True
    assert english.score <= 40.0


def test_empty_text_is_hard_not_crashing():
    r = score("")
    assert r.grade == "hard"
    assert r.score == 0.0


def test_signals_are_reported_so_a_score_can_be_argued_with():
    r = score("您好。请点这个链接。")
    for key in ("chars_per_sentence", "long_sentence_rate",
                "latin_rate", "formal_per_100"):
        assert key in r.signals


# --------------------------------------------------------------------------
# Chinese-specific primitives
# --------------------------------------------------------------------------

def test_sentences_split_on_chinese_punctuation():
    assert len(normalize.sentences("第一句。第二句！第三句？")) == 3


def test_latin_rate_ignores_citation_markers():
    assert normalize.latin_char_rate("您好 [1][2]") == 0.0


def test_han_counting():
    assert normalize.count_han("您好 hello") == 2
