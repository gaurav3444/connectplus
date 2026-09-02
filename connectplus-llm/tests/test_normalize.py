"""Folding, syllables and sentences."""

import pytest

from llm.vi.normalize import (fold, has_vietnamese_diacritics, sentences,
                              syllables)


@pytest.mark.parametrize("written,typed", [
    ("Tôi bị lừa đảo", "toi bi lua dao"),
    ("Điện thoại cứ đòi mã", "dien thoai cu doi ma"),
    ("Xác thực hai bước", "xac thuc hai buoc"),
    ("Đăng nhập myGov", "dang nhap mygov"),
])
def test_diacritic_and_plain_spellings_fold_together(written, typed):
    """The whole termbase depends on this: a senior typing without dau must
    hit the same entries as one typing with it."""
    assert fold(written) == fold(typed)


def test_d_with_stroke_is_not_decomposed_by_unicode():
    """Regression guard. NFD does not split 'đ', so it needs its own rule."""
    assert fold("đảo") == "dao"
    assert fold("Đăng") == "dang"


def test_detects_vietnamese_only_orthography():
    assert has_vietnamese_diacritics("điện")          # d with stroke
    assert has_vietnamese_diacritics("bị")            # dot below
    assert has_vietnamese_diacritics("để")            # circumflex + hook stacked
    assert has_vietnamese_diacritics("lừa")           # horn
    assert not has_vietnamese_diacritics("toi bi lua dao")
    assert not has_vietnamese_diacritics("hello world")


def test_single_shared_accent_is_not_decisive():
    """A lone circumflex is French as often as it is Vietnamese, so 'Tôi' on
    its own does not take the diacritics path - it goes to the lexicon, which
    resolves it correctly anyway. Accepting a bare accent here would classify
    'cafe' with an accent, 'etre' and 'senor' as Vietnamese."""
    assert not has_vietnamese_diacritics("Tôi")
    from llm.vi.detect import detect
    assert detect("Tôi").lang == "vi"        # lexicon still gets it right


@pytest.mark.parametrize("text", ["café", "naïve", "señor", "être"])
def test_other_latin_scripts_are_not_vietnamese(text):
    """The regression this rule exists for."""
    assert not has_vietnamese_diacritics(text)


def test_syllables_are_whitespace_tokens():
    assert syllables("xác thực hai bước") == ["xác", "thực", "hai", "bước"]


def test_sentences_split_on_terminal_punctuation():
    assert len(sentences("Xin chào. Ông khỏe không? Vâng!")) == 3
    assert sentences("") == []
