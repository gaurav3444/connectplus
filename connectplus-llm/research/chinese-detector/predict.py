"""
Check whether typed text is Chinese, using the model trained by train.py.

This is the manual-check CLI. The actual integration point for
connectplus-llm is the `chinese_detector` package (see its __init__.py) --
this script is a thin wrapper around the same code.

Usage:
    python predict.py "怎么把手机上的字变大"
    python predict.py --interactive
"""

from __future__ import annotations

import argparse
import sys

from chinese_detector import classify

sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252, which can't print Chinese


def _print_result(text: str) -> None:
    result = classify(text)
    verdict = "CHINESE" if result.lang == "zh" else "NOT CHINESE"
    print(f"{verdict}  (confidence {result.confidence:.1%})  scores={result.scores}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", help="text to check")
    ap.add_argument("--interactive", action="store_true")
    args = ap.parse_args()

    if args.interactive or not args.text:
        print("Type text and press Enter to check it (Ctrl+C to quit).")
        try:
            while True:
                text = input("> ").strip()
                if text:
                    _print_result(text)
        except (KeyboardInterrupt, EOFError):
            print()
        return

    _print_result(args.text)


if __name__ == "__main__":
    main()
