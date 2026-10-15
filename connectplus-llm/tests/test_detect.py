"""Language detection across all three lanes."""

import pytest

from llm.lang.detect import detect, fold, has_cjk, has_vietnamese_diacritics


# --------------------------------------------------------------------------
# The rule that outranks everything else
# --------------------------------------------------------------------------

def test_app_language_always_wins():
    """A stated choice is a fact. A statistical guess must never overrule it."""
    d = detect("my phone keeps asking for a code", app_lang="vi")
    assert d.lang == "vi"
    assert d.method == "app"
    assert d.confidence == 1.0


# --------------------------------------------------------------------------
# Script layer
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "我收到一条奇怪的短信", "怎么了", "算了", "myGov密码忘记了",
])
def test_chinese_by_script(text):
    assert detect(text).lang == "zh"


def test_japanese_is_not_chinese():
    """Kanji are Han characters, so a naive 'contains Han' rule calls every
    Japanese sentence Chinese. Kana must be checked first."""
    assert detect("携帯電話の設定を教えてください").lang == "und"


@pytest.mark.parametrize("text", [
    "안녕하세요 도와주세요", "مرحبا كيف حالك", "Здравствуйте помогите",
])
def test_out_of_scope_scripts_are_undecided_not_chinese(text):
    """The failure mode of a zh-vs-English classifier is calling every
    non-Latin script Chinese. Saying `und` is the honest answer."""
    assert detect(text).lang == "und"


# --------------------------------------------------------------------------
# Diacritics layer
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Tôi bị lừa đảo", "Điện thoại cứ đòi mã", "Chữ quá nhỏ",
])
def test_vietnamese_by_diacritics(text):
    d = detect(text)
    assert d.lang == "vi"
    assert d.method == "diacritics"


# --------------------------------------------------------------------------
# The hard case: Latin script, no diacritics
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "toi bi lua dao",
    "dien thoai cu doi ma",
    "lam sao chan so dien thoai la",
    "toi khong biet lam the nao",
    "quen mat khau roi",
])
def test_vietnamese_without_diacritics(text):
    """The only case where no cheap rule works. This is the lane a trained
    classifier would take over, and the regression guard for it."""
    assert detect(text).lang == "vi"


@pytest.mark.parametrize("text", [
    "my phone keeps asking for a code",
    "how do I block a number",
    "the writing is too small on my screen",
    "I think I have been scammed",
])
def test_english_stays_english(text):
    assert detect(text).lang == "en"


# --------------------------------------------------------------------------
# Knowing when to shut up
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["myGov", "OTP", "123456", "", "   "])
def test_undecidable_input_is_not_guessed(text):
    """Guessing routes a senior into a language they cannot read. The app
    has a language picker; asking costs one tap."""
    assert detect(text).lang == "und"


def test_undecided_is_reported_as_unsupported():
    assert detect("myGov").supported is False
    assert detect("我收到一条奇怪的短信").supported is True


def test_detection_reports_the_rule_that_decided():
    """A wrong language must trace back to the rule that caused it."""
    assert detect("我收到一条短信").method == "script"
    assert detect("Tôi bị lừa đảo").method == "diacritics"
    assert detect("toi bi lua dao").method == "lexicon"


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------

def test_fold_strips_tone_marks_and_d_stroke():
    assert fold("tôi") == "toi"
    assert fold("đảo") == "dao"
    assert fold("Điện") == "dien"


def test_has_cjk():
    assert has_cjk("短信") is True
    assert has_cjk("tin nhan") is False


def test_has_vietnamese_diacritics():
    assert has_vietnamese_diacritics("lừa đảo") is True
    assert has_vietnamese_diacritics("lua dao") is False
    assert has_vietnamese_diacritics("我收到") is False
