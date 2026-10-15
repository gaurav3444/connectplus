"""The Chinese terminology and register lock.

Two jobs, and they are deliberately the same data seen from both ends:

* **Before generation** -- ``glossary_block`` and ``register_block`` are
  injected into the prompt, so the model is told which words to use.
* **After generation** -- ``audit`` checks the answer against the same
  lists, because telling a model not to do something is not the same as it
  not doing it.

``expand`` is the third use: a deterministic Chinese-to-English query
expansion that runs with no model at all, so a dead API degrades retrieval
rather than breaking it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

__all__ = ["termbase", "glossary_block", "register_block",
           "protected_nouns", "expand", "audit", "Violation"]

_DATA = Path(__file__).parent / "data" / "termbase_zh.json"


@lru_cache(maxsize=1)
def termbase() -> dict:
    """Load and cache the termbase."""
    with _DATA.open(encoding="utf-8") as f:
        return json.load(f)


@dataclass(frozen=True)
class Violation:
    """One thing wrong with a generated answer.

    Attributes:
        kind: ``address``, ``term``, ``formal`` or ``untranslated``.
        severity: ``error`` or ``warn``. Errors are correctness problems.
        found: What appeared in the answer.
        expected: What should have appeared.
        note: Why it matters, for whoever reads the eval output.
    """

    kind: str
    severity: str
    found: str
    expected: str
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Prompt blocks
# --------------------------------------------------------------------------

def glossary_block() -> str:
    """The locked-terms list, rendered for the prompt."""
    lines = []
    for entry in termbase()["glossary"]:
        avoid = "、".join(entry.get("avoid", []))
        line = f"- {entry['term']} ({entry['en']})"
        if avoid:
            line += f" — 不要用：{avoid}"
        lines.append(line)
    return "\n".join(lines)


def register_block() -> str:
    """The form-of-address rules, rendered for the prompt."""
    reg = termbase()["register"]
    lines = [
        f"- 称呼读者用「{reg['required_address']}」。",
        f"- 称呼我们自己用「{reg['self_reference']}」。",
    ]
    for f in reg["forbidden"]:
        lines.append(f"- 绝对不要用「{f['form']}」：{f['note']}")
    return "\n".join(lines)


def protected_nouns() -> list[str]:
    """Service and product names that stay in English."""
    return list(termbase()["protected_nouns"])


def plain_language_block() -> str:
    """Formal-to-plain substitutions, rendered for the prompt."""
    pairs = {k: v for k, v in termbase()["plain_language"].items()
             if not k.startswith("_")}
    return "、".join(f"「{k}」→「{v}」" for k, v in pairs.items())


# --------------------------------------------------------------------------
# Query expansion -- the deterministic floor
# --------------------------------------------------------------------------

def expand(query: str, limit: int = 10) -> list[str]:
    """Chinese query to English retrieval terms, with no model.

    Args:
        query: The question as typed.
        limit: Maximum terms to return. Retrieval degrades when the query
            becomes a bag of everything, so this stays short.

    Returns:
        De-duplicated English search terms, most specific first. Empty when
        nothing matched.
    """
    table = {k: v for k, v in termbase()["query_expansion"].items()
             if not k.startswith("_")}
    text = query or ""
    hits: list[str] = []

    # Service names first, and verbatim. A senior writes myGov, Centrelink
    # and Medicare in English inside an otherwise Chinese sentence, and those
    # names are the highest-value retrieval terms in the whole query -- they
    # name the exact page wanted. Generalising "myGov" into "government
    # website" is how a precise question becomes an unanswerable one.
    #
    # This is also the one thing the RAG team must know about our output:
    # these names reach them unchanged, so their index must not normalise
    # them away.
    for noun in sorted(protected_nouns(), key=len, reverse=True):
        if noun.lower() in text.lower() and noun not in hits:
            hits.append(noun)

    # Then the table, longest keys first, so 忘记密码 beats 密码 and the more
    # specific retrieval terms win.
    for key in sorted(table, key=len, reverse=True):
        if key in text:
            for term in table[key]:
                if term not in hits:
                    hits.append(term)
    return hits[:limit]


# --------------------------------------------------------------------------
# Post-generation audit
# --------------------------------------------------------------------------

def _protected_noun_pattern() -> re.Pattern:
    names = sorted(protected_nouns(), key=len, reverse=True)
    return re.compile("|".join(re.escape(n) for n in names), re.IGNORECASE)


@lru_cache(maxsize=1)
def _protected_re() -> re.Pattern:
    return _protected_noun_pattern()


def audit(answer: str, *, source_text: str = "") -> list[Violation]:
    """Check a generated Chinese answer against the termbase.

    Args:
        answer: The generated text.
        source_text: The retrieved chunks. Latin words that appear here are
            genuine source vocabulary, so they are not reported as
            untranslated English.

    Returns:
        Violations, errors first. An empty list means the answer is clean.
    """
    from .normalize import latin_runs, strip_citations

    text = strip_citations(answer or "")
    out: list[Violation] = []
    reg = termbase()["register"]

    # 1. Form of address. The correctness check, not a style note.
    for forbidden in reg["forbidden"]:
        form = forbidden["form"]
        # 你 is a substring of 你们 and of 您 in neither case -- but 你们
        # contains 你, so report the longer form only once.
        if form == "你" and "你们" in text:
            continue
        if form in text:
            out.append(Violation(
                kind="address",
                severity=forbidden["severity"],
                found=form,
                expected=reg["required_address"],
                note=forbidden["note"],
            ))

    # 2. Locked terminology. A synonym is not a style preference here: the
    # senior may be matching what they read against what is on their screen.
    for entry in termbase()["glossary"]:
        for wrong in entry.get("avoid", []):
            if wrong in text:
                out.append(Violation(
                    kind="term", severity="error",
                    found=wrong, expected=entry["term"],
                    note=f"Locked term for {entry['en']}.",
                ))

    # 3. Officialese that has a plain equivalent.
    for formal, plain in termbase()["plain_language"].items():
        if formal.startswith("_"):
            continue
        if formal in text:
            out.append(Violation(
                kind="formal", severity="warn",
                found=formal, expected=plain,
                note="Formal register; a plainer word exists.",
            ))

    # 4. Untranslated English. Protected nouns and anything present in the
    # sources are legitimate; the rest is English the reader cannot decode.
    protected = _protected_re()
    source_lower = (source_text or "").lower()
    seen: set[str] = set()
    for run in latin_runs(text):
        if len(run) < 3 or run.lower() in seen:
            continue
        if protected.fullmatch(run):
            continue
        seen.add(run.lower())
        if run.lower() in source_lower and len(run) > 4:
            # Appears verbatim in the sources: likely a real proper noun the
            # protected list has not caught up with. Worth flagging softly.
            out.append(Violation(
                kind="untranslated", severity="warn",
                found=run, expected="Chinese, or add to protected_nouns",
                note="English from the sources, left untranslated.",
            ))
        else:
            out.append(Violation(
                kind="untranslated", severity="error",
                found=run, expected="Chinese",
                note="English word a Chinese-only reader cannot decode.",
            ))

    out.sort(key=lambda v: 0 if v.severity == "error" else 1)
    return out
