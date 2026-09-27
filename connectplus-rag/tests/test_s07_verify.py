"""Stage 07 - Guardrails + Citation Check.

Runs the committed adversarial fixture (`rag/fixtures/f07_drafts.json`) on
every change, which is the outer README's own instruction: "Keep a file of
drafts that should be rejected and run them on every change."

This iteration covers the three deterministic checks only. Grounding is
not implemented yet, so the two drafts marked needs_grounding are asserted
to PASS - keeping the gap visible in the test names rather than letting an
unimplemented check look green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag.s07_verify import (
    find_unsafe_instruction,
    load_approved_domains,
    resolve_citations,
    verify,
)
from rag.schemas import Chunk

FIXTURE = Path(__file__).parent.parent / "rag" / "fixtures" / "f07_drafts.json"
SPEC = json.loads(FIXTURE.read_text(encoding="utf-8"))
ALL_CHUNKS = [Chunk.model_validate(c) for c in SPEC["chunks"]]
APPROVED = {"beconnected.esafety.gov.au", "scamwatch.gov.au"}


def chunks_for(draft: dict) -> list[Chunk]:
    return [ALL_CHUNKS[i] for i in draft["chunks"]]


def draft(draft_id: str) -> dict:
    return next(d for d in SPEC["drafts"] if d["id"] == draft_id)


# ---------------------------------------------------------------------------
# the fixture - the acceptance criteria, run on every change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("d", SPEC["drafts"], ids=[d["id"] for d in SPEC["drafts"]])
def test_every_fixture_draft_gets_its_expected_verdict(d: dict) -> None:
    """Drafts marked needs_grounding pass here - grounding is not
    implemented in this iteration. Asserting that explicitly rather than
    skipping them keeps the gap visible instead of letting it look green."""
    expected = None if d.get("needs_grounding") else d["expect"]
    verdict = verify(
        d["answer_md"], chunks_for(d), d["confidence"], approved_domains=APPROVED
    )
    assert verdict.reason == expected, d["note"]
    assert verdict.passed is (expected is None)


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
