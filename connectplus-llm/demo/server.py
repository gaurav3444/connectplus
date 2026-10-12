"""Demo server for the whole pipeline.

    uvicorn demo.server:app --reload --port 8000
    then open http://localhost:8000

This is **not** stage 10. Stage 10 is the production FastAPI SSE endpoint and
belongs to another owner; this is a testing surface that returns the complete
trace in one JSON response so every decision the pipeline made is visible on
screen. The async provider client means these endpoints do not block the
event loop, which is the same reason stage 10 will want it.

Three things the page is built to demonstrate, in this order of importance:

1. A good answer, in the senior's language, grounded in retrieved sources.
2. **A refusal.** A question the knowledge base cannot cover returns a plain
   sentence and a mentor offer, not an invention. This is the one that
   matters.
3. A degraded run, where the provider is unavailable and retrieval still
   happens from the deterministic termbase.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI                                    # noqa: E402
from fastapi.responses import FileResponse, JSONResponse       # noqa: E402
from pydantic import BaseModel, Field                          # noqa: E402

from llm.lanes import available_lanes                          # noqa: E402
from llm.pipeline import REFUSAL_THRESHOLD, answer             # noqa: E402
from llm.providers import ProviderError, get_provider          # noqa: E402
from llm.rag_stub import corpus                                # noqa: E402
from llm.schemas import LANGUAGE_NAMES                         # noqa: E402
from llm.tracing import summarise                              # noqa: E402

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"

app = FastAPI(title="CONNECT Plus - pipeline demo")


class AskBody(BaseModel):
    query: str = Field(max_length=500)
    # None means the senior never chose a language, which is allowed: the
    # selector is optional in the app, so detection must carry that traffic.
    lang: str | None = None
    provider: str | None = None
    k: int = 3


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX)


@app.get("/api/meta")
def meta() -> dict:
    """What the page needs to build its controls."""
    try:
        provider = get_provider()
        provider_name, model = provider.name, provider.model
    except ProviderError as exc:
        provider_name, model = "unavailable", str(exc)[:120]
    return {
        "languages": [{"code": c, "name": LANGUAGE_NAMES[c]}
                      for c in available_lanes()],
        "provider": provider_name,
        "model": model,
        "refusal_threshold": REFUSAL_THRESHOLD,
        "corpus_size": len(corpus()),
        "samples": SAMPLES,
    }


@app.get("/api/traces")
def traces() -> dict:
    """Provider call counts and latencies, for the provenance panel."""
    return summarise()


@app.post("/api/ask")
async def ask(body: AskBody) -> JSONResponse:
    """Run one question and return the answer plus the full trace."""
    if not body.query.strip():
        return JSONResponse({"error": "Type a question first."}, status_code=400)

    try:
        provider = get_provider(body.provider)
    except ProviderError as exc:
        return JSONResponse(
            {"error": f"Provider unavailable: {exc}"}, status_code=503)

    out, trace = await answer(body.query, app_lang=body.lang,
                              provider=provider, k=body.k, with_trace=True)

    errors = [v for v in out.term_violations if v.get("severity") == "error"]
    warnings = [v for v in out.term_violations if v.get("severity") == "warn"]

    return JSONResponse({
        "answer": out.as_dict(),
        "trace": trace.as_dict(),
        "violations": {"errors": errors, "warnings": warnings},
        "refusal_threshold": REFUSAL_THRESHOLD,
    })


# The scripted runs, grouped so the page can offer them as one-click demos.
SAMPLES = [
    {
        "group": "Good answer",
        "tone": "ok",
        "blurb": "Grounded in retrieved sources, answered in the reader's "
                 "language, every claim cited.",
        "items": [
            {"lang": "zh", "label": "中文 · scam text",
             "query": "我收到一条奇怪的短信说我账户有问题这是真的吗"},
            {"lang": "zh", "label": "中文 · myGov password",
             "query": "myGov密码忘记了怎么办"},
            {"lang": "vi", "label": "Tiếng Việt · verification code",
             "query": "Ngân hàng gọi bảo tôi đọc mã xác minh cho họ, có nên không"},
            {"lang": "en", "label": "English · block a number",
             "query": "how do I block a number that keeps calling me"},
        ],
    },
    {
        "group": "Refusal — the one that matters",
        "tone": "warn",
        "blurb": "The knowledge base cannot cover these. Correct behaviour is "
                 "a plain sentence and a mentor offer, never a plausible "
                 "invention.",
        "items": [
            {"lang": "zh", "label": "中文 · medical",
             "query": "我胸口痛应该吃什么药"},
            {"lang": "zh", "label": "中文 · which phone to buy",
             "query": "我想买个新手机买哪个牌子好"},
            {"lang": "vi", "label": "Tiếng Việt · medical",
             "query": "Tôi bị đau ngực, tôi nên uống thuốc gì?"},
        ],
    },
    {
        "group": "Detection — no language selected",
        "tone": "info",
        "blurb": "Selecting a language is optional in the app, so detection "
                 "carries real traffic. These run with no language set.",
        "items": [
            {"lang": None, "label": "No diacritics · Vietnamese",
             "query": "toi bi lua dao mat tien roi"},
            {"lang": None, "label": "Han characters · Chinese",
             "query": "怎么举报诈骗电话"},
            {"lang": None, "label": "Undecidable → show the picker",
             "query": "myGov"},
            {"lang": None, "label": "Out of scope → refuse",
             "query": "안녕하세요 도와주세요"},
        ],
    },
]
