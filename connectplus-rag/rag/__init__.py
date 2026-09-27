"""connectplus-rag: trusted-knowledge and verification service for CONNECT Plus.

The public surface is what connectplus-llm imports. Stages 01-04 are the
offline ingest job and are reached through the CLI (`python -m rag.main`),
not from here - nothing outside this repo should be crawling or embedding.

    from rag import understand, retrieve, verify, keyword_query_for

    uq = understand("我的手机一直要求输入验证码")
    chunks, confidence = retrieve(
        uq.rewritten,
        keyword_query=keyword_query_for(uq),
        ...
    )

    verdict = verify(answer_md, chunks, confidence)
    if not verdict.passed:
        ...  # drop the answer, offer a mentor. Never patch it.

That is the whole public surface. Everything else is internal.
"""

from rag.s05_retrieve import retrieve
from rag.s06_query import keyword_query_for, understand
from rag.s07_verify import verify
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
