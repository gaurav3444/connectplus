"""connectplus-rag: trusted-knowledge and verification service for CONNECT Plus.

The public surface is what connectplus-llm imports. Stages 01-04 are the
offline ingest job and are reached through the CLI (`python -m rag.main`),
not from here - nothing outside this repo should be crawling or embedding.

    from rag import retrieve, verify, REFUSAL_THRESHOLD

    chunks, confidence = retrieve(query_en, lang, k)
    draft = generate(chunks, lang)          # connectplus-llm
    verdict = verify(draft, chunks, lang=lang)
    if not verdict.passed:
        ...  # drop the answer, offer a mentor. Never patch it.

That is the whole public surface. Everything else is internal.
"""

from rag.api import REFUSAL_THRESHOLD, retrieve, verify
from rag.schemas import Chunk, Retrieved, Verdict

__all__ = [
    "REFUSAL_THRESHOLD",
    "Chunk",
    "Retrieved",
    "Verdict",
    "retrieve",
    "verify",
]
