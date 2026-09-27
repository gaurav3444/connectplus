"""connectplus-rag: trusted-knowledge and verification service for CONNECT Plus.

The public surface is what connectplus-llm imports. Stages 01-04 are the
offline ingest job and are reached through the CLI (`python -m rag.main`),
not from here - nothing outside this repo should be crawling or embedding.

    from rag import retrieve, verify

    chunks, confidence = retrieve(query_en, lang, k)
    draft = generate(chunks, lang)          # connectplus-llm
    verdict = verify(draft, chunks)
    if not verdict.passed:
        ...  # drop the answer, offer a mentor. Never patch it.

`understand` and `keyword_query_for` (stage 06) are here too for callers
that want this repo to do the translate-and-rewrite step instead.

That is the whole public surface. Everything else is internal.
"""

from rag.api import retrieve, verify
from rag.s06_query import keyword_query_for, understand
from rag.schemas import Chunk, Retrieved, UnderstoodQuery, Verdict

__all__ = [
    "Chunk",
    "Retrieved",
    "UnderstoodQuery",
    "Verdict",
    "keyword_query_for",
    "retrieve",
    "understand",
    "verify",
]
