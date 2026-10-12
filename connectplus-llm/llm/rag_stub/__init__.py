"""A stand-in for ``connectplus-rag``.

``connectplus-rag`` owns retrieval and verification and does not exist yet. The
README's own advice is to develop stages 07-10 against a fixture and a stubbed
verifier from day one, so they are not blocked on the crawl. This is that stub.

**It is not a retrieval system and its verdicts are not verification.** Lexical
overlap is a crude proxy for both. It exists so the Vietnamese layer can be
built, tested and evaluated today, and so the seam it plugs into is the real
one: when the sibling repo lands, ``from rag import retrieve, verify`` replaces
this import and nothing above it changes.

:func:`retrieve` and :func:`verify` already have the real signatures.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from ..schemas import Chunk, Verdict

__all__ = ["retrieve", "verify", "corpus", "poisoned_chunk", "IS_STUB",
           "REFUSAL_THRESHOLD"]

#: Read by callers that want to warn a user, or annotate a report, that the
#: numbers came from the stub rather than the real retriever.
IS_STUB = True

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "f06_retrieved.json"

_WORD_RE = re.compile(r"[a-z0-9]+")

#: Calibration constant for :func:`retrieve`. See the note where it is used.
_CONFIDENCE_DIVISOR = 2.6

#: Below this confidence, stage 10 should refuse rather than answer.
#: Measured on the fixture corpus: questions it covers score 0.29 to 1.00,
#: questions it does not (medical advice, immigration, product choice) score
#: 0.00 to 0.15. 0.25 sits in the gap. This number is a property of the stub
#: and must be re-derived against the real retriever.
REFUSAL_THRESHOLD = 0.25

# Words too common to carry retrieval signal in this tiny corpus.
_STOP = frozenset("""
a an the and or but if of to in on at for from with without by about is are was
were be been being am do does did have has had you your my me it this that these
those what how why when where which can could should would will not no yes get
got make made use used need want know i we they he she them their there
""".split())


# Crude suffix stripping. Without it "phone runs slowly" and "phone running
# slow" share no tokens at all, and an on-topic question scores like an
# off-topic one. A real retriever uses embeddings and needs none of this.
_SUFFIXES = ("ingly", "edly", "ing", "ies", "ed", "ly", "es", "s")


def _stem(word: str) -> str:
    for suf in _SUFFIXES:
        if len(word) > len(suf) + 2 and word.endswith(suf):
            base = word[: -len(suf)]
            return base[:-1] if base.endswith(base[-1:] * 2) else base
    return word


def _tokens(text: str) -> list[str]:
    return [_stem(w) for w in _WORD_RE.findall(text.lower())
            if w not in _STOP and len(w) > 1]


@lru_cache(maxsize=1)
def _fixture() -> dict:
    with _FIXTURE.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def corpus() -> list[Chunk]:
    """The fixture passages, as :class:`~llm.schemas.Chunk` objects."""
    return [Chunk(**{k: v for k, v in c.items() if not k.startswith("_")})
            for c in _fixture()["chunks"]]


def poisoned_chunk() -> Chunk:
    """The prompt-injection fixture. Never returned by :func:`retrieve`."""
    raw = _fixture()["poisoned_chunk"]
    return Chunk(**{k: v for k, v in raw.items() if not k.startswith("_")})


@lru_cache(maxsize=1)
def _idf() -> dict[str, float]:
    """Inverse document frequency over the fixture corpus."""
    docs = [set(_tokens(c.title + " " + c.text)) for c in corpus()]
    n = len(docs)
    df = Counter(t for d in docs for t in d)
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


def retrieve(query_en: str, lang: str = "vi", k: int = 3) -> tuple[list[Chunk], float]:
    """Return the top ``k`` passages for an English query, and a confidence.

    Scoring is TF-IDF cosine-ish overlap. Deliberately simple - a real
    implementation uses BGE-m3 embeddings and lives in ``connectplus-rag``.

    Args:
        query_en: English query from stage 07.
        lang: The user's language. Unused here; present because the real
            signature takes it (retrieval may prefer translated pages).
        k: How many passages to return.

    Returns:
        ``(chunks, confidence)``. Confidence is 0..1 and is what tells stage 10
        whether the knowledge base can cover the question at all. A question the
        corpus does not cover scores low, which is how refusals get triggered.
    """
    q = _tokens(query_en)
    if not q:
        return [], 0.0
    idf = _idf()
    scored: list[tuple[float, Chunk]] = []
    for c in corpus():
        doc = _tokens(c.title + " " + c.title + " " + c.text)  # title weighted x2
        if not doc:
            continue
        counts = Counter(doc)
        raw = sum(counts[t] * idf.get(t, 0.0) for t in set(q))
        scored.append((raw / math.sqrt(len(doc)), c))

    scored.sort(key=lambda p: p[0], reverse=True)
    top = scored[:k]
    if not top or top[0][0] <= 0:
        return [], 0.0

    # Squash the raw score into 0..1. The divisor is calibrated on this
    # fixture so an on-topic question lands near 0.6-1.0 and a question the
    # corpus does not cover stays below the 0.35 refusal threshold used by the
    # eval and by stage 10. Recalibrate when the real retriever replaces this.
    confidence = min(1.0, top[0][0] / _CONFIDENCE_DIVISOR)
    chunks = [Chunk(id=c.id, url=c.url, title=c.title, domain=c.domain,
                    text=c.text, score=round(s, 3)) for s, c in top]
    return chunks, round(confidence, 3)


def verify(draft: str, chunks: list[Chunk], *, lang: str = "vi") -> Verdict:
    """Grade a draft answer against the passages it was given.

    Real verification compares claims to source text and is the safety
    backstop of the whole system. This stub can only check something much
    weaker: whether the answer cites at all, and whether the numbers, URLs and
    proper nouns it states appear somewhere in the sources. That catches the
    single most dangerous failure mode - an invented phone number or an
    invented service name - and nothing subtler.

    Args:
        draft: The generated answer.
        chunks: The passages that were in the prompt.
        lang: Answer language. Unused; part of the real signature.

    Returns:
        A :class:`~llm.schemas.Verdict`.
    """
    if not draft.strip():
        return Verdict(grounded=False, confidence=0.0, refused=True,
                       refusal_reason="empty draft")
    if not chunks:
        return Verdict(grounded=False, confidence=0.0, refused=True,
                       refusal_reason="no sources retrieved")

    source_text = " ".join(c.text + " " + c.url for c in chunks).lower()
    unsupported: list[str] = []

    # Numbers are the highest-risk invention: a wrong phone number or a wrong
    # fee sends a senior somewhere real and harmful.
    for num in re.findall(r"\b\d[\d\s]{4,}\b", draft):
        compact = num.replace(" ", "")
        if compact not in source_text.replace(" ", ""):
            unsupported.append(num.strip())

    # Any URL in the answer must be one we supplied.
    allowed_urls = {c.url.lower() for c in chunks}
    for url in re.findall(r"https?://\S+", draft.lower()):
        if not any(url.startswith(a) for a in allowed_urls):
            unsupported.append(url)

    cited = bool(re.search(r"\[\d{1,2}\]", draft))
    grounded = not unsupported and cited

    if unsupported:
        reason = "answer contains details not present in the sources"
    elif not cited:
        reason = "answer cites no sources"
    else:
        reason = ""

    return Verdict(
        grounded=grounded,
        confidence=0.85 if grounded else 0.2,
        refused=not grounded,
        refusal_reason=reason,
        unsupported_claims=unsupported[:5],
    )
