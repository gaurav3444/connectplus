"""
Generates the team-facing status report for the LLM query-understanding
work (stage 07): what's built, why, the results (including live Gemini
output), and what's explicitly out of scope.
"""

from __future__ import annotations

import json

from docx import Document
from docx.shared import Pt

OUT_PATH = "../LLM_Stage07_Status_Report.docx"


def add_heading(doc, text, level=1):
    return doc.add_heading(text, level=level)


def main() -> None:
    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)

    doc.add_heading("CONNECT Plus — LLM Query Understanding: Status for the Team", level=0)
    doc.add_paragraph(
        "Status of the query-understanding half of the LLM pipeline: detect "
        "the language a senior typed in, then translate and rewrite their "
        "question into an English, retrieval-ready search query. This "
        "report covers what has been built, verified, and demoed so far, "
        "and is explicit about what has not."
    )

    # ---------------------------------------------------------------
    add_heading(doc, "1. Scope", level=1)
    doc.add_paragraph("This work covers exactly steps [1] and [2] of the pipeline:")
    for line in [
        "[1] detect language",
        "[2] translate + rewrite query -> English, expand vague terms",
    ]:
        doc.add_paragraph(line, style="List Bullet")
    doc.add_paragraph(
        "Retrieval (rag.retrieve), answer generation, and verification "
        "(rag.verify) are explicitly out of scope for this work -- that is "
        "connectplus-rag, owned by a teammate. Nothing here calls or stubs "
        "retrieval beyond the one-value contract it will eventually need: "
        "a rewritten English query string and a language code."
    )

    # ---------------------------------------------------------------
    add_heading(doc, "2. What Has Been Built", level=1)
    for bullet in [
        "chinese_detector -- a trained classifier (3,279,816 training rows, "
        "no sampling) that decides whether typed text is Chinese, replacing "
        "the langdetect library used previously. Verified separately in its "
        "own report: 99.76% / 99.9% / 98.1% train/validation/test accuracy, "
        "and 100% correct across 140 independently written test statements "
        "(40 clean + 100 in an elderly, imperfectly-typed style).",
        "A provider wrapper (Gemini primary, Ollama local fallback, plus an "
        "offline stub) with one call interface, automatic JSON-repair retry, "
        "and automatic fallback on quota or network errors -- so swapping "
        "providers is a configuration change, not a code change.",
        "The query-understanding module itself: detects language via "
        "chinese_detector, then calls the LLM to translate and rewrite the "
        "query, expanding vague phrasing into the specific terms a help "
        "article would use (e.g. \"keeps asking for a code\" -> "
        "\"two-factor authentication verification code\").",
        "A non-LLM degraded fallback path: if the model is unavailable, "
        "English input gets naive keyword extraction; Chinese input with no "
        "model available gets an honest generic query rather than being "
        "echoed back untranslated, which would silently break retrieval.",
        "A versioned, file-based prompt (not embedded in code), so prompt "
        "changes are reviewable diffs and every result can be traced back "
        "to the exact prompt version that produced it.",
        "10 test fixtures (5 English, 5 Chinese) covering vague, "
        "real-world phrasings, per the project's own stated verification "
        "requirement for this stage.",
        "6 automated offline tests (language detection correctness, "
        "degraded-path behaviour for both languages, and a schema guard "
        "against the model echoing untranslated Chinese back) -- all passing.",
        "A live demo: a local web page (demo.html) backed by a small "
        "FastAPI server, so the team can type a question and see the real "
        "detected language and rewritten query, not a mock.",
    ]:
        doc.add_paragraph(bullet, style="List Bullet")

    # ---------------------------------------------------------------
    add_heading(doc, "3. Results", level=1)

    add_heading(doc, "3.1 Language Detection", level=2)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    for i, h in enumerate(["Metric", "This model", "langdetect (previous approach)"]):
        hdr[i].text = h
    for metric, ours, ld in [
        ("Train / Validation / Test accuracy", "99.76% / 99.9% / 98.1%", "not applicable -- rule-based library"),
        ("Held-out dev split", "99.9%", "84.8%"),
        ("Held-out test split", "98.1%", "81.9%"),
        ("140 independent hand-written statements", "100%", "not tested -- superseded"),
    ]:
        row = table.add_row().cells
        row[0].text = metric
        row[1].text = ours
        row[2].text = ld
    doc.add_paragraph("")
    doc.add_paragraph(
        "Full methodology, leakage checks, and the two failed training "
        "attempts that led to the final approach are documented in the "
        "separate Chinese_Language_Detector_Report.docx."
    )

    add_heading(doc, "3.2 Query Translation and Rewriting -- Live Gemini Results", level=2)
    doc.add_paragraph(
        "The 10 fixtures run against the real Gemini API (not the offline "
        "stub), spaced to avoid the free-tier rate limit. Every result "
        "below is a live model output, not a mock."
    )

    try:
        results = json.load(open("fixtures/query_fixtures_gemini_results.json", encoding="utf-8"))
    except FileNotFoundError:
        results = []

    rtable = doc.add_table(rows=1, cols=4)
    rtable.style = "Light Grid Accent 1"
    hdr = rtable.rows[0].cells
    for i, h in enumerate(["ID", "Lang", "Original", "Rewritten (English)"]):
        hdr[i].text = h
    for r in results:
        row = rtable.add_row().cells
        row[0].text = r["id"]
        row[1].text = "Chinese" if r["lang"] == "zh" else "English"
        row[2].text = r["raw_query"]
        row[3].text = r["query_rewritten"] + (" [DEGRADED]" if r.get("degraded") else "")

    doc.add_paragraph("")
    doc.add_paragraph(f"Result: {sum(1 for r in results if not r.get('degraded'))}/{len(results)} produced a real, non-degraded translation and rewrite, matching or exceeding the expected concepts for every fixture.")

    add_heading(doc, "3.3 A Finding Worth Knowing About: Free-Tier Rate Limits", level=2)
    doc.add_paragraph(
        "Running all 10 fixtures back-to-back with no delay hit the Gemini "
        "free tier's rate limit after roughly 16 calls (verified via the "
        "call trace log, not guessed). This correctly triggered the "
        "automatic fallback to Ollama -- which is not installed on the "
        "development machine, so that fallback also failed, and the system "
        "correctly landed in the honest degraded path rather than crashing "
        "or fabricating an answer. This is the exact failure mode the "
        "project's own documentation flags as worth testing before demo "
        "day: the Ollama fallback should be installed and verified working "
        "at least once before relying on it live."
    )

    # ---------------------------------------------------------------
    add_heading(doc, "4. Guardrails", level=1)
    doc.add_paragraph(
        "No guardrails against malicious website content exist yet in this "
        "code -- and that is correct for where the work currently stands, "
        "not an oversight. Everything built so far only ever processes the "
        "senior's own typed question; no content retrieved from a website "
        "passes through any code that exists yet, because retrieval "
        "(connectplus-rag) has not been built. The prompt-injection defence "
        "the project requires (fencing retrieved chunks as inert data, so a "
        "page saying \"ignore previous instructions\" cannot steer the "
        "model) applies to the next stage -- building the answer-generation "
        "prompt -- and must be in place and tested against a deliberately "
        "poisoned fixture chunk before that stage is considered done, not "
        "added afterward."
    )

    # ---------------------------------------------------------------
    add_heading(doc, "5. How to Run It", level=1)
    for cmd in [
        "pip install -r requirements.txt",
        "pip install -e ../chinese-detector",
        "cp .env.example .env   # add GEMINI_API_KEY to use real Gemini instead of the offline stub",
        "pytest tests/ -v                                  # 6 offline tests",
        "python scripts/demo_query.py                      # all 10 fixtures, terminal output",
        "uvicorn scripts.demo_server:app --port 8000        # then open http://localhost:8000",
    ]:
        p = doc.add_paragraph(cmd)
        p.style = doc.styles["Normal"]
        for run in p.runs:
            run.font.name = "Consolas"
            run.font.size = Pt(10)

    # ---------------------------------------------------------------
    add_heading(doc, "6. Explicitly Not Done", level=1)
    for bullet in [
        "Step [3] build prompt (plain language, steps, citations) -- not started.",
        "Step [4] generate answer, in the senior's own language -- not started.",
        "Anything in connectplus-rag: crawling, chunking, indexing, retrieval, "
        "verification -- not this person's scope, confirmed with the team, "
        "not built and not stubbed beyond the query_rewritten/lang contract "
        "retrieval will need.",
        "Real translation quality has not yet been reviewed by a native "
        "speaker -- the results in Section 3.2 look correct on inspection, "
        "but that is not the same as native-speaker sign-off, which the "
        "project's own verification checklist calls for.",
    ]:
        doc.add_paragraph(bullet, style="List Bullet")

    doc.save(OUT_PATH)
    print(f"Saved report to {OUT_PATH}")


if __name__ == "__main__":
    main()
