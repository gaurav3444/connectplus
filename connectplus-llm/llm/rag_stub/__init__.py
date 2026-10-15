"""Stand-in for ``connectplus-rag``. **Temporary.**

The RAG team owns crawling, chunking, embedding, indexing, retrieval and
verification. None of it exists yet, so this module provides the two
functions the pipeline calls, with the agreed signatures:

    chunks, confidence = retrieve(query_en, lang, k=3)
    verdict            = verify(draft, chunks, lang=lang)

Swapping in the real package is a three-line change at the top of
``pipeline.py`` and nothing above it moves.

**Do not improve the scoring here.** It is a keyword overlap score over
sixteen hand-written passages. Making it cleverer would produce better
numbers that mean nothing, and would make it harder to notice when the real
retriever lands. The retrieval figures this produces describe the pipeline's
plumbing, not the knowledge base.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from ..schemas import Chunk, Verdict

__all__ = ["retrieve", "verify", "corpus", "poisoned_chunk",
           "REFUSAL_THRESHOLD"]

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "f06_retrieved.json"

# Below this, the knowledge base does not cover the question and the correct
# behaviour is to refuse. Tuned so the three out-of-scope questions in each
# eval set refuse and the in-scope ones do not.
REFUSAL_THRESHOLD = 0.18

_STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "to", "of", "in",
    "on", "at", "for", "from", "with", "and", "or", "if", "my", "me", "i",
    "you", "your", "it", "this", "that", "how", "what", "why", "when",
    "do", "does", "did", "can", "could", "should", "would", "get", "got",
    "keeps", "help", "about", "some", "any", "not", "no",
}

_WORD_RE = re.compile(r"[a-z][a-z'\-]+")


@lru_cache(maxsize=1)
def _data() -> dict:
    with _FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def corpus() -> list[Chunk]:
    """The fixture passages, as :class:`~llm.schemas.Chunk` objects."""
    return [Chunk(**c, score=0.0) for c in _data()["chunks"]]


@lru_cache(maxsize=1)
def poisoned_chunk() -> Chunk:
    """A chunk carrying an injection attempt, for the fencing tests."""
    return Chunk(**_data()["poisoned"], score=1.0)


def _terms(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall((text or "").lower())
            if w not in _STOPWORDS and len(w) > 2}


def _score(query_terms: set[str], chunk: Chunk) -> float:
    """Overlap between the query terms and the chunk, title weighted double.

    Deliberately crude. See the module docstring.
    """
    if not query_terms:
        return 0.0
    body = _terms(chunk.text)
    title = _terms(chunk.title)
    hits = len(query_terms & body) + 2 * len(query_terms & title)
    return min(1.0, hits / (len(query_terms) + 2))


def retrieve(query_en: str, lang: str = "en",
             k: int = 3) -> tuple[list[Chunk], float]:
    """Return the top ``k`` passages and a confidence for the whole result.

    Args:
        query_en: The English retrieval query from stage 07.
        lang: The senior's language. Unused here -- the knowledge base is
            English -- but part of the agreed signature, because the real
            retriever may filter by which pages have translations.
        k: How many passages to return.

    Returns:
        ``(chunks, confidence)``. A confidence below
        :data:`REFUSAL_THRESHOLD` means the knowledge base does not cover
        the question, and the caller must refuse without generating.
    """
    terms = _terms(query_en)
    scored = sorted(
        ((_score(terms, c), c) for c in corpus()),
        key=lambda pair: pair[0], reverse=True,
    )
    top = [(s, c) for s, c in scored[:k] if s > 0]
    if not top:
        return [], 0.0
    chunks = [Chunk(id=c.id, text=c.text, url=c.url, title=c.title,
                    domain=c.domain, score=round(s, 3)) for s, c in top]
    # Confidence is led by the best hit, with the rest contributing a little:
    # one strong match is a better signal than three weak ones.
    best = top[0][0]
    rest = sum(s for s, _ in top[1:]) / max(1, len(top) - 1) if len(top) > 1 else 0.0
    return chunks, round(min(1.0, best * 0.75 + rest * 0.25), 3)


def verify(draft: str, chunks: list[Chunk], lang: str = "en") -> Verdict:
    """Check a draft answer against the passages it was built from.

    The real implementation belongs to the RAG team and will compare claims
    against source text. This stub checks the two things it honestly can:
    that the answer cites at least one supplied source, and that it does not
    cite a source number that was never provided.

    This service does not argue with the verdict. A model must not grade its
    own output, which is exactly why this function lives outside the LLM
    repo in the real system.
    """
    if not draft.strip():
        return Verdict(grounded=False, confidence=0.0, refused=True,
                       refusal_reason="empty draft")
    if not chunks:
        return Verdict(grounded=False, confidence=0.0, refused=True,
                       refusal_reason="no sources supplied")

    cited = {int(n) for n in re.findall(r"\[(\d{1,2})\]", draft)}
    valid = {n for n in cited if 1 <= n <= len(chunks)}
    invalid = cited - valid

    if not valid:
        return Verdict(grounded=False, confidence=0.0, refused=True,
                       refusal_reason="answer cites no supplied source")
    if invalid:
        return Verdict(grounded=False, confidence=0.3, refused=True,
                       refusal_reason=f"answer cites sources that do not exist: "
                                      f"{sorted(invalid)}")

    coverage = len(valid) / len(chunks)
    return Verdict(grounded=True, confidence=round(0.6 + 0.4 * coverage, 3))
