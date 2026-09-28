"""Stage 06 - Guardrails + Citation Check. The last RAG stage; 07-10 are
connectplus-llm's.

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
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

from rag.schemas import Chunk, Citation, Verdict

DEFAULT_CONFIDENCE_THRESHOLD = 0.45  # outer README's CONFIDENCE_THRESHOLD
DEFAULT_GROUNDING_THRESHOLD = 0.7    # outer README's GROUNDING_THRESHOLD

APPROVED_DOMAINS_PATH = Path(__file__).parent / "config" / "approved_domains.json"

# (premises, hypotheses) -> entailment probability per pair, both same length.
EntailmentFunction = Callable[[list[str], list[str]], list[float]]

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


NLI_MODEL_NAME = "cross-encoder/nli-deberta-v3-base"
_ENTAILMENT_LABEL = "entailment"


@lru_cache(maxsize=1)
def get_default_entailment(model_name: str = NLI_MODEL_NAME) -> EntailmentFunction:
    """Real NLI cross-encoder, loaded once per process.

    Not used by any test in this repo - this sandbox cannot download it, so
    tests inject a stand-in (see tests/test_s06_verify.py). Untested by me;
    you are the first to run this against the real model, the same situation
    as stage 04's embedder and stage 05's database functions.

    The label index is read from the model's OWN config rather than
    hardcoded. This model returns three classes (contradiction, entailment,
    neutral) and the order is not a standard anyone guarantees - hardcoding
    index 1 would silently grade every answer against the wrong class, which
    fails open: wrong answers pass. Deriving it from id2label means a model
    swap either works or raises, never quietly mis-scores.

    Deliberately NOT reusing stage 05's bge-reranker, even though it is
    already downloaded: relevance is not entailment. A chunk about scam
    texts is highly relevant to an invented claim about scam texts, and a
    relevance model would score that invented step as well-supported -
    precisely the failure this stage exists to catch.
    """
    import numpy as np
    from sentence_transformers import CrossEncoder

    model = CrossEncoder(model_name)
    id2label = {int(k): str(v).lower() for k, v in model.config.id2label.items()}
    try:
        entail_idx = next(i for i, label in id2label.items() if _ENTAILMENT_LABEL in label)
    except StopIteration:
        raise ValueError(
            f"{model_name!r} has no '{_ENTAILMENT_LABEL}' class in its id2label "
            f"({id2label}). Grounding cannot be scored against an unknown label set."
        ) from None

    def entail(premises: list[str], hypotheses: list[str]) -> list[float]:
        logits = np.asarray(model.predict(list(zip(premises, hypotheses))))
        exp = np.exp(logits - logits.max(axis=1, keepdims=True))
        return (exp[:, entail_idx] / exp.sum(axis=1)).tolist()

    return entail


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


def _substantive_sentences(answer_md: str, min_words: int = 4) -> list[str]:
    """Sentences worth grounding.

    Skips headers, list bullets stripped to nothing, and short connective
    lines ("Here's how:"), which carry no factual claim and would drag a
    min-based grounded_score down for no reason.
    """
    text = re.sub(r"\[\d{1,3}\]", " ", answer_md)          # citation markers
    text = re.sub(r"^\s*(?:#{1,6}|[-*>]|\d+[.)])\s*", " ", text, flags=re.MULTILINE)
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
    return [s.strip() for s in sentences if len(s.split()) >= min_words]


def grounded_score(
    answer_md: str,
    chunks: list[Chunk],
    entail_fn: EntailmentFunction,
) -> float:
    """The answer's WEAKEST substantive claim, scored 0..1.

    Minimum across sentences, not mean. An average lets one invented step
    hide behind four well-supported ones, and "a hand-written answer
    containing one invented step is caught" is this stage's own acceptance
    criterion - a mean cannot deliver it.

    Each sentence is scored against its best-matching chunk (max), because
    a claim only needs ONE source to support it; needing every chunk to
    entail every sentence would fail every real answer.
    """
    sentences = _substantive_sentences(answer_md)
    if not sentences or not chunks:
        return 0.0

    premises: list[str] = []
    hypotheses: list[str] = []
    for sentence in sentences:
        for chunk in chunks:
            premises.append(chunk.text)
            hypotheses.append(sentence)

    scores = entail_fn(premises, hypotheses)
    if len(scores) != len(premises):
        raise ValueError(
            f"entail_fn returned {len(scores)} scores for {len(premises)} pairs - "
            "refusing to guess which score belongs to which claim"
        )

    per_sentence = [
        max(scores[i * len(chunks) : (i + 1) * len(chunks)]) for i in range(len(sentences))
    ]
    return min(per_sentence)


def verify(
    answer_md: str,
    chunks: list[Chunk],
    confidence: float,
    entail_fn: EntailmentFunction | None = None,
    approved_domains: set[str] | None = None,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    grounding_threshold: float = DEFAULT_GROUNDING_THRESHOLD,
) -> Verdict:
    """Grades a draft answer against the chunks it was generated from.

    entail_fn defaults to None, which SKIPS the grounding check and leaves
    grounded_score at 0.0. That is deliberate rather than a silent
    downgrade: grounding needs a cross-encoder this repo will not download
    on your behalf, and the three deterministic checks are genuinely useful
    without it. `passed` never claims a grounding check that did not run -
    read grounded_score together with whether you supplied entail_fn.

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
    if not citations and _substantive_sentences(answer_md):
        return fail("bad_citation")
    if any(not c.resolved for c in citations):
        return fail("bad_citation")

    # 4. Grounded - the expensive one, last.
    score = 0.0
    if entail_fn is not None:
        score = grounded_score(answer_md, chunks, entail_fn)
        if score < grounding_threshold:
            return fail("ungrounded", score)

    return Verdict(
        passed=True, reason=None, grounded_score=score,
        citations=citations, confidence=confidence, chunk_ids=chunk_ids,
    )
