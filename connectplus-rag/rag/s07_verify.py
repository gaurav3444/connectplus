"""Stage 07 - Guardrails + Citation Check (this repo's file numbering; the
unified whole-project stage map calls this "stage 08" - see README's
mapping table).

Its own stage, not a flag inside generation. This is the only thing standing
between a senior and a confident invented answer about myGov.

Four checks. All must pass:

    confident   retrieval confidence is below threshold, so there was never
                good enough source material to answer from
    safe        the answer tells the senior to hand over a password, an MFA
                code, or payment details
    cited       a citation marker resolves to nothing, or to a domain that
                is not on the approved list
    grounded    the answer states a fact that is not in the supplied chunks
                - NOT IMPLEMENTED YET, see the note below

Fail any one and the answer is **dropped, not patched**. What the senior
gets instead is "I don't have trusted information on that" plus a mentor
offer. In a scam-and-safety domain a confident wrong answer about myGov is
real harm, not a quality bug.

Design decisions made explicit here:

- Check order is HARM-first, not cost-first. Confidence is a free number
  comparison so it goes first regardless; after that, `unsafe` outranks
  `bad_citation` even though both are cheap regexes, because `reason` is
  what decides which message the senior sees and being told "that advice
  was dangerous" matters more than "a footnote didn't resolve".
- Everything except grounding is deterministic. No second LLM judging the
  first one on the hot path - a model that can invent an answer can invent
  a defence of it. Citation resolution and the deny-list are regex and set
  membership, and they are the checks that catch the two failure modes with
  actual victims.
- The approved-domain list is enforced HERE as well as at fetch time. That
  is the outer README's own claim ("enforced in code, at fetch time and
  again at verification time") and it is not redundant: chunks already in
  the index outlive a domain's approval, since stage 04's upsert-by-id
  never deletes anything.
- An answer with NO citations at all fails `cited`. Non-obvious but
  essential - without it, the single easiest way to pass the citation check
  is to cite nothing, which is exactly the shape a wholly invented answer
  takes.
- GROUNDING IS NOT IMPLEMENTED IN THIS ITERATION. The three deterministic
  checks land first, on their own, because they are the ones that catch the
  failures with actual victims and they need no model download to run. A
  draft whose only fault is an invented fact PASSES here, and that is stated
  rather than hidden: `grounded_score` stays 0.0 and never claims a check
  that did not run. Grounding arrives next.
- The safety deny-list matches INSTRUCTIONS TO DISCLOSE, never the mere
  mention of a credential. This is the whole difficulty of the check: the
  correct, desirable answer on this corpus is "never share your password
  with anyone", and a naive deny-list on the word "password" rejects every
  good safety answer while a lazy fix (dropping the word) lets the
  dangerous one through. See _DISCLOSURE_RE and _NEGATION_RE.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from rag.schemas import Chunk, Citation, Verdict

DEFAULT_CONFIDENCE_THRESHOLD = 0.45  # outer README's CONFIDENCE_THRESHOLD

APPROVED_DOMAINS_PATH = Path(__file__).parent / "config" / "approved_domains.json"

_CITATION_RE = re.compile(r"\[(\d{1,3})\]")

# Sensitive things a senior must never be told to hand over.
_SECRET = (
    r"password|passcode|pass phrase|passphrase|"
    r"pin(?:\s+number|\s+code)?|"
    r"(?:verification|security|one[- ]time|login|access|sms|authentication|2fa|mfa|otp)\s+code|"
    r"one[- ]time\s+p(?:in|assword)|otp|"
    r"(?:credit|debit|bank)\s+card(?:\s+number|\s+details)?|card number|"
    r"bank\s+(?:details|account\s+details|login)|"
    r"cvv|cvc|security\s+number|"
    r"gift\s+card(?:\s+code|\s+number)?|"
    r"(?:medicare|licence|license|passport)\s+number|"
    r"remote\s+access|teamviewer|anydesk|"
    # Bare "code", last. The outer README's own acceptance case is literally
    # "reply with the code you received" - a senior forwarding a one-time
    # code does not call it a "verification code", and requiring the
    # qualifier would miss the exact phrasing the check exists to catch.
    # False positives are handled by _BENIGN_CODE_RE rather than by
    # narrowing this, because the qualifier is precisely what's missing.
    r"code"
)

# "Code" that is not a credential. Checked against the matched span, so
# "enter your postcode" and "share the discount code" don't trip the
# guardrail while "reply with the code you received" still does.
_BENIGN_CODE_RE = re.compile(
    r"\b(?:post|area|dial|zip|qr|bar|dress|source|discount|promo|coupon|error|"
    r"country|colour|color|reference|booking|product)[\s-]?code|code\s+of\s+conduct",
    re.IGNORECASE,
)

# Verbs that mean "give it to someone". The gap allows a few words in
# between ("send them the code you received") without spanning a sentence.
_GIVE = (
    r"share|send|give|provide|hand over|forward|reply with|read out|read back|"
    r"tell (?:them|him|her|us|the caller|the operator)|enter|type in|confirm|"
    r"disclose|pass on|let them have|allow (?:them )?access"
)

_DISCLOSURE_RE = re.compile(
    rf"\b(?:{_GIVE})\b[^.!?\n]{{0,60}}?\b(?:{_SECRET})\b",
    re.IGNORECASE,
)

# The safety-advice form of the same words. "Never share your password" is
# the CORRECT answer on this corpus and must not be flagged. Checked in the
# text immediately before the matched instruction.
_NEGATION_RE = re.compile(
    r"\b(?:never|do not|don't|dont|avoid|refuse to|should not|shouldn't|must not|"
    r"mustn't|no need to|won't ask|will never ask|would never ask|no legitimate|"
    r"nobody|no one|not|stop)\b",
    re.IGNORECASE,
)

_NEGATION_WINDOW = 60  # characters before the match to search for a negation
_MIN_CONTENT_WORDS = 4  # below this an "answer" is a bare refusal, not a claim needing a citation


def load_approved_domains(path: Path = APPROVED_DOMAINS_PATH) -> set[str]:
    """Bare hostnames from the allowlist. Reads the same file stage 01
    enforces at fetch time, so the two checks can never drift apart."""
    return {row["domain"] for row in json.loads(path.read_text(encoding="utf-8"))}


def find_unsafe_instruction(answer_md: str) -> str | None:
    """The matched text of the first genuine disclosure instruction, or None.

    Returns the match rather than a bool so a failure is debuggable - "which
    sentence tripped this" is the first question anyone asks.

    A match preceded by a negation inside the same sentence is treated as
    safety advice, not an instruction. "Never share your password" and
    "myGov will never ask you to send your password" are the single most
    common correct answers this corpus produces, and flagging them would
    make the guardrail worse than useless: it would reject exactly the
    advice seniors most need.
    """
    for match in _DISCLOSURE_RE.finditer(answer_md):
        if _BENIGN_CODE_RE.search(match.group(0)):
            continue  # "enter your postcode", "share the discount code"

        # Look back only to the start of the current sentence, so a negation
        # in a PREVIOUS sentence can't launder the instruction in this one.
        sentence_start = max(
            answer_md.rfind(".", 0, match.start()),
            answer_md.rfind("!", 0, match.start()),
            answer_md.rfind("?", 0, match.start()),
            answer_md.rfind("\n", 0, match.start()),
        )
        window_start = max(sentence_start + 1, match.start() - _NEGATION_WINDOW, 0)
        preceding = answer_md[window_start : match.start()]
        if not _NEGATION_RE.search(preceding):
            return match.group(0)
    return None


def resolve_citations(
    answer_md: str,
    chunks: list[Chunk],
    approved_domains: set[str],
) -> list[Citation]:
    """Every `[n]` marker in the answer, resolved against the chunks the
    generator was actually given.

    Markers are 1-based positions in `chunks`, which is the numbering the
    generator's prompt hands it. A marker outside that range resolved to
    nothing - the shape an invented citation takes.
    """
    citations: list[Citation] = []
    for n in sorted({int(m.group(1)) for m in _CITATION_RE.finditer(answer_md)}):
        if 1 <= n <= len(chunks):
            chunk = chunks[n - 1]
            citations.append(
                Citation(
                    n=n,
                    url=str(chunk.url),
                    title=chunk.title,
                    domain=chunk.domain,
                    resolved=chunk.domain in approved_domains,
                )
            )
        else:
            citations.append(Citation(n=n, resolved=False))
    return citations


def verify(
    answer_md: str,
    chunks: list[Chunk],
    confidence: float,
    approved_domains: set[str] | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Verdict:
    """Grades a draft answer against the chunks it was generated from.

    Grounding is not implemented in this iteration, so `grounded_score`
    stays 0.0 and a draft whose only fault is an invented fact will pass.
    Deliberate and documented rather than hidden - the three deterministic
    checks are useful on their own, and they need no model to run.

    approved_domains defaults to the same allowlist file stage 01 enforces
    at fetch time.
    """
    if approved_domains is None:
        approved_domains = load_approved_domains()

    citations = resolve_citations(answer_md, chunks, approved_domains)
    chunk_ids = [c.id for c in chunks]

    def fail(reason: str, score: float = 0.0) -> Verdict:
        return Verdict(
            passed=False, reason=reason, grounded_score=score,
            citations=citations, confidence=confidence, chunk_ids=chunk_ids,
        )

    # 1. Confident - there was never good enough source material.
    if confidence < confidence_threshold:
        return fail("low_confidence")

    # 2. Safe - highest harm, so it outranks the citation check even though
    #    both are cheap.
    if find_unsafe_instruction(answer_md) is not None:
        return fail("unsafe")

    # 3. Cited - every marker must resolve to a real chunk on an approved
    #    domain, and an answer with content must cite something.
    if not citations and len(answer_md.split()) >= _MIN_CONTENT_WORDS:
        return fail("bad_citation")
    if any(not c.resolved for c in citations):
        return fail("bad_citation")

    # 4. Grounded - next iteration.

    return Verdict(
        passed=True, reason=None, grounded_score=0.0,
        citations=citations, confidence=confidence, chunk_ids=chunk_ids,
    )
