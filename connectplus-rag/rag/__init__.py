"""connectplus-rag: trusted-knowledge and verification service for CONNECT Plus.

The public surface is what connectplus-llm imports. Stages 01-04 are the
offline ingest job and are reached through the CLI (`python -m rag.main`),
not from here - nothing outside this repo should be crawling or embedding.

    from rag import understand, retrieve, keyword_query_for

    uq = understand("我的手机一直要求输入验证码")
    chunks, confidence = retrieve(
        uq.rewritten,
        keyword_query=keyword_query_for(uq),
        ...
    )

`verify` is deliberately absent rather than stubbed: stage 07 (guardrails,
"stage 08" in the whole-project stage map) is not built yet, and an
importable name that silently passes everything is worse than an ImportError
in a repo whose whole job is being the trust boundary.
"""

from rag.s05_retrieve import retrieve
from rag.s06_query import keyword_query_for, understand
from rag.schemas import Chunk, Retrieved, UnderstoodQuery

__all__ = [
    "Chunk",
    "Retrieved",
    "UnderstoodQuery",
    "keyword_query_for",
    "retrieve",
    "understand",
]
