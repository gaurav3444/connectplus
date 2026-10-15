"""The scored eval harness.

    python -m llm.eval                   # both lanes, mock provider
    python -m llm.eval --lang zh         # one lane
    python -m llm.eval --provider gemini # the numbers that count
    python -m llm.eval detect            # detection vs the baseline

Re-run this on every prompt, termbase or retrieval change. It is the only
signal that says whether a change helped.

**How to read a mock run.** The mock provider copies English source text
into the answer scaffold, so groundedness and citations cannot fail and
readability cannot pass. Those rows describe the plumbing. Any claim about
model quality has to come from ``--provider gemini`` or ``--provider
ollama``, and the provider column in the output says which you ran.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from ..lang.detect import detect
from ..pipeline import answer as pipeline_answer
from ..providers import ProviderError, get_provider
from . import metrics

if hasattr(sys.stdout, "reconfigure"):
    # Windows consoles default to cp1252, which cannot print Chinese or
    # Vietnamese. Without this the harness crashes on its own output.
    sys.stdout.reconfigure(encoding="utf-8")

_DATA = Path(__file__).parent / "data"


def _load(name: str) -> dict:
    with (_DATA / name).open(encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------
# Detection benchmark
# --------------------------------------------------------------------------

def run_detect() -> int:
    cases = _load("detect_cases.json")["cases"]

    try:
        from langdetect import DetectorFactory, detect as ld_detect
        from langdetect.lang_detect_exception import LangDetectException
        DetectorFactory.seed = 0
        have_baseline = True
    except ImportError:
        have_baseline = False

    def baseline(text: str) -> str:
        if not have_baseline:
            return "n/a"
        try:
            code = ld_detect(text)
        except (LangDetectException, Exception):
            return "err"
        if code in ("zh-cn", "zh-tw"):
            return "zh"
        return code if code in ("vi", "en") else "other"

    print("\nLanguage detection - %d cases" % len(cases))
    print("Baseline is langdetect, the library this detector replaces.\n")
    print(f"{'expect':>7}{'ours':>7}{'langdetect':>12}  {'hard':<6} text")
    print("-" * 78)

    ours_ok = base_ok = hard_n = hard_ours = hard_base = 0
    for c in cases:
        got = detect(c["text"]).lang
        base = baseline(c["text"])
        ok = got == c["expect"]
        # langdetect has no "und", so it is credited whenever it declines or
        # errors on a case we also call undecidable.
        b_ok = (base == c["expect"]) or (c["expect"] == "und" and base in ("err", "other"))
        ours_ok += ok
        base_ok += b_ok
        if c["hard"]:
            hard_n += 1
            hard_ours += ok
            hard_base += b_ok
        shown = c["text"] if len(c["text"]) <= 34 else c["text"][:31] + "..."
        flag = "" if ok else "  <-- miss"
        print(f"{c['expect']:>7}{got:>7}{base:>12}  {str(c['hard']):<6} {shown}{flag}")

    n = len(cases)
    print(f"\n  ours        {ours_ok}/{n} = {ours_ok / n:.1%}")
    print(f"  langdetect  {base_ok}/{n} = {base_ok / n:.1%}")
    if hard_n:
        print(f"\n  on the {hard_n} hard cases (no diacritics, very short, "
              f"or out of scope):")
        print(f"    ours        {hard_ours}/{hard_n} = {hard_ours / hard_n:.1%}")
        print(f"    langdetect  {hard_base}/{hard_n} = {hard_base / hard_n:.1%}")
    print("\n  NOTE: these cases and the detector were written together, so")
    print("  the headline number is a regression guard, not an unbiased")
    print("  accuracy estimate. The gap on the hard cases is the finding.")
    return 0


# --------------------------------------------------------------------------
# Answer benchmark
# --------------------------------------------------------------------------

async def _run_lang(lang: str, provider, k: int) -> dict:
    data = _load(f"questions_{lang}.json")["questions"]
    rows = []
    for q in data:
        ans = await pipeline_answer(q["query"], app_lang=lang,
                                    provider=provider, k=k)
        rewrite_ok, missing = metrics.rewrite_contains_concept(
            ans, q["expect_concepts"])
        rows.append({
            "id": q["id"], "intent": q["intent"], "must_refuse": q["must_refuse"],
            "answered": not ans.refused,
            "lang": metrics.language_correct(ans, lang),
            "rewrite": rewrite_ok, "missing": missing,
            "hit3": metrics.hit_at_k(ans, q["expect_chunks"]),
            "refusal": metrics.refusal_correct(ans, q["must_refuse"]),
            "cite": metrics.citations_valid(ans),
            "domain": metrics.domain_correct(ans, q["expect_domain"]),
            "register": metrics.register_correct(ans),
            "terms": metrics.terms_correct(ans),
            "read": (ans.readability or {}).get("score", 0.0),
            "grade": (ans.readability or {}).get("grade", "-"),
        })
    return {"lang": lang, "rows": rows}


def _print_lang(result: dict) -> None:
    lang, rows = result["lang"], result["rows"]
    print(f"\n{'=' * 86}")
    print(f"  {lang.upper()} lane - {len(rows)} questions")
    print("=" * 86)
    print(f"{'id':<8}{'intent':<30}{'lang':>5}{'rewr':>6}{'hit3':>6}"
          f"{'refu':>6}{'cite':>6}{'regi':>6}{'term':>6}{'read':>7}")
    print("-" * 86)

    def mark(ok: bool, na: bool = False) -> str:
        return "  . " if na else ("  ok" if ok else "  XX")

    for r in rows:
        na = not r["answered"]
        read = "    -" if na else f"{r['read']:5.0f}"
        print(f"{r['id']:<8}{r['intent']:<30}"
              f"{mark(r['lang']):>5}{mark(r['rewrite'], na):>6}"
              f"{mark(r['hit3'], na):>6}{mark(r['refusal']):>6}"
              f"{mark(r['cite'], na):>6}{mark(r['register']):>6}"
              f"{mark(r['terms']):>6}{read:>7}")

    answered = [r for r in rows if r["answered"]]

    def pct(name: str, rs: list) -> None:
        if not rs:
            print(f"  {name:<26} {'n/a':>7}")
            return
        hits = sum(1 for r in rs if r[name.split()[0]])
        print(f"  {name:<26} {hits / len(rs):>6.1%}  (n={len(rs)})")

    print("\n  Summary")
    print("  " + "-" * 40)
    pct("lang", rows)
    pct("rewrite", answered)
    pct("hit3", answered)
    pct("refusal", rows)
    pct("cite", answered)
    pct("domain", answered)
    pct("register", rows)
    pct("terms", rows)
    if answered:
        mean = sum(r["read"] for r in answered) / len(answered)
        hard = sum(1 for r in answered if r["grade"] == "hard")
        print(f"  {'readability mean':<26} {mean:>6.1f}  ({hard} graded hard)")

    notes = [r for r in answered if r["missing"]]
    if notes:
        print("\n  Notes")
        for r in notes:
            print(f"    {r['id']}: rewrite missing {r['missing']}")


def run_answers(langs: list[str], provider_name: str | None, k: int) -> int:
    try:
        provider = get_provider(provider_name,
                                strict=bool(provider_name and
                                            provider_name not in ("mock", "stub")))
    except ProviderError as exc:
        print(f"\nCannot start provider {provider_name!r}: {exc}")
        print("The eval refuses to silently score the mock while the table "
              "says otherwise.")
        return 2

    print(f"\nProvider: {provider.name} ({provider.model or 'n/a'})")
    print("NOTE: retrieval and verification are the stub in llm/rag_stub, "
          "not connectplus-rag.")
    if provider.name in ("mock", "stub"):
        print("NOTE: the mock copies English source text, so readability is")
        print("      SUPPOSED to grade hard. That is the metric working.")

    async def main() -> int:
        # A provider that cannot be reached produces a whole table of
        # refusals, which reads like a content problem and is actually a
        # connection problem. Fail loudly instead.
        if provider.name not in ("mock", "stub"):
            if not await provider.healthy():
                print(f"\n{provider.name} is configured but not reachable.")
                print("Run `python check_provider.py` to find out why.")
                await provider.aclose()
                return 2
        for lang in langs:
            _print_lang(await _run_lang(lang, provider, k))
        await provider.aclose()
        return 0

    return asyncio.run(main())


def main() -> int:
    ap = argparse.ArgumentParser(prog="python -m llm.eval")
    ap.add_argument("mode", nargs="?", default="answers",
                    choices=["answers", "detect"])
    ap.add_argument("--lang", action="append",
                    choices=["zh", "zh_hant", "vi"],
                    help="repeatable; default zh+vi. zh_hant has a starter "
                         "set only (converted from questions_zh.json, not "
                         "independently authored -- see its _comment)")
    ap.add_argument("--provider", default=None,
                    choices=["mock", "stub", "gemini", "ollama"])
    ap.add_argument("-k", type=int, default=3)
    args = ap.parse_args()

    if args.mode == "detect":
        return run_detect()
    return run_answers(args.lang or ["zh", "vi"], args.provider, args.k)


if __name__ == "__main__":
    raise SystemExit(main())
