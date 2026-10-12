"""Single question from the command line, no server.

    python -m llm.main "toi bi lua dao"
    python -m llm.main "Điện thoại cứ đòi mã" --lang vi --provider gemini
    python -m llm.main "Tôi bị đau ngực" --trace

Useful for the by-hand check the README asks for: ask something the knowledge
base cannot cover and confirm you get a plain refusal plus a mentor offer,
rather than a plausible invention.
"""

from __future__ import annotations

import argparse
import json
import sys

from .pipeline import answer
from .providers import ProviderError, get_provider


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m llm.main")
    ap.add_argument("query", help="the question, in the user's own language")
    ap.add_argument("--lang", default=None,
                    help="language the app knows the user chose (e.g. vi). "
                         "Omit to let detection decide.")
    ap.add_argument("--provider", default=None,
                    choices=["gemini", "ollama", "mock"])
    ap.add_argument("--trace", action="store_true",
                    help="print the pipeline trace as JSON")
    args = ap.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        provider = get_provider(args.provider, strict=bool(args.provider))
    except ProviderError as exc:
        print(f"Provider error: {exc}", file=sys.stderr)
        return 2

    ans, trace = answer(args.query, app_lang=args.lang, provider=provider,
                        with_trace=True)

    print()
    print(ans.answer_md)
    print()
    if ans.citations:
        print("Nguồn / Sources")
        for c in ans.citations:
            print(f"  [{c.n}] {c.title} - {c.url}")
        print()
    print(f"refused={ans.refused}  confidence={ans.confidence}  "
          f"provider={ans.provider}  prompt={ans.prompt_version}")
    if ans.readability:
        print(f"readability={ans.readability['score']} "
              f"({ans.readability['grade']})")
    if ans.term_violations:
        print("term violations:")
        for v in ans.term_violations:
            print(f"  [{v['severity']}] {v['kind']}: {v['found']}")
    if args.trace:
        print("\ntrace:")
        print(json.dumps(trace.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
