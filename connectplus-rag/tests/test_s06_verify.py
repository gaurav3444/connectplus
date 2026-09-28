"""Stage 06 - Guardrails + Citation Check.

Runs the committed adversarial fixture (`rag/fixtures/f06_drafts.json`) on
every change, which is the outer README's own instruction: "Keep a file of
drafts that should be rejected and run them on every change."

Grounding uses an injected entailment function throughout. The real
cross-encoder is a download this sandbox cannot make, so what is tested here
is the scoring LOGIC - weakest-claim aggregation, per-sentence best-chunk
matching - against deterministic fakes. get_default_entailment() is the
production path and is untested by me, the same honest caveat every other
stage in this repo carries for its external dependency.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag.s06_verify import (
    DEFAULT_GROUNDING_THRESHOLD,
    EntailmentFunction,
    find_unsafe_instruction,
    grounded_score,
    load_approved_domains,
    resolve_citations,
    verify,
)
from rag.schemas import Chunk

FIXTURE = Path(__file__).parent.parent / "rag" / "fixtures" / "f06_drafts.json"
SPEC = json.loads(FIXTURE.read_text(encoding="utf-8"))
ALL_CHUNKS = [Chunk.model_validate(c) for c in SPEC["chunks"]]
APPROVED = {"beconnected.esafety.gov.au", "scamwatch.gov.au"}


def chunks_for(draft: dict) -> list[Chunk]:
    return [ALL_CHUNKS[i] for i in draft["chunks"]]


def draft(draft_id: str) -> dict:
    return next(d for d in SPEC["drafts"] if d["id"] == draft_id)


def entail_by_overlap() -> EntailmentFunction:
    """A stand-in entailment function: word overlap between hypothesis and
    premise, which is crude but monotonic in the right direction - a
    sentence lifted from a chunk scores high, an invented one scores low.
    Enough to test the aggregation logic without a 500MB model.
    """

    def entail(premises: list[str], hypotheses: list[str]) -> list[float]:
        scores = []
        for premise, hypothesis in zip(premises, hypotheses):
            words = {w.strip(".,!?()").lower() for w in hypothesis.split() if len(w) > 3}
            if not words:
                scores.append(1.0)
                continue
            premise_words = {w.strip(".,!?()").lower() for w in premise.split()}
            scores.append(len(words & premise_words) / len(words))
        return scores

    return entail


# ---------------------------------------------------------------------------
# the fixture - the acceptance criteria, run on every change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("d", SPEC["drafts"], ids=[d["id"] for d in SPEC["drafts"]])
def test_every_fixture_draft_gets_its_expected_verdict(d: dict) -> None:
    entail = entail_by_overlap() if d.get("needs_grounding") else None
    verdict = verify(
        d["answer_md"], chunks_for(d), d["confidence"],
        entail_fn=entail, approved_domains=APPROVED,
    )
    assert verdict.reason == d["expect"], d["note"]
    assert verdict.passed is (d["expect"] is None)


def test_the_three_named_acceptance_criteria_are_all_covered() -> None:
    """Guards the fixture itself: if someone deletes one of the outer
    README's three named cases, this fails rather than the suite quietly
    getting weaker."""
    ids = {d["id"] for d in SPEC["drafts"]}
    assert {"d03-one-invented-step", "d04-citation-to-unapproved-domain",
            "d05-reply-with-the-code"} <= ids


# ---------------------------------------------------------------------------
# safety - instruction to disclose vs advice not to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "reply with the verification code you received",
        "reply with the code you received",  # the outer README's literal acceptance case
        "send us the code that was texted to you",
        "share your password with the operator",
        "send the gift card code to the number in the message",
        "give the caller your bank details",
        "read out the security code that was sent to your phone",
        "enter your PIN on the website in the message",
        "allow them access to your computer with AnyDesk",
        "tell them the one-time code",
        "forward the SMS code to the sender",
    ],
)
def test_disclosure_instructions_are_caught(text: str) -> None:
    assert find_unsafe_instruction(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Never share your password with anyone.",
        "Your bank will never ask you to send your password.",
        "Do not reply with the verification code.",
        "myGov would never ask you to give your bank details over the phone.",
        "No legitimate caller will ask you to read out a security code.",
        "Don't give the caller your card number.",
        "You should not enter your PIN on a site you reached from a text.",
        "A scam text often asks you for a password, but you should never provide one.",
        # "code" that is not a credential - the cost of matching bare "code"
        "Enter your postcode to find your nearest library.",
        "Share the discount code with a friend.",
        "Give the reference code to the librarian when you arrive.",
        "Scan the QR code shown on the screen.",
    ],
)
def test_safety_advice_is_not_flagged(text: str) -> None:
    """The regression that matters most. These are the correct answers on
    this corpus; a deny-list that rejects them is worse than none."""
    assert find_unsafe_instruction(text) is None


def test_a_negation_in_an_earlier_sentence_does_not_launder_a_later_instruction() -> None:
    text = "You should never share your password. Now give the operator the security code."
    assert find_unsafe_instruction(text) is not None


def test_unsafe_beats_bad_citation_in_the_reason() -> None:
    """Order is harm-first: an answer that is both dangerous and badly cited
    must report 'unsafe', because that is what decides the message the
    senior sees."""
    verdict = verify(
        "Reply with the code you received [9].", ALL_CHUNKS[:2], 0.9, approved_domains=APPROVED
    )
    assert verdict.reason == "unsafe"


def test_low_confidence_beats_everything() -> None:
    verdict = verify(
        "Reply with the code you received [9].", ALL_CHUNKS[:2], 0.01, approved_domains=APPROVED
    )
    assert verdict.reason == "low_confidence"


# ---------------------------------------------------------------------------
# citations
# ---------------------------------------------------------------------------


def test_markers_resolve_to_the_supplied_chunks_by_position() -> None:
    cites = resolve_citations("first [1] second [2]", ALL_CHUNKS[:2], APPROVED)
    assert [c.n for c in cites] == [1, 2]
    assert cites[0].url == str(ALL_CHUNKS[0].url)
    assert cites[1].domain == ALL_CHUNKS[1].domain
    assert all(c.resolved for c in cites)


def test_a_marker_beyond_the_supplied_chunks_resolves_to_nothing() -> None:
    cites = resolve_citations("claim [4]", ALL_CHUNKS[:2], APPROVED)
    assert cites[0].resolved is False
    assert cites[0].url == ""


def test_a_marker_to_an_unapproved_domain_is_unresolved_even_though_the_chunk_exists() -> None:
    """The whole point of re-enforcing the allowlist here: the chunk is
    real and in range. Only the domain check catches it."""
    cites = resolve_citations("claim [1]", [ALL_CHUNKS[2]], APPROVED)
    assert cites[0].domain == "example-unapproved-site.com"
    assert cites[0].resolved is False


def test_repeated_markers_are_reported_once_in_order() -> None:
    cites = resolve_citations("a [2] b [1] c [2] d [1]", ALL_CHUNKS[:2], APPROVED)
    assert [c.n for c in cites] == [1, 2]


def test_an_answer_with_no_content_and_no_citations_is_not_a_citation_failure() -> None:
    """A bare refusal cites nothing and should not be graded as one."""
    verdict = verify("No.", ALL_CHUNKS[:2], 0.9, approved_domains=APPROVED)
    assert verdict.passed is True


# ---------------------------------------------------------------------------
# grounding
# ---------------------------------------------------------------------------


def test_grounded_score_is_the_weakest_claim_not_the_average() -> None:
    """Two well-supported sentences must not be able to carry one invented
    one - that is the acceptance criterion a mean cannot deliver."""
    def entail(premises, hypotheses):
        return [1.0 if "supported" in h else 0.05 for h in hypotheses]

    score = grounded_score(
        "This claim is supported by the source. "
        "This claim is supported by the source too. "
        "The national scam register blocks senders within 24 hours.",
        ALL_CHUNKS[:1],
        entail,
    )
    assert score == pytest.approx(0.05)


def test_each_sentence_is_scored_against_its_best_chunk_not_all_of_them() -> None:
    """A claim needs only ONE source to support it. Requiring every chunk to
    entail every sentence would fail every real answer."""
    def entail(premises, hypotheses):
        return [0.95 if p is ALL_CHUNKS[1].text else 0.02 for p in premises]

    score = grounded_score("Some substantive claim here.", ALL_CHUNKS[:2], entail)
    assert score == pytest.approx(0.95)


def test_citation_markers_and_list_numbering_are_stripped_before_grounding() -> None:
    seen: list[str] = []

    def entail(premises, hypotheses):
        seen.extend(hypotheses)
        return [1.0] * len(premises)

    grounded_score("1. Do not tap the link in the message [1].", ALL_CHUNKS[:1], entail)
    assert seen and "[1]" not in seen[0] and not seen[0].startswith("1.")


def test_short_connective_lines_are_not_grounded() -> None:
    seen: list[str] = []

    def entail(premises, hypotheses):
        seen.extend(hypotheses)
        return [1.0] * len(premises)

    grounded_score(
        "Here's how:\n\nScam texts often create a sense of urgency about your account.",
        ALL_CHUNKS[:1], entail,
    )
    assert all("Here's how" not in h for h in seen)


def test_grounding_is_skipped_when_no_entail_fn_is_supplied() -> None:
    """Deliberate, not a silent downgrade: the three deterministic checks
    are useful on their own, and grounded_score stays 0.0 rather than
    claiming a check that never ran."""
    d = draft("d03-one-invented-step")
    verdict = verify(d["answer_md"], chunks_for(d), d["confidence"], approved_domains=APPROVED)
    assert verdict.passed is True
    assert verdict.grounded_score == 0.0


def test_an_entail_fn_returning_the_wrong_number_of_scores_raises() -> None:
    with pytest.raises(ValueError, match="refusing to guess"):
        grounded_score("A substantive claim goes here.", ALL_CHUNKS[:2], lambda p, h: [1.0])


def test_grounding_threshold_is_the_documented_default() -> None:
    assert DEFAULT_GROUNDING_THRESHOLD == 0.7


# ---------------------------------------------------------------------------
# verdict shape and provenance
# ---------------------------------------------------------------------------


def test_verdict_carries_the_audit_trail_even_when_it_fails() -> None:
    """'A bad answer has to be traceable' - the chunk ids and resolved
    citations must survive a failure, not only a pass."""
    d = draft("d05-reply-with-the-code")
    verdict = verify(d["answer_md"], chunks_for(d), d["confidence"], approved_domains=APPROVED)
    assert verdict.passed is False
    assert verdict.chunk_ids == [c.id for c in chunks_for(d)]
    assert verdict.confidence == d["confidence"]
    assert [c.n for c in verdict.citations] == [1, 2]


def test_the_real_allowlist_file_is_what_gets_enforced() -> None:
    """Not a hardcoded set - the same file stage 01 enforces at fetch time,
    so the two checks cannot drift apart."""
    domains = load_approved_domains()
    assert domains == {"beconnected.esafety.gov.au", "scamwatch.gov.au"}


def test_verify_defaults_to_the_real_allowlist_when_none_is_passed() -> None:
    d = draft("d04-citation-to-unapproved-domain")
    verdict = verify(d["answer_md"], chunks_for(d), d["confidence"])
    assert verdict.reason == "bad_citation"
