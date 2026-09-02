"""End-to-end orchestration: understand -> retrieve -> generate -> verify.

Stage 10 (``s10_answer.py``) is the FastAPI SSE endpoint and belongs to another
owner. This module is the part underneath it - the sequencing and the decisions
- so that the Vietnamese layer can be run and evaluated without an HTTP server,
and so stage 10 has one function to call rather than a procedure to reimplement.

The refusal decision is made in three places, and all three lead to the same
user-visible outcome:

1. Retrieval confidence below the threshold. The knowledge base does not cover
   the question. Nothing is generated at all - generating first and refusing
   afterwards wastes quota and risks a partial answer reaching the screen.
2. Generation failed or came back empty.
3. Verification rejected the draft. This verdict is not ours to argue with; the
   README is explicit that a model must not grade its own output, so whatever
   ``verify`` says, stands.

Swapping the stub for the real sibling repo is the ``_rag`` import below and
nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import rag_stub as _rag
from .providers import Provider, get_provider
from .s07_query import understand
from .s09_generate import extract_citations, generate, refusal
from .schemas import Answer, Chunk
from .vi.readability import score as readability_score
from .vi.termbase import audit

__all__ = ["answer", "PipelineTrace"]

# When ``connectplus-rag`` exists, this becomes:
#     from rag import retrieve, verify, REFUSAL_THRESHOLD
retrieve = _rag.retrieve
verify = _rag.verify
REFUSAL_THRESHOLD = _rag.REFUSAL_THRESHOLD


@dataclass
class PipelineTrace:
    """Everything the eval and the log need about one call.

    Kept separate from :class:`~llm.schemas.Answer` because the app never needs
    it and it should not cross the network to a client.
    """

    rewrite_source: str = ""
    lang_method: str = ""
    lang_confidence: float = 0.0
    retrieval_confidence: float = 0.0
    retrieved_ids: list[str] | None = None
    refused_at: str = ""
    verdict_reason: str = ""
    poisoned_chunk_ids: list[str] | None = None
    generation_error: str = ""


def _refusal_answer(query: str, lang: str, reason: str, *,
                    provider: Provider, understanding=None,
                    prompt_version: str = "vi.v1") -> Answer:
    """Build the Answer for any refusal path.

    One function so that a refusal looks identical to the client no matter
    which of the three checks triggered it. The reader must not be able to tell
    a thin knowledge base from a dead provider.
    """
    return Answer(
        answer_md=refusal(query, lang, provider=provider),
        citations=[],
        confidence=0.0,
        refused=True,
        refusal_reason=reason,
        chunk_ids=[],
        prompt_version=prompt_version,
        provider=provider.name,
        query_original=query,
        query_rewritten=understanding.rewritten_en if understanding else "",
        lang=lang,
    )


def answer(query: str, *, app_lang: str | None = None,
           provider: Provider | None = None, k: int = 3,
           with_trace: bool = False) -> Answer | tuple[Answer, PipelineTrace]:
    """Answer one question end to end.

    Args:
        query: The question as typed.
        app_lang: Language the client already knows the user chose. Always
            wins over detection.
        provider: Injected for testing and for the provider bake-off.
        k: Passages to retrieve.
        with_trace: Also return a :class:`PipelineTrace`.

    Returns:
        An :class:`~llm.schemas.Answer`, or ``(answer, trace)``.
    """
    provider = provider or get_provider()
    trace = PipelineTrace(retrieved_ids=[], poisoned_chunk_ids=[])

    u = understand(query, app_lang=app_lang, provider=provider)
    trace.rewrite_source = u.rewrite_source
    trace.lang_method = u.lang_method
    trace.lang_confidence = u.lang_confidence

    chunks: list[Chunk]
    chunks, confidence = retrieve(u.rewritten_en, u.lang, k=k)
    trace.retrieval_confidence = confidence
    trace.retrieved_ids = [c.id for c in chunks]

    # 1. Nothing trustworthy to answer from.
    if not chunks or confidence < REFUSAL_THRESHOLD:
        trace.refused_at = "retrieval"
        trace.verdict_reason = f"retrieval confidence {confidence} below {REFUSAL_THRESHOLD}"
        out = _refusal_answer(query, u.lang, "no trusted sources",
                              provider=provider, understanding=u)
        return (out, trace) if with_trace else out

    gen = generate(chunks, u, provider=provider)
    trace.poisoned_chunk_ids = gen.poisoned_chunk_ids
    trace.generation_error = gen.error

    # 2. The model did not produce anything usable.
    if not gen.text:
        trace.refused_at = "generation"
        trace.verdict_reason = gen.error or "empty generation"
        out = _refusal_answer(query, u.lang, "generation unavailable",
                              provider=provider, understanding=u,
                              prompt_version=gen.prompt_version)
        return (out, trace) if with_trace else out

    verdict = verify(gen.text, chunks, lang=u.lang)

    # 3. Verification said no. Not ours to overrule.
    if verdict.refused or not verdict.grounded:
        trace.refused_at = "verification"
        trace.verdict_reason = verdict.refusal_reason
        out = _refusal_answer(query, u.lang, verdict.refusal_reason or "not grounded",
                              provider=provider, understanding=u,
                              prompt_version=gen.prompt_version)
        return (out, trace) if with_trace else out

    citations, invalid = extract_citations(gen.text, chunks)
    source_text = " ".join(c.text for c in chunks)
    violations = audit(gen.text, source_text=source_text)
    read = readability_score(gen.text)

    out = Answer(
        answer_md=gen.text,
        citations=citations,
        confidence=min(confidence, verdict.confidence),
        refused=False,
        refusal_reason="",
        chunk_ids=[c.id for c in chunks],
        prompt_version=gen.prompt_version,
        provider=gen.provider,
        query_original=query,
        query_rewritten=u.rewritten_en,
        lang=u.lang,
        readability=read.as_dict(),
        term_violations=[v.__dict__ for v in violations],
    )
    if invalid:
        # A citation marker pointing at a source that was never supplied. Not
        # fatal to the answer, but it is a hallucination and the eval scores it.
        out.term_violations.append({
            "kind": "invalid_citation", "severity": "error",
            "found": str(invalid), "expected": f"1..{len(chunks)}",
            "note": "Cited a source number that was not in the prompt.",
        })
    return (out, trace) if with_trace else out
