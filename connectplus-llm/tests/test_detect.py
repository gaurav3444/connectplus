"""Language detection, including the case the whole module exists for."""

import json
from pathlib import Path

import pytest

from llm.vi.detect import detect

CASES = json.loads(
    (Path(__file__).parent.parent / "llm/eval/data/detect_cases.json")
    .read_text(encoding="utf-8"))["cases"]


def test_app_language_always_wins():
    """The user chose a language in the app. A statistical guess must never
    overrule a stated fact - answering a Vietnamese senior in English because
    a detector was confident is the failure this rule prevents."""
    d = detect("how do I block this number", app_lang="vi")
    assert d.lang == "vi"
    assert d.method == "app"
    assert d.confidence == 1.0


@pytest.mark.parametrize("text", [
    "Tôi bị lừa đảo", "Điện thoại cứ đòi mã", "Tôi quên mật khẩu rồi",
])
def test_diacritics_are_decisive(text):
    d = detect(text)
    assert d.lang == "vi"
    assert d.method == "diacritics"


@pytest.mark.parametrize("text", [
    "toi bi lua dao", "dien thoai cu doi ma", "tai khoan ngan hang bi khoa",
    "myGov khong vao duoc",
])
def test_vietnamese_without_diacritics(text):
    """The hard case: how people actually type on a phone."""
    assert detect(text).lang == "vi"


@pytest.mark.parametrize("text", [
    "how do I block this number", "connect my phone to wifi",
    "I forgot my myGov password",
])
def test_english_is_not_claimed_as_vietnamese(text):
    assert detect(text).lang == "en"


def test_short_product_names_are_undecided_not_guessed():
    """'myGov' is not a Vietnamese sentence. With no function word from either
    language, the honest answer is 'I don't know'."""
    assert detect("myGov").lang == "und"
    assert detect("OTP").lang == "und"
    assert detect("123456").lang == "und"


def test_chinese_is_routed_by_script():
    assert detect("我收到一条奇怪的短信").lang == "zh"


def test_empty_input():
    assert detect("").lang == "und"


def test_accuracy_on_the_full_case_set():
    """Guards against a regression in the lexicon or the shape signal.

    Note this is a development set, not a held-out one: the detector and these
    cases were written together, so this number is a regression guard rather
    than an unbiased estimate of accuracy.
    """
    correct = sum(detect(c["text"]).lang == c["expect"] for c in CASES)
    assert correct / len(CASES) >= 0.90


def test_accuracy_on_hard_cases():
    hard = [c for c in CASES if c["hard"]]
    correct = sum(detect(c["text"]).lang == c["expect"] for c in hard)
    assert correct / len(hard) >= 0.85
