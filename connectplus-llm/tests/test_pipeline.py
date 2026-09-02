"""End-to-end behaviour, including the paths that must never break."""

import pytest

from llm.pipeline import answer
from llm.providers.base import Provider, ProviderError
from llm.s09_generate import FALLBACK_REFUSAL_VI, extract_citations, refusal
from llm.schemas import Chunk


class DeadProvider(Provider):
    """A provider that always fails, standing in for an exhausted quota."""
    name = "dead"

    def complete(self, prompt, *, temperature=0.2, max_tokens=1024):
        raise ProviderError("quota exhausted")

    def healthy(self):
        return False


class EnglishProvider(Provider):
    """A provider that answers in the wrong language."""
    name = "english"

    def complete(self, prompt, *, temperature=0.2, max_tokens=1024):
        return "Sorry, we do not have information about that."


def test_answerable_question_is_answered(provider):
    a = answer("Tôi nhận được tin nhắn lạ", app_lang="vi", provider=provider)
    assert not a.refused
    assert a.citations
    assert a.chunk_ids
    assert a.lang == "vi"
    assert a.prompt_version


@pytest.mark.parametrize("q", [
    "Tôi bị đau ngực, tôi nên uống thuốc gì?",
    "Làm sao để bảo lãnh con tôi sang Úc định cư?",
    "Tôi nên mua điện thoại hãng nào thì tốt?",
])
def test_out_of_scope_questions_are_refused(q, provider):
    """The three questions the eval set exists to protect. Answering any of
    them from a digital-literacy knowledge base is worse than answering
    nothing, because the reader will act on it."""
    a = answer(q, app_lang="vi", provider=provider)
    assert a.refused
    assert a.citations == []


def test_refusal_is_a_real_message_not_an_error(provider):
    a = answer("Tôi bị đau ngực", app_lang="vi", provider=provider)
    assert a.answer_md.strip()
    assert "ông/bà" in a.answer_md
    assert "Error" not in a.answer_md and "None" not in a.answer_md


def test_refusal_offers_the_mentor():
    """Required by the README and by the style guide: a refusal ends with a
    way forward, not a dead end."""
    assert "người hướng dẫn" in FALLBACK_REFUSAL_VI


def test_dead_provider_degrades_to_a_refusal_not_a_crash():
    """The demo must survive a dead quota. The user sees a plain sentence."""
    a = answer("Tôi nhận được tin nhắn lạ", app_lang="vi",
               provider=DeadProvider())
    assert a.refused
    assert a.answer_md == FALLBACK_REFUSAL_VI


def test_refusal_falls_back_when_the_model_answers_in_english():
    """A refusal in English strands the reader just as badly as a wrong
    answer, so the wrong-language response is discarded."""
    assert refusal("bất kỳ", "vi", provider=EnglishProvider()) == FALLBACK_REFUSAL_VI


def test_trace_records_where_a_refusal_happened(provider):
    _, trace = answer("Tôi bị đau ngực", app_lang="vi",
                      provider=provider, with_trace=True)
    assert trace.refused_at == "retrieval"
    assert trace.verdict_reason


def test_app_language_is_honoured_over_detection(provider):
    _, trace = answer("toi bi lua dao", app_lang="vi",
                      provider=provider, with_trace=True)
    assert trace.lang_method == "app"


def test_hallucinated_citation_is_reported():
    chunks = [Chunk("a", "http://a", "A", "d.gov.au", "text")]
    cites, invalid = extract_citations("Câu này [1] và câu kia [7].", chunks)
    assert [c.n for c in cites] == [1]
    assert invalid == [7]


def test_answer_carries_the_full_trace_fields(provider):
    a = answer("Tôi muốn gọi video cho cháu tôi", app_lang="vi",
               provider=provider)
    for field in ("prompt_version", "provider", "query_original",
                  "query_rewritten", "lang"):
        assert getattr(a, field), f"{field} is empty"
    assert a.readability.get("grade")
