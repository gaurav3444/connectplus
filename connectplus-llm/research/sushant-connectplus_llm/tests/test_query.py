"""Offline tests for stage 07. Run with the stub provider -- no key, no wifi."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from connectplus_llm.lang_id import identify_language
from connectplus_llm.query import degraded_plan, understand
from connectplus_llm.schemas import QueryPlan, QueryRequest


def test_identifies_chinese():
    assert identify_language("我的手机一直要我输入验证码") == "zh"


def test_identifies_english():
    assert identify_language("my phone keeps asking for a code") == "en"


def test_identifies_vietnamese():
    assert identify_language("điện thoại của tôi cứ hỏi mã xác minh") == "vi"


def test_rejects_out_of_scope_language():
    """Korean -- not one of the three supported languages -- must not be
    silently accepted as if it were English."""
    assert identify_language("이 문자 메시지가 사기인가요") is None


@pytest.mark.asyncio
async def test_unsupported_language_refused_without_llm_call():
    plan = await understand(QueryRequest(raw_query="이 문자 메시지가 사기인가요"))
    assert plan.supported is False
    assert plan.lang is None
    assert plan.query_rewritten == ""


@pytest.mark.asyncio
async def test_english_query_understood():
    plan = await understand(QueryRequest(raw_query="my phone keeps asking for a code"))
    assert plan.supported is True
    assert plan.lang == "en"
    assert plan.query_original == "my phone keeps asking for a code"


@pytest.mark.asyncio
async def test_chinese_query_understood():
    plan = await understand(QueryRequest(raw_query="我的手机一直要我输入验证码"))
    assert plan.supported is True
    assert plan.lang == "zh"


@pytest.mark.asyncio
async def test_vietnamese_query_understood():
    plan = await understand(QueryRequest(raw_query="điện thoại của tôi cứ hỏi mã xác minh"))
    assert plan.supported is True
    assert plan.lang == "vi"


@pytest.mark.asyncio
async def test_rewritten_query_is_never_empty_for_supported_languages():
    for raw in ["my phone keeps asking for a code", "我的手机一直要我输入验证码"]:
        plan = await understand(QueryRequest(raw_query=raw))
        assert plan.query_rewritten.strip() != ""


def test_degraded_plan_sets_flag_and_extracts_english_keywords():
    plan = degraded_plan(QueryRequest(raw_query="the writing is too small"), lang="en")
    assert plan.degraded is True
    assert "writing" in plan.query_rewritten
    assert "small" in plan.query_rewritten


def test_degraded_plan_chinese_falls_back_to_generic_query_not_untranslated_text():
    """No model, no honest translation available -- must not just echo the
    Chinese text back as the 'query', since retrieval only understands English."""
    plan = degraded_plan(QueryRequest(raw_query="我的手机一直要我输入验证码"), lang="zh")
    assert plan.degraded is True
    assert plan.query_rewritten == "digital literacy help getting started"


def test_degraded_plan_vietnamese_falls_back_to_generic_query():
    plan = degraded_plan(QueryRequest(raw_query="điện thoại của tôi cứ hỏi mã xác minh"), lang="vi")
    assert plan.degraded is True
    assert plan.query_rewritten == "digital literacy help getting started"


def test_query_plan_rejects_cjk_in_rewritten_field():
    with pytest.raises(ValueError):
        QueryPlan(query_original="x", query_rewritten="我的手机", lang="zh")
