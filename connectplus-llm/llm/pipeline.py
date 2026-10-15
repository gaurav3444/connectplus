"""End-to-end orchestration: understand, retrieve, generate, verify.

Stage 10 (the FastAPI SSE endpoint) belongs to another owner. This module is
the part underneath it -- the sequencing and the decisions -- so the language
lanes can be run and evaluated without an HTTP server, and so stage 10 has
one function to call rather than a procedure to reimplement.

The refusal decision is made in four places, and all four lead to the same
user-visible outcome:

1. **Unsupported language.** Detection returned ``und``, or a language with
   no lane. Nothing is retrieved and nothing is generated. The caller should
   show the language picker -- the app has one, and asking costs one tap.
2. **Retrieval confidence below the threshold.** The knowledge base does not
   cover the question. Generating first and refusing afterwards wastes quota
   and risks a partial answer reaching the screen.
3. **Generation failed, came back empty, or came back in the wrong
   language.**
4. **Verification rejected the draft.** This verdict is not ours to argue
   with: a model must not grade its own output, so whatever ``verify`` says,
   stands.

Swapping the stub for the real sibling repo is the ``_rag`` import below and
nothing else.
"""

from __future__ import annotations

import os
import time

# CONNECTPLUS_RAG=real uses the real connectplus-rag package (needs its
# DATABASE_URL and models). Anything else keeps the offline stub, which is
# what the test suite and the no-network demo run against.
if os.getenv("CONNECTPLUS_RAG", "stub").lower() == "real":
    from . import rag_adapter as _rag
else:
    from . import rag_stub as _rag
from .lanes import get_lane
from .lang.detect import detect
from .providers import Provider, get_provider
from .providers.nllb_fallback import maybe_translate_fallback
from .s07_query import understand
from .s09_generate import extract_citations, generate, refusal
from .schemas import Answer, Chunk, PipelineTrace

__all__ = ["answer", "PipelineTrace"]

# When ``connectplus-rag`` ships as an importable package, this becomes:
#     from rag import retrieve, verify, REFUSAL_THRESHOLD
retrieve = _rag.retrieve
verify = _rag.verify
REFUSAL_THRESHOLD = _rag.REFUSAL_THRESHOLD


# Added AFTER verification, never generated. The mentor offer is not a fact
# from any source page, so a model-written one can never pass the grounding
# check (real run: 0.002 in English) and dragged every answer it appeared in
# down to "ungrounded". The prompts now tell the model not to write it.
MENTOR_LINE = {
    "zh": "如果您还需要帮助，我们可以帮您联系一位会说中文的辅导员。",
    "zh_hant": "如果您還需要幫助，我們可以幫您聯絡一位會說中文的輔導員。",
    "vi": "Nếu ông/bà cần giúp thêm, chúng tôi có thể kết nối ông/bà với một người hướng dẫn nói tiếng Việt.",
    "en": "If you need more help, we can connect you with a mentor.",
}


def _with_mentor_line(text: str, lang: str) -> str:
    line = MENTOR_LINE.get(lang)
    if not line or line.rstrip("。.") in text:   # the mock already writes one
        return text
    return f"{text.rstrip()}\n\n{line}"


async def _refusal_answer(query: str, lang: str, reason: str, *,
                          provider: Provider, understanding=None,
                          prompt_version: str = "") -> Answer:
    """Build the Answer for any refusal path.

    One function, so a refusal looks identical to the senior no matter which
    check triggered it. The reader must not be able to tell a thin knowledge
    base from a dead provider.
    """
    text = await refusal(query, lang, provider=provider)
    return Answer(
        answer_md=text,
        citations=[],
        confidence=0.0,
        refused=True,
        refusal_reason=reason,
        chunk_ids=[],
        prompt_version=prompt_version or f"{lang}.v1",
        provider=provider.name,
        query_original=query,
        query_rewritten=understanding.rewritten_en if understanding else "",
        lang=lang,
    )


