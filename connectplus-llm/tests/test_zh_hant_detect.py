"""Simplified vs Traditional Chinese script detection.

Companion to tests/test_detect.py, which already covers the Chinese-vs-
Japanese-vs-everything-else layer. These tests are specifically for the
finer-grained question added on top of it: once something is known to be
Chinese, which script is it in.
"""

import pytest

from llm.lang.detect import detect, detect_script


# --------------------------------------------------------------------------
# Traditional, unambiguously
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "你好嗎？", "請檢查您的密碼", "這是詐騙簡訊，請不要點擊連結",
])
def test_traditional_only_text_is_zh_hant(text):
    assert detect_script(text) == "zh_hant"
    assert detect(text).lang == "zh_hant"


# --------------------------------------------------------------------------
# Simplified, unambiguously
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "你好吗？", "请检查您的密码", "这是诈骗短信，请不要点击链接",
])
def test_simplified_only_text_is_zh(text):
    assert detect_script(text) == "zh"
    assert detect(text).lang == "zh"


# --------------------------------------------------------------------------
# Script-neutral text: the bug this module exists to avoid regressing.
#
# hanzidentifier.is_traditional() returns True for these on its own, because
# every character in them is *valid* Traditional Chinese -- it is also valid
# Simplified Chinese, since none of these characters differ between the two
# scripts. Using identify() and checking specifically for the TRADITIONAL
# verdict (as opposed to BOTH) is what tells "genuinely Traditional" apart
# from "happens to pass a Traditional membership test". Regressing this
# would route every mainland Simplified-writing senior who happens to type a
# short, script-neutral sentence into the wrong lane.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "怎么了", "算了", "我收到一条奇怪的短信", "myGov密码忘记了",
])
def test_script_neutral_text_defaults_to_zh_not_zh_hant(text):
    assert detect_script(text) == "zh"
    assert detect(text).lang == "zh"


# --------------------------------------------------------------------------
# Mixed script: also not treated as Traditional
# --------------------------------------------------------------------------

def test_mixed_script_defaults_to_zh():
    """發 is Traditional-only, 电 is Simplified-only. Pasted-together text
    like this is not confident evidence of a Traditional-writing senior, so
    it degrades to the long-standing default rather than guessing."""
    assert detect_script("發电子邮件") == "zh"


# --------------------------------------------------------------------------
# supported() includes the new lane
# --------------------------------------------------------------------------

def test_traditional_chinese_is_a_supported_language():
    assert detect("你好嗎？").supported is True
    assert detect("你好嗎？").lang == "zh_hant"
