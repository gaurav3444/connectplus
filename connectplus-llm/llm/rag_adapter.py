"""Adapter between connectplus-llm and the real connectplus-rag package.

The two repos agreed on function names but not on data shapes:

* rag.retrieve() returns pydantic ``Retrieved`` objects (url is HttpUrl,
  plus doc_id, lang, heading_path, ...). llm expects its own frozen
  ``Chunk`` dataclass with a plain-string url.
* rag.verify() returns ``Verdict(passed, reason, grounded_score, ...)``.
  llm expects ``Verdict(grounded, confidence, refused, refusal_reason)``.
* rag.verify() needs the full Retrieved objects back, not llm's slim Chunk.

This file converts at the boundary so nothing else in llm/ has to change.
"""
from __future__ import annotations

from collections import OrderedDict

import rag

from .schemas import Chunk, Verdict

REFUSAL_THRESHOLD = rag.REFUSAL_THRESHOLD

# llm's Chunk is too slim for rag.verify(), so remember the originals by id.
_originals: "OrderedDict[str, rag.Retrieved]" = OrderedDict()
_MAX_REMEMBERED = 500


def _remember(r: "rag.Retrieved") -> None:
    _originals[r.id] = r
    _originals.move_to_end(r.id)
    while len(_originals) > _MAX_REMEMBERED:
        _originals.popitem(last=False)


def retrieve(query_en: str, lang: str = "en", k: int = 5) -> tuple[list[Chunk], float]:
    results, confidence = rag.retrieve(query_en, lang, k)
    chunks = []
    for r in results:
        _remember(r)
        chunks.append(Chunk(id=r.id, text=r.text, url=str(r.url),
                            title=r.title, domain=r.domain, score=r.score))
    return chunks, confidence


def verify(draft: str, chunks: list[Chunk], lang: str = "en") -> Verdict:
    try:
        originals = [_originals[c.id] for c in chunks]
    except KeyError as e:
        # Fail closed: a chunk we did not retrieve cannot be verified.
        return Verdict(grounded=False, confidence=0.0, refused=True,
                       refusal_reason=f"unknown chunk id {e}")
    v = rag.verify(draft, originals, lang=lang)
    return Verdict(grounded=v.passed, confidence=v.confidence,
                   refused=not v.passed, refusal_reason=v.reason or "")
