"""End-to-end behaviour for the zh_hant lane, mirroring the zh/vi cases in
tests/test_pipeline.py.
"""

import pytest

from llm.lanes import REFUSALS, available_lanes, get_lane
from llm.pipeline import answer

# pytest.ini sets asyncio_mode = auto; see tests/test_pipeline.py.


def test_zh_hant_is_a_registered_lane():
    assert "zh_hant" in available_lanes()
    lane = get_lane("zh_hant")
    assert lane.answer_template == "zh_hant_answer.v1.jinja"
    assert lane.rewrite_template == "zh_hant_query_rewrite.v1.jinja"


def test_every_lane_including_zh_hant_has_a_handwritten_refusal():
    for code in available_lanes():
        assert REFUSALS[code].strip()


async def test_zh_hant_question_is_answered_in_traditional_chinese(provider):
    out = await answer("我收到一則奇怪的簡訊說我帳戶有問題這是真的嗎",
                       app_lang="zh_hant", provider=provider)
    assert out.refused is False
    assert out.lang == "zh_hant"
    assert out.citations
    assert "您" in out.answer_md


async def test_zh_hant_medical_question_is_refused_in_traditional_chinese(provider):
    out, trace = await answer("我胸口痛應該吃什麼藥", app_lang="zh_hant",
                              provider=provider, with_trace=True)
    assert out.refused is True
    assert trace.refused_at == "retrieval"
    assert out.answer_md == REFUSALS["zh_hant"]
    assert not out.citations


async def test_zh_hant_refusal_offers_a_mentor(provider):
    out = await answer("我想買個新手機買哪個牌子好", app_lang="zh_hant",
                       provider=provider)
    assert out.refused is True
    assert out.answer_md == REFUSALS["zh_hant"]
    assert "輔導員" in out.answer_md


async def test_zh_hant_detected_without_an_app_language(provider):
    """Traditional script alone, with no app_lang hint, must still route to
    the zh_hant lane and not fall back to Simplified."""
    out = await answer("你好嗎？我的密碼被盜用了怎麼辦", provider=provider)
    assert out.lang == "zh_hant"


async def test_zh_and_zh_hant_are_distinct_lanes(provider):
    """The two Chinese lanes must not collapse into one another: same
    question, different script, different lane and different template."""
    zh_out = await answer("我的密码被盗用了怎么办", app_lang="zh", provider=provider)
    hant_out = await answer("我的密碼被盜用了怎麼辦", app_lang="zh_hant", provider=provider)
    assert zh_out.lang == "zh"
    assert hant_out.lang == "zh_hant"
    assert get_lane("zh").answer_template != get_lane("zh_hant").answer_template
