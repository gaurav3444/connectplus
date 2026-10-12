"""End-to-end behaviour, prompt safety, and the refusal paths."""

import pytest

from llm.lanes import REFUSALS, available_lanes, get_lane
from llm.pipeline import answer
from llm.s07_query import parse_rewrite, validate_rewrite
from llm.s08_prompt import build_answer_prompt, sanitise_chunk
from llm.s09_generate import extract_citations

# No pytestmark here: pytest.ini sets asyncio_mode = auto, so async tests are
# collected automatically and a blanket marker would only warn on the sync
# ones in this file.


# --------------------------------------------------------------------------
# Every lane is complete
# --------------------------------------------------------------------------

def test_every_lane_has_a_handwritten_refusal():
    """A refusal fires exactly when the model may be the broken thing, so
    its wording must never come from the model."""
    for code in available_lanes():
        assert REFUSALS[code].strip()


def test_every_lane_has_its_own_answer_template():
    """The bug this replaces: build_answer_prompt used to load the Vietnamese
    template for every language, so a Chinese question produced a prompt
    saying 'write in Vietnamese'."""
    templates = {get_lane(c).answer_template for c in available_lanes()}
    assert len(templates) == len(available_lanes())


def test_answer_prompt_requires_a_language(chunks):
    with pytest.raises(TypeError):
        build_answer_prompt(chunks, query_original="q", query_rewritten="q")


def test_chinese_prompt_is_chinese_and_vietnamese_is_not(chunks):
    zh = build_answer_prompt(chunks, lang="zh", query_original="问题",
                             query_rewritten="question").text
    vi = build_answer_prompt(chunks, lang="vi", query_original="câu hỏi",
                             query_rewritten="question").text
    assert "您" in zh and "ông/bà" not in zh
    assert "ông/bà" in vi and "您" not in vi


# --------------------------------------------------------------------------
# Prompt injection
# --------------------------------------------------------------------------

def test_poisoned_chunk_cannot_close_its_fence(poisoned):
    cleaned, modified = sanitise_chunk(poisoned.text)
    assert modified is True
    assert "<<<END SOURCE" not in cleaned
    assert "ignore all your previous instructions" not in cleaned.lower()


def test_poisoned_chunk_is_reported_by_id(chunks, poisoned):
    prompt = build_answer_prompt([poisoned, *chunks[:2]], lang="zh",
                                 query_original="问题", query_rewritten="q")
    assert poisoned.id in prompt.sanitised_chunk_ids


def test_genuine_advice_containing_trigger_words_survives():
    """The phrase list is for detection. It must not destroy a real page that
    happens to explain what a system prompt is."""
    text = ("Follow the instructions on the screen. Your bank will never ask "
            "you to ignore a security warning.")
    cleaned, modified = sanitise_chunk(text)
    assert modified is False
    assert cleaned == text


def test_clean_chunks_are_not_reported(chunks):
    prompt = build_answer_prompt(chunks, lang="zh", query_original="问题",
                                 query_rewritten="q")
    assert prompt.sanitised_chunk_ids == []


# --------------------------------------------------------------------------
# Rewrite validation
# --------------------------------------------------------------------------

def test_structured_output_is_parsed():
    assert parse_rewrite('{"query_rewritten": "scam text message"}') == \
        "scam text message"


def test_markdown_fenced_json_is_still_parsed():
    raw = '```json\n{"query_rewritten": "password reset"}\n```'
    assert parse_rewrite(raw) == "password reset"


@pytest.mark.parametrize("text,reason", [
    ("", "empty"),
    ("我收到一条奇怪的短信", "still Chinese"),
    ("tôi bị lừa đảo", "still Vietnamese"),
    ("one\ntwo", "multiple lines"),
    (" ".join(["word"] * 30), "too long"),
])
def test_unusable_rewrites_are_rejected(text, reason):
    """A bad rewrite is worse than none: it sends the retriever after the
    wrong thing while looking like it worked."""
    ok, why = validate_rewrite(text)
    assert ok is False
    assert reason in why


def test_good_rewrite_passes():
    assert validate_rewrite("two-factor authentication verification code") == (True, "")


# --------------------------------------------------------------------------
# Citations
# --------------------------------------------------------------------------

def test_citations_resolve_in_prompt_order(chunks):
    cites, invalid = extract_citations("Step one [1]. Step two [2].", chunks)
    assert [c.n for c in cites] == [1, 2]
    assert cites[0].url == chunks[0].url
    assert invalid == []


def test_hallucinated_citation_is_reported(chunks):
    """A right fact with a wrong source is still a source the reader cannot
    check."""
    _, invalid = extract_citations("Do this [9].", chunks)
    assert invalid == [9]


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------

async def test_chinese_question_is_answered_in_chinese(provider):
    out = await answer("我收到一条奇怪的短信说我账户有问题这是真的吗",
                       app_lang="zh", provider=provider)
    assert out.refused is False
    assert out.lang == "zh"
    assert out.citations
    assert "您" in out.answer_md


async def test_vietnamese_question_is_answered_in_vietnamese(provider):
    out = await answer("Tôi bị lừa đảo mất tiền rồi", app_lang="vi",
                       provider=provider)
    assert out.refused is False
    assert out.lang == "vi"
    assert "ông/bà" in out.answer_md


async def test_medical_question_is_refused_in_chinese(provider):
    """A system that answers a medical question out of a digital-literacy
    knowledge base is more dangerous than one that answers nothing."""
    out, trace = await answer("我胸口痛应该吃什么药", app_lang="zh",
                              provider=provider, with_trace=True)
    assert out.refused is True
    assert trace.refused_at == "retrieval"
    assert out.answer_md == REFUSALS["zh"]
    assert not out.citations


async def test_refusal_offers_a_mentor(provider):
    for lang in ("zh", "vi"):
        out = await answer("我想买个新手机买哪个牌子好" if lang == "zh"
                           else "Tôi muốn mua điện thoại mới, nên mua hãng nào",
                           app_lang=lang, provider=provider)
        assert out.refused is True
        assert out.answer_md == REFUSALS[lang]


async def test_undecidable_query_refuses_without_retrieving(provider):
    """The app has a language picker. Guessing is worse than asking."""
    out, trace = await answer("myGov", provider=provider, with_trace=True)
    assert out.refused is True
    assert trace.refused_at == "language"
    assert trace.retrieved_ids == []


async def test_detection_carries_the_query_when_no_language_is_selected(provider):
    """Selecting a language is optional in the app, so this is real traffic."""
    out, trace = await answer("toi bi lua dao mat tien roi", provider=provider,
                              with_trace=True)
    assert out.lang == "vi"
    assert trace.lang_method == "lexicon"
    assert out.refused is False


async def test_trace_records_where_it_stopped(provider):
    _, trace = await answer("我胸口痛应该吃什么药", app_lang="zh",
                            provider=provider, with_trace=True)
    assert trace.refused_at == "retrieval"
    assert trace.verdict_reason
    assert trace.lang_method == "app"
