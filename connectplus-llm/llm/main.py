"""One question from the command line, no server.

    python -m llm.main "我收到一条奇怪的短信"
    python -m llm.main "toi bi lua dao" --lang vi
    python -m llm.main "我胸口痛应该吃什么药" --lang zh --trace

The third is the check worth demonstrating by hand: a question the knowledge
base cannot cover comes back as a plain refusal with a mentor offer, and
``--trace`` shows exactly where it refused and why.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from .pipeline import answer
from .providers import ProviderError, get_provider

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def _run(args) -> int:
    try:
        provider = get_provider(args.provider)
    except ProviderError as exc:
        print(f"Provider unavailable: {exc}", file=sys.stderr)
        return 2

    out, trace = await answer(args.query, app_lang=args.lang,
                              provider=provider, k=args.k, with_trace=True)

    print()
    print(out.answer_md)

    if out.citations:
        print("\n来源 / Nguồn / Sources")
        for c in out.citations:
            print(f"  [{c.n}] {c.title} - {c.url}")

    print(f"\nlang={out.lang}  refused={out.refused}  "
          f"confidence={out.confidence}  provider={out.provider}  "
          f"prompt={out.prompt_version}")

    if out.readability:
        print(f"readability={out.readability['score']} "
              f"({out.readability['grade']})")

    errors = [v for v in out.term_violations if v.get("severity") == "error"]
    if errors:
        print(f"\n{len(errors)} termbase error(s):")
        for v in errors[:6]:
            print(f"  [{v['kind']}] found {v['found']!r}, "
                  f"expected {v['expected']!r} - {v.get('note', '')}")

    if args.trace:
        print("\ntrace:")
        print(json.dumps(trace.as_dict(), indent=2, ensure_ascii=False))

    await provider.aclose()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m llm.main")
    ap.add_argument("query")
    ap.add_argument("--lang", default=None, choices=["zh", "zh_hant", "vi", "en"],
                    help="the language the app already knows was selected; "
                         "omit to exercise detection")
    ap.add_argument("--provider", default=None,
                    choices=["mock", "stub", "gemini", "ollama"])
    ap.add_argument("-k", type=int, default=3)
    ap.add_argument("--trace", action="store_true")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
