"""The Traditional Chinese lane: terminology, register, readability, expansion.

Mirrors tests/test_zh_lane.py. Kept as a separate file rather than
parametrising the Simplified tests over both lanes, to match how the lane
itself is a separate package -- these tests are also the ones a future
lane's author would copy.
"""

import pytest

from llm.zh_hant import normalize
from llm.zh_hant.readability import score
from llm.zh_hant.termbase import audit, expand, glossary_block, register_block


# --------------------------------------------------------------------------
# Register -- the correctness problem, not a style note
# --------------------------------------------------------------------------

def test_familiar_address_is_an_error():
    violations = audit("你好，請點這個連結。")
    address = [v for v in violations if v.kind == "address"]
    assert address, "你 must be caught"
    assert address[0].severity == "error"
    assert address[0].expected == "您"


def test_respectful_address_passes():
    assert not [v for v in audit("您好，我們可以幫您。") if v.kind == "address"]


def test_plural_familiar_is_reported_once():
    """你們 contains 你. Reporting both would double-count one mistake."""
    address = [v for v in audit("你們好") if v.kind == "address"]
    assert len(address) == 1
    assert address[0].found == "你們"


def test_register_block_names_the_required_address():
    block = register_block()
    assert "您" in block and "你" in block


# --------------------------------------------------------------------------
# Locked terminology, in Taiwan register specifically
# --------------------------------------------------------------------------

def test_locked_term_substitution_is_an_error():
    """兩步認證 is a synonym the Traditional termbase locks against, same as
    the Simplified lane locks 二次验证. The correct term is 雙重認證."""
    violations = [v for v in audit("請設定兩步認證。") if v.kind == "term"]
    assert violations
    assert violations[0].expected == "雙重認證"


def test_taiwan_vocabulary_not_mainland_script_conversion():
    """The point of a hand-reviewed termbase rather than a straight OpenCC
    pass: 網路 is the Taiwan word for the internet, not merely 网络 with its
    characters swapped to Traditional."""
    assert "網路" in glossary_block()
    assert "网络" not in glossary_block()


def test_glossary_block_is_rendered_for_the_prompt():
    block = glossary_block()
    assert "雙重認證" in block
    assert "不要用" in block


# --------------------------------------------------------------------------
# Untranslated English
# --------------------------------------------------------------------------

def test_untranslated_english_is_an_error():
    violations = [v for v in audit("您好，請檢查 suspicious message。")
                  if v.kind == "untranslated"]
    assert violations
    assert violations[0].severity == "error"


def test_protected_nouns_are_not_flagged():
    violations = [v for v in audit("請登入 myGov 和 Centrelink 查看。")
                  if v.kind == "untranslated"]
    assert not violations


def test_citation_markers_do_not_count_as_english():
    assert not [v for v in audit("您好，請小心 [1]。") if v.kind == "untranslated"]


# --------------------------------------------------------------------------
# Query expansion -- the deterministic floor
# --------------------------------------------------------------------------

def test_expansion_produces_english_retrieval_terms():
    terms = expand("我收到一條奇怪的簡訊")
    assert terms
    assert all(t.isascii() for t in terms)


def test_service_names_survive_verbatim():
    assert "myGov" in expand("myGov密碼忘記了怎麼辦")
    assert "Centrelink" in expand("Centrelink的電話打不通")


def test_longer_keys_win():
    terms = expand("我忘記密碼了")
    assert "forgot password" in terms


def test_expansion_returns_nothing_for_an_unrelated_question():
    assert expand("今天天氣怎麼樣") == []


# --------------------------------------------------------------------------
# Readability
# --------------------------------------------------------------------------

def test_plain_chinese_scores_better_than_officialese():
    plain = score("您好。請不要點這個連結。如果不放心，請打電話給銀行。")
    formal = score(
        "若您收到上述信息，須立即進行核實並予以處理，"
        "相關事宜請前往官方網站查詢並獲取進一步的操作指引如下。")
    assert plain.score > formal.score


def test_untranslated_english_caps_the_score():
    english = score("Open the app. Tap settings. Then tap security. Done now.")
    assert english.capped is True
    assert english.score <= 40.0


# --------------------------------------------------------------------------
# normalize.py and readability.py are re-exports of the Simplified lane's
# modules (see llm/zh_hant/__init__.py for why); this is the check that the
# re-export actually points at working code, not a smoke test of logic that
# is already covered by test_zh_lane.py.
# --------------------------------------------------------------------------

def test_normalize_reexport_is_wired_up():
    assert normalize.count_han("您好世界") == 4
    assert normalize.strip_citations("您好 [1]。") == "您好 。"
