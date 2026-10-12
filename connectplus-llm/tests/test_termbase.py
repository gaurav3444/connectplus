"""Locked terminology, register and query expansion."""

import pytest

from llm.vi.termbase import audit, expand, glossary_block, register_block


def test_expansion_matches_with_and_without_diacritics():
    assert expand("Tôi bị lừa đảo") == expand("toi bi lua dao")
    assert "scam" in expand("toi bi lua dao")


def test_longer_phrases_win():
    """'tin nhan lua dao' is more specific than 'lua dao' and must rank first,
    or the retrieval query loses the fact that it was a text message."""
    terms = expand("tin nhan lua dao")
    assert terms[0] == "scam text message"


def test_vague_phrasing_becomes_a_retrievable_concept():
    """The README's own example, in Vietnamese: a description of an experience
    has to become the name of the thing."""
    assert "two-factor authentication" in expand("Điện thoại cứ đòi mã")


def test_unmatched_query_returns_nothing_rather_than_guessing():
    assert expand("hôm nay trời đẹp quá") == []


def test_forbidden_synonym_is_an_error():
    v = audit("Đây là gian lận.")
    assert any(x.kind == "forbidden_term" and x.severity == "error" for x in v)


def test_peer_address_to_a_senior_is_an_error():
    """The register failure that matters most. Every model reaches for 'bạn'
    because that is what web copy uses; web copy is written for 30-year-olds."""
    v = audit("Bạn nên xóa tin nhắn này.")
    assert any(x.kind == "address" and x.severity == "error" for x in v)


def test_correct_address_passes():
    assert not any(x.kind == "address"
                   for x in audit("Thưa ông/bà, xin ông/bà xóa tin nhắn này."))


def test_short_forbidden_terms_do_not_match_inside_other_syllables():
    """Regression. 'ap' (a forbidden rendering of 'app') is a substring of
    'truy cap'. Naive substring matching fired on innocent text; every lookup
    now matches whole tokens only."""
    v = audit("Xin ông/bà bấm vào ứng dụng.")
    assert not any(x.kind == "forbidden_term" for x in v)


def test_formal_register_is_a_warning_not_an_error():
    v = audit("Xin ông/bà truy cập myGov.")
    formal = [x for x in v if x.kind == "formal_register"]
    assert formal and formal[0].severity == "warning"
    assert formal[0].expected == "vào"


def test_proper_noun_dropped_from_the_answer_is_reported():
    """A step that names no app is a step the reader cannot follow."""
    v = audit("Thưa ông/bà, xin ông/bà đăng nhập.",
              source_text="Sign in to myGov to update your details.")
    assert any(x.kind == "untranslated_noun" and "myGov" in x.expected for x in v)


def test_clean_answer_has_no_violations():
    assert audit("Thưa ông/bà, đây là tin nhắn lừa đảo. "
                 "Xin ông/bà đừng bấm vào đường liên kết.") == []


@pytest.mark.parametrize("block", [glossary_block(), register_block()])
def test_prompt_blocks_are_non_empty(block):
    assert len(block.splitlines()) > 3
