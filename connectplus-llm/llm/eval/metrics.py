"""Scoring for the Vietnamese eval.

Each question produces one :class:`QuestionResult`. Nothing here is a single
"quality" number, on purpose: a system can be perfectly grounded and completely
unreadable, or beautifully written and citing nothing, and one blended score
hides exactly the trade-off a prompt change makes. The harness prints the
columns and lets the reader see which one moved.

The columns and what a failure means:

``lang``
    The answer came back in the language the user asked in. A failure here is
    the worst outcome in the set - the senior gets English.
``rewrite``
    The English query contains the concept the question was about. A failure
    means retrieval was sent after the wrong thing.
``hit@3``
    At least one of the pages that can answer the question was retrieved.
``refusal``
    Refused exactly when it should have. Scored on the three out-of-scope
    questions and on the seventeen answerable ones equally - refusing a
    question you could have answered is also a failure.
``cited``
    At least one citation, and no citation pointing at a source that was never
    supplied.
``register``
    No disrespectful address. Treated as an error, not a style note.
``terms``
    No forbidden synonym for a locked safety term.
``read``
    Vietnamese readability score from :mod:`llm.vi.readability`.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field

from ..schemas import Answer
from ..vi.normalize import has_vietnamese_diacritics

__all__ = ["QuestionResult", "score_question", "summarise"]


@dataclass
class QuestionResult:
    """Scored outcome for one eval question."""

    id: str
    intent: str
    should_refuse: bool
    refused: bool
    lang_ok: bool = False
    rewrite_ok: bool | None = None
    hit_at_3: bool | None = None
    refusal_ok: bool = False
    cited_ok: bool | None = None
    register_ok: bool = True
    terms_ok: bool = True
    readability: float = 0.0
    grade: str = ""
    query_rewritten: str = ""
    retrieved: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


def score_question(q: dict, ans: Answer, trace) -> QuestionResult:
    """Score one answer against its expected behaviour.

    Args:
        q: The question entry from ``questions_vi.json``.
        ans: What the pipeline produced.
        trace: The :class:`~llm.pipeline.PipelineTrace` for the same call.

    Returns:
        A :class:`QuestionResult`. Metrics that do not apply to a question are
        left as ``None`` rather than defaulted to pass or fail - averaging a
        refusal question into hit@3 would quietly distort the number.
    """
    r = QuestionResult(
        id=q["id"],
        intent=q["intent"],
        should_refuse=q["should_refuse"],
        refused=ans.refused,
        query_rewritten=ans.query_rewritten,
        retrieved=list(trace.retrieved_ids or []),
    )

    r.refusal_ok = (ans.refused == q["should_refuse"])
    if not r.refusal_ok:
        r.notes.append(
            "refused a question it should have answered" if ans.refused
            else "ANSWERED A QUESTION IT SHOULD HAVE REFUSED"
        )

    # Language. Every answer to a Vietnamese question, refusal included, must
    # be in Vietnamese - a refusal in English is still a senior left stranded.
    r.lang_ok = has_vietnamese_diacritics(ans.answer_md)
    if not r.lang_ok:
        r.notes.append("answer is not in Vietnamese")

    read = ans.readability or {}
    r.readability = float(read.get("score", 0.0))
    r.grade = str(read.get("grade", ""))

    kinds = {v.get("kind") for v in (ans.term_violations or [])}
    r.register_ok = "address" not in kinds
    r.terms_ok = "forbidden_term" not in kinds
    if not r.register_ok:
        r.notes.append("disrespectful address")
    if not r.terms_ok:
        r.notes.append("forbidden term for a locked concept")

    if q["should_refuse"]:
        # Retrieval and citation metrics are meaningless for a question whose
        # correct answer is "we don't know".
        return r

    expected_terms = [t.lower() for t in q.get("expected_query_en_terms", [])]
    rewritten = (ans.query_rewritten or "").lower()
    r.rewrite_ok = all(t in rewritten for t in expected_terms) if expected_terms else None
    if r.rewrite_ok is False:
        missing = [t for t in expected_terms if t not in rewritten]
        r.notes.append(f"rewrite missing {missing}")

    expected_chunks = set(q.get("expected_chunks", []))
    r.hit_at_3 = bool(expected_chunks & set(r.retrieved)) if expected_chunks else None
    if r.hit_at_3 is False:
        r.notes.append("no expected source in top 3")

    if not ans.refused:
        r.cited_ok = bool(ans.citations) and "invalid_citation" not in kinds
        if not r.cited_ok:
            r.notes.append("no valid citations")

    return r


def _rate(values: list[bool | None]) -> tuple[float, int]:
    """Pass rate over the entries where the metric applies."""
    applicable = [v for v in values if v is not None]
    if not applicable:
        return 0.0, 0
    return sum(applicable) / len(applicable), len(applicable)


def summarise(results: list[QuestionResult]) -> dict:
    """Aggregate scored questions into the numbers that go in the report."""
    answered = [r for r in results if not r.should_refuse]
    graded = [r for r in results if not r.refused and r.readability > 0]

    lang_rate, lang_n = _rate([r.lang_ok for r in results])
    rewrite_rate, rewrite_n = _rate([r.rewrite_ok for r in answered])
    hit_rate, hit_n = _rate([r.hit_at_3 for r in answered])
    refusal_rate, refusal_n = _rate([r.refusal_ok for r in results])
    cite_rate, cite_n = _rate([r.cited_ok for r in answered])
    reg_rate, reg_n = _rate([r.register_ok for r in results])
    term_rate, term_n = _rate([r.terms_ok for r in results])

    over_refusals = [r.id for r in answered if r.refused]
    under_refusals = [r.id for r in results if r.should_refuse and not r.refused]

    return {
        "n_questions": len(results),
        "language_correct": {"rate": round(lang_rate, 3), "n": lang_n},
        "rewrite_contains_concept": {"rate": round(rewrite_rate, 3), "n": rewrite_n},
        "hit_at_3": {"rate": round(hit_rate, 3), "n": hit_n},
        "refusal_correct": {"rate": round(refusal_rate, 3), "n": refusal_n},
        "citations_valid": {"rate": round(cite_rate, 3), "n": cite_n},
        "register_correct": {"rate": round(reg_rate, 3), "n": reg_n},
        "terms_correct": {"rate": round(term_rate, 3), "n": term_n},
        "readability_mean": round(
            sum(r.readability for r in graded) / len(graded), 1) if graded else 0.0,
        "readability_hard_count": sum(1 for r in graded if r.grade == "hard"),
        "over_refused_ids": over_refusals,
        "under_refused_ids": under_refusals,
    }
