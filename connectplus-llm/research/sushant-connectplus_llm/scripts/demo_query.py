"""
Runs stage 07 (detect + translate + rewrite) against the fixture questions
and prints the result. Defaults to the offline stub (no key, no wifi); set
LLM_PROVIDER=gemini in .env to see real translation/rewriting.

Usage:
    python scripts/demo_query.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from connectplus_llm.config import FIXTURE_DIR, settings
from connectplus_llm.query import understand
from connectplus_llm.schemas import QueryRequest


async def main() -> None:
    fixtures = json.loads((FIXTURE_DIR / "query_fixtures.json").read_text(encoding="utf-8"))
    print(f"provider: {settings.provider}\n")

    for fx in fixtures:
        plan = await understand(QueryRequest(raw_query=fx["raw_query"]))
        if not plan.supported:
            print(f"[{fx['id']}] UNSUPPORTED -- refused before any LLM call")
            print(f"  original : {plan.query_original}")
            print()
            continue
        flag = " (DEGRADED)" if plan.degraded else ""
        print(f"[{fx['id']}] lang={plan.lang}{flag}")
        print(f"  original : {plan.query_original}")
        print(f"  rewritten: {plan.query_rewritten}")
        if fx.get("expect_concepts"):
            print(f"  expected concepts: {', '.join(fx['expect_concepts'])}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