async def answer(query: str, *, app_lang: str | None = None,
                 provider: Provider | None = None, k: int = 3,
                 with_trace: bool = False):
    """Answer one question end to end.

    Args:
        query: The question as typed.
        app_lang: Language the app already knows was selected. Always wins
            over detection. Pass ``None`` when the senior never chose one --
            selecting a language is optional in CONNECT Plus.
        provider: Injected for testing and for the provider bake-off.
        k: Passages to retrieve.
        with_trace: Also return a :class:`~llm.schemas.PipelineTrace`.

    Returns:
        An :class:`~llm.schemas.Answer`, or ``(answer, trace)``.
    """
    started = time.perf_counter()
    provider = provider or get_provider()
    trace = PipelineTrace(provider=provider.name, model=provider.model)

    def _done(out: Answer) -> Answer | tuple[Answer, PipelineTrace]:
        trace.latency_ms = int((time.perf_counter() - started) * 1000)
        trace.provider = provider.name
        trace.model = provider.model
        return (out, trace) if with_trace else out

    # 1. Language. An unsupported or undecidable query stops here.
    detection = detect(query, app_lang=app_lang)
    trace.lang_method = detection.method
    trace.lang_confidence = detection.confidence
    trace.lang_detail = detection.detail

    if not detection.supported:
        trace.refused_at = "language"
        trace.verdict_reason = detection.detail or "language not supported"
        # Refuse in English: we genuinely do not know what the senior reads,
        # and the app should show the language picker rather than guess.
        out = await _refusal_answer(query, "en", "unsupported language",
                                    provider=provider)
        out.lang = detection.lang
        return _done(out)

    u = await understand(query, app_lang=detection.lang, provider=provider)
    u.lang_method = detection.method
    u.lang_confidence = detection.confidence
    trace.rewrite_source = u.rewrite_source

    # 2. Nothing trustworthy to answer from.
    chunks: list[Chunk]
    chunks, confidence = retrieve(u.rewritten_en, u.lang, k=k)
    trace.retrieval_confidence = confidence
    trace.retrieved_ids = [c.id for c in chunks]

    if not chunks or confidence < REFUSAL_THRESHOLD:
        trace.refused_at = "retrieval"
        trace.verdict_reason = (f"retrieval confidence {confidence} below "
                                f"{REFUSAL_THRESHOLD}")
        out = await _refusal_answer(query, u.lang, "no trusted sources",
                                    provider=provider, understanding=u)
        return _done(out)

    # 3. The model did not produce anything usable.
    gen = await generate(chunks, u, provider=provider)
    trace.poisoned_chunk_ids = gen.poisoned_chunk_ids
    trace.generation_error = gen.error

    if not gen.text:
        trace.refused_at = "generation"
        trace.verdict_reason = gen.error or "empty generation"
        out = await _refusal_answer(query, u.lang, "generation unavailable",
                                    provider=provider, understanding=u,
                                    prompt_version=gen.prompt_version)
        return _done(out)

    # Optional, additive step: when the mock provider served a zh_hant
    # answer, its own docstring records that it echoes source text in
    # English rather than translating it. If CONNECTPLUS_NLLB_MODEL_DIR is
    # set, translate those lines with the fine-tuned NLLB-200 model rather
    # than shipping them to a senior in a language they cannot read. A no-op
    # for everyone who has not opted in: unset env var, non-mock provider,
    # or any lane other than zh_hant all return gen.text unchanged. See
    # llm/providers/nllb_fallback.py for the full reasoning.
    gen.text = maybe_translate_fallback(gen.text, lang=u.lang,
                                        provider_name=provider.name)

    # 4. Verification said no. Not ours to overrule.
    verdict = verify(gen.text, chunks, lang=u.lang)
    if verdict.refused or not verdict.grounded:
        trace.refused_at = "verification"
        trace.verdict_reason = verdict.refusal_reason
        out = await _refusal_answer(query, u.lang,
                                    verdict.refusal_reason or "not grounded",
                                    provider=provider, understanding=u,
                                    prompt_version=gen.prompt_version)
        return _done(out)

    lane = get_lane(u.lang)
    citations, invalid = extract_citations(gen.text, chunks)
    source_text = " ".join(c.text for c in chunks)
    violations = lane.audit(gen.text, source_text=source_text)
    read = lane.readability(gen.text)

    out = Answer(
        answer_md=_with_mentor_line(gen.text, u.lang),
        citations=citations,
        confidence=round(min(confidence, verdict.confidence), 3),
        refused=False,
        refusal_reason="",
        chunk_ids=[c.id for c in chunks],
        prompt_version=gen.prompt_version,
        provider=gen.provider,
        query_original=query,
        query_rewritten=u.rewritten_en,
        lang=u.lang,
        readability=read.as_dict() if read is not None else None,
        term_violations=[v.as_dict() for v in violations],
    )
    if invalid:
        # A citation marker pointing at a source that was never supplied.
        # Not fatal to the answer, but it is a hallucination and the eval
        # scores it.
        out.term_violations.append({
            "kind": "invalid_citation", "severity": "error",
            "found": str(invalid), "expected": f"1..{len(chunks)}",
            "note": "Cited a source number that was not in the prompt.",
        })
    return _done(out)
