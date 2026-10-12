"""
Local demo server for stage 07 only -- detect language, translate + rewrite.
No retrieval, no answer generation, no RAG: this serves demo.html and one
endpoint that calls understand() directly.

Run:
    uvicorn scripts.demo_server:app --reload --port 8000
Then open http://localhost:8000 in a browser.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from connectplus_llm.config import settings
from connectplus_llm.query import understand
from connectplus_llm.schemas import QueryRequest

app = FastAPI()

DEMO_HTML = Path(__file__).resolve().parent.parent / "demo.html"


class AskBody(BaseModel):
    raw_query: str


@app.get("/")
def index():
    return FileResponse(DEMO_HTML)


@app.post("/understand")
async def understand_endpoint(body: AskBody):
    started = time.perf_counter()
    plan = await understand(QueryRequest(raw_query=body.raw_query))
    latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "query_original": plan.query_original,
        "query_rewritten": plan.query_rewritten,
        "lang": plan.lang,
        "degraded": plan.degraded,
        "supported": plan.supported,
        "provider": settings.provider,
        "latency_ms": latency_ms,
    }
