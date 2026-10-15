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

    categories = browse_topics()                           # screen 3a, levels 1-2
    resources = browse(category_id, subcategory_id)        # screen 3a, level 3

That is the whole public surface. Everything else is internal.
"""

from rag.api import REFUSAL_THRESHOLD, browse, browse_topics, retrieve, verify
from rag.schemas import BrowseCategory, BrowsePage, BrowseSubcategory, Chunk, Resource, Retrieved, Verdict

__all__ = [
    "REFUSAL_THRESHOLD",
    "BrowseCategory",
    "BrowsePage",
    "BrowseSubcategory",
    "Chunk",
    "Resource",
    "Retrieved",
    "Verdict",
    "browse",
    "browse_topics",
    "retrieve",
    "verify",
]
