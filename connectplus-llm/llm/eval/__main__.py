"""Command line for the Vietnamese eval.

    python -m llm.eval                      # answer eval, provider from .env
    python -m llm.eval --provider mock      # no key needed, plumbing only
    python -m llm.eval --provider gemini    # the number that goes in the report
    python -m llm.eval --provider ollama    # the offline fallback, in Vietnamese
    python -m llm.eval detect               # language detection vs langdetect
    python -m llm.eval --json out/run.json  # machine-readable, for diffing runs

Re-run this on every prompt, termbase, rewrite or chunking change, including
changes made in ``connectplus-rag``. It is the only signal that says whether a
change helped, and comparing two runs by eye is how prompt work goes in circles.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..providers import ProviderError, get_provider
from ..vi.detect import detect
from .metrics import score_question, summarise

_DATA = Path(__file__).parent / "data"

_TICK, _CROSS, _DASH = "PASS", "FAIL", "  - "


def _flag(value) -> str:
    if value is None:
        return "  . "
    return " ok " if value else " XX "


# ---------------------------------------------------------------------------
# Answer eval
# ---------------------------------------------------------------------------

def run_answers(provider_name: str | None, limit: int | None,
                json_path: str | None) -> int:
    from ..pipeline import answer  # imported late so `detect` needs no provider

    with (_DATA / "questions_vi.json").open(encoding="utf-8") as fh:
        questions = json.load(fh)["questions"]
    if limit:
        questions = questions[:limit]

    try:
        provider = get_provider(provider_name, strict=bool(provider_name))
    except ProviderError as exc:
        print(f"Cannot start provider {provider_name!r}: {exc}", file=sys.stderr)
        return 2

    print(f"\nVietnamese answer eval - provider={provider.name} "
          f"- {len(questions)} questions")
    if provider.name == "mock":
        print("NOTE: the mock provider copies source text; its scores measure "
              "the plumbing, not model quality.")
    print("NOTE: retrieval and verification are the stub in llm/rag_stub, not "
          "connectplus-rag.\n")

    header = (f"{'id':<8}{'intent':<28}{'lang':>6}{'rewr':>6}{'hit3':>6}"
              f"{'refu':>6}{'cite':>6}{'regi':>6}{'term':>6}{'read':>7}")
    print(header)
    print("-" * len(header))

    results = []
    for q in questions:
        ans, trace = answer(q["query_vi"], app_lang="vi",
                            provider=provider, with_trace=True)
        r = score_question(q, ans, trace)
        results.append(r)
        print(f"{r.id:<8}{r.intent[:27]:<28}"
              f"{_flag(r.lang_ok):>6}{_flag(r.rewrite_ok):>6}{_flag(r.hit_at_3):>6}"
              f"{_flag(r.refusal_ok):>6}{_flag(r.cited_ok):>6}"
              f"{_flag(r.register_ok):>6}{_flag(r.terms_ok):>6}"
              f"{r.readability:>7.0f}")

    summary = summarise(results)
    print("\nSummary")
    print("-------")
    for key in ("language_correct", "rewrite_contains_concept", "hit_at_3",
                "refusal_correct", "citations_valid", "register_correct",
                "terms_correct"):
        s = summary[key]
        print(f"  {key:<26} {s['rate']:>6.1%}  (n={s['n']})")
    print(f"  {'readability_mean':<26} {summary['readability_mean']:>6.1f}"
          f"  ({summary['readability_hard_count']} graded hard)")

    if summary["under_refused_ids"]:
        print(f"\n  !! ANSWERED WHAT IT SHOULD HAVE REFUSED: "
              f"{summary['under_refused_ids']}")
    if summary["over_refused_ids"]:
        print(f"  !  refused what it could have answered: "
              f"{summary['over_refused_ids']}")

    failures = [r for r in results if r.notes]
    if failures:
        print("\nNotes")
        print("-----")
        for r in failures:
            for n in r.notes:
                print(f"  {r.id}: {n}")

    if json_path:
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            json.dump({"provider": provider.name, "summary": summary,
                       "results": [r.as_dict() for r in results]},
                      fh, ensure_ascii=False, indent=2)
        print(f"\nWrote {out}")

    # Non-zero exit on the failure that matters most, so this can gate a commit.
    return 1 if summary["under_refused_ids"] else 0


# ---------------------------------------------------------------------------
# Detection eval
# ---------------------------------------------------------------------------

def run_detect(json_path: str | None) -> int:
    with (_DATA / "detect_cases.json").open(encoding="utf-8") as fh:
        cases = json.load(fh)["cases"]

    try:
        from langdetect import detect as ld_detect, DetectorFactory
        DetectorFactory.seed = 0
        have_baseline = True
    except ImportError:
        have_baseline = False

    def baseline(text: str) -> str:
        """langdetect's answer, with regional tags folded to the primary
        subtag so 'zh-cn' is scored as a correct 'zh' rather than a miss."""
        if not have_baseline:
            return "n/a"
        try:
            return ld_detect(text).split("-")[0]
        except Exception:
            return "err"

    print(f"\nLanguage detection eval - {len(cases)} cases")
    print("Baseline is langdetect, the library the README names as the fallback.\n")
    header = f"{'expect':>7}{'ours':>7}{'langdetect':>12}  {'hard':<5} text"
    print(header)
    print("-" * (len(header) + 20))

    ours_right = base_right = 0
    hard_ours = hard_base = hard_n = 0
    rows = []
    for c in cases:
        got = detect(c["text"]).lang
        base = baseline(c["text"])
        # langdetect has no "und"; a short meaningless string is a pass for the
        # baseline if it errors out, since that is honest behaviour too.
        base_ok = (base == c["expect"]) or (c["expect"] == "und" and base == "err")
        ok = got == c["expect"]
        ours_right += ok
        base_right += base_ok
        if c["hard"]:
            hard_n += 1
            hard_ours += ok
            hard_base += base_ok
        rows.append({"text": c["text"], "expect": c["expect"], "ours": got,
                     "langdetect": base, "hard": c["hard"],
                     "ours_ok": ok, "langdetect_ok": base_ok})
        mark = "" if ok else "   <-- ours wrong"
        print(f"{c['expect']:>7}{got:>7}{base:>12}  {str(c['hard']):<5} "
              f"{c['text'][:38]}{mark}")

    n = len(cases)
    print(f"\n  ours        {ours_right}/{n} = {ours_right/n:.1%}")
    if have_baseline:
        print(f"  langdetect  {base_right}/{n} = {base_right/n:.1%}")
        print(f"\n  on the {hard_n} hard cases (no diacritics, or very short):")
        print(f"    ours        {hard_ours}/{hard_n} = {hard_ours/hard_n:.1%}")
        print(f"    langdetect  {hard_base}/{hard_n} = {hard_base/hard_n:.1%}")
    else:
        print("  langdetect not installed - baseline skipped "
              "(pip install langdetect)")

    if json_path:
        out = Path(json_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            json.dump({"accuracy_ours": ours_right / n,
                       "accuracy_langdetect": base_right / n if have_baseline else None,
                       "rows": rows}, fh, ensure_ascii=False, indent=2)
        print(f"\nWrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m llm.eval",
        description="Vietnamese evaluation harness for connectplus-llm.")
    parser.add_argument("mode", nargs="?", default="answers",
                        choices=["answers", "detect"],
                        help="answers (default) or detect")
    parser.add_argument("--provider", default=None,
                        choices=["gemini", "ollama", "mock"],
                        help="override $LLM_PROVIDER; fails loudly if unusable")
    parser.add_argument("--limit", type=int, default=None,
                        help="run only the first N questions")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="also write results to this JSON file")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if args.mode == "detect":
        return run_detect(args.json_path)
    return run_answers(args.provider or os.getenv("LLM_PROVIDER"),
                       args.limit, args.json_path)


if __name__ == "__main__":
    raise SystemExit(main())
