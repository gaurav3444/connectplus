"""Scoring functions for the eval harness.

Each metric answers one question about one answered row. They are kept
separate from the runner so a metric can be argued with, replaced, or
reported on its own -- and so the runner stays readable.
"""

from __future__ import annotations

import re

__all__ = ["language_correct", "rewrite_contains_concept", "hit_at_k",
           "refusal_correct", "citations_valid", "register_correct",
           "terms_correct", "domain_correct"]


def language_correct(answer, expected_lang: str) -> bool:
    """Did the pipeline route the query to the right language lane?

    The first thing that can go wrong and the most consequential: a
    misdetection means a senior is answered in a language they cannot read.
    """
    return answer.lang == expected_lang


def rewrite_contains_concept(answer, expect_concepts: list[str]) -> tuple[bool, list[str]]:
    """Does the English rewrite carry the concepts retrieval needs?

    Substring matching on the head word of each expected concept, because
    "two-factor authentication" and "two factor authentication verification
    code" should both pass. Returns the misses so the eval can print them.
    """
    if not expect_concepts:
        return True, []
    rewritten = (answer.query_rewritten or "").lower()
    missing = []
    for concept in expect_concepts:
        words = [w for w in re.findall(r"[a-z]+", concept.lower()) if len(w) > 2]
        if not any(w in rewritten for w in words):
            missing.append(concept)
    return not missing, missing


def hit_at_k(answer, expect_chunks: list[str]) -> bool:
    """Was at least one acceptable passage retrieved?

    Scored against a fixture corpus, so this measures the retrieval *query*
    the pipeline built, not the knowledge base. The report must say so.
    """
    if not expect_chunks:
        return True
    return bool(set(answer.chunk_ids) & set(expect_chunks))


def refusal_correct(answer, must_refuse: bool) -> bool:
    """Did it refuse exactly when it should have?

    Both directions are failures. Answering a medical question is dangerous;
    refusing an answerable one makes the service useless.
    """
    return bool(answer.refused) == bool(must_refuse)


def domain_correct(answer, expect_domain: str) -> bool:
    """Did at least one citation come from the expected source domain?"""
    if not expect_domain:
        return True
    return any(c.domain == expect_domain for c in answer.citations)


def citations_valid(answer) -> bool:
    """Every citation marker resolves to a supplied source, and there is one.

    An answer with no citation is unverifiable; an answer citing a source
    that was never in the prompt is a hallucination even when the fact is
    right, because the reader cannot check it.
    """
    if answer.refused:
        return True
    if not answer.citations:
        return False
    return not any(v.get("kind") == "invalid_citation"
                   for v in answer.term_violations)


def register_correct(answer) -> bool:
    """No form-of-address violation.

    Calling a senior 你 or bạn is a correctness failure, not a style note,
    so it is scored as its own metric rather than folded into readability.
    """
    return not any(v.get("kind") == "address" and v.get("severity") == "error"
                   for v in answer.term_violations)


def terms_correct(answer) -> bool:
    """No locked-terminology violation."""
    return not any(v.get("kind") == "term" and v.get("severity") == "error"
                   for v in answer.term_violations)
