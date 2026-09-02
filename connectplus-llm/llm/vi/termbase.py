"""Locked Vietnamese terminology, register rules and query expansion.

Loads ``data/termbase.json`` once and exposes three jobs:

* **Feed the prompt.** :func:`glossary_block` and :func:`register_block` render
  the locked terms and forms of address into the generation prompt, so the
  model is told the wording rather than asked to invent it.
* **Audit the answer.** :func:`audit` re-reads the generated Vietnamese and
  reports forbidden synonyms, disrespectful address and formal register that a
  senior would struggle with. This runs *after* generation, because telling a
  model not to do something is not the same as it not doing it.
* **Expand the query.** :func:`expand` maps Vietnamese intent phrases onto
  English retrieval terms deterministically, with no model call. This is the
  floor under the LLM rewrite: when the provider is down, or the rewrite comes
  back nonsense, retrieval still gets usable English.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .normalize import fold

__all__ = [
    "Violation",
    "termbase",
    "protected_nouns",
    "expand",
    "audit",
    "glossary_block",
    "register_block",
]

_DATA_PATH = Path(__file__).parent / "data" / "termbase.json"

# Severity ordering used when sorting audit output.
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _contains_phrase(folded_haystack: str, phrase: str) -> bool:
    """Whole-token phrase match against already-folded text.

    Plain substring matching is wrong here and quietly produces nonsense:
    ``fold("ap")`` is inside ``fold("truy cap")``, so the forbidden term "ap"
    would fire on the innocent word "truy cap". Vietnamese syllables are short
    and share letters constantly, so every termbase lookup goes through this.
    """
    folded_phrase = fold(phrase)
    if not folded_phrase:
        return False
    pattern = r"(?<![0-9A-Za-z])" + re.escape(folded_phrase) + r"(?![0-9A-Za-z])"
    return re.search(pattern, folded_haystack) is not None


@dataclass(frozen=True)
class Violation:
    """One problem found in generated Vietnamese.

    Attributes:
        kind: ``forbidden_term``, ``address``, ``untranslated_noun`` or
            ``formal_register``.
        severity: ``error`` fails the answer in eval; ``warning`` is scored but
            does not fail; ``info`` is advisory.
        found: The offending text as it appeared.
        expected: What should have been written instead.
        note: Why it matters, carried through to the eval report.
    """

    kind: str
    severity: str
    found: str
    expected: str = ""
    note: str = ""

    def __str__(self) -> str:  # pragma: no cover - display only
        arrow = f" -> {self.expected}" if self.expected else ""
        return f"[{self.severity}] {self.kind}: {self.found!r}{arrow}"


@lru_cache(maxsize=1)
def termbase() -> dict:
    """Parsed ``termbase.json``. Cached; the file is read once per process."""
    with _DATA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def protected_nouns() -> list[str]:
    """Proper nouns that must appear verbatim, never translated."""
    return list(termbase()["protected_nouns"])


# --------------------------------------------------------------------------
# Query expansion (deterministic, no model)
# --------------------------------------------------------------------------

def expand(query_vi: str) -> list[str]:
    """Map a Vietnamese query onto English retrieval terms.

    Matching is done on the folded form, so ``"tôi bị lừa đảo"`` and
    ``"toi bi lua dao"`` both hit the ``lua dao`` entry.

    Args:
        query_vi: The user's query, with or without diacritics.

    Returns:
        English terms, longest-phrase matches first, de-duplicated and order
        preserved. Empty when nothing in the termbase matches - that is a
        legitimate outcome, and the caller should fall back to the LLM rewrite.
    """
    folded = fold(query_vi)
    table = {k: v for k, v in termbase()["query_expansion"].items()
             if not k.startswith("_")}

    # Longest phrases first: "tin nhan lua dao" should win over "lua dao".
    hits: list[str] = []
    for phrase in sorted(table, key=len, reverse=True):
        if phrase in folded:
            hits.extend(table[phrase])

    seen: set[str] = set()
    out: list[str] = []
    for term in hits:
        if term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
    return out


# --------------------------------------------------------------------------
# Prompt fragments
# --------------------------------------------------------------------------

def glossary_block() -> str:
    """Locked terminology, rendered for injection into the prompt."""
    lines = []
    for entry in termbase()["glossary"]:
        line = f"- {entry['en']} = {entry['vi']}"
        if entry.get("forbidden"):
            line += f"  (never: {', '.join(entry['forbidden'])})"
        lines.append(line)
    nouns = ", ".join(protected_nouns())
    lines.append(f"- Keep these names in English exactly as written: {nouns}")
    return "\n".join(lines)


def register_block() -> str:
    """Forms-of-address rules, rendered for injection into the prompt."""
    reg = termbase()["register"]
    preferred = ", ".join(reg["preferred_address"])
    forbidden = ", ".join(reg["forbidden_address"])
    plain = termbase()["plain_language"]["prefer_plain"]
    plain_lines = "\n".join(f"  - write {v} instead of {k}" for k, v in plain.items())
    return (
        f"Address the reader as: {preferred}. The reader is an older adult.\n"
        f"Never address the reader as: {forbidden}.\n"
        f"Refer to this service as: {reg['self_reference']}.\n"
        f"Prefer everyday words over formal ones:\n{plain_lines}"
    )


# --------------------------------------------------------------------------
# Answer audit
# --------------------------------------------------------------------------

def audit(answer_vi: str, *, source_text: str = "") -> list[Violation]:
    """Check generated Vietnamese against the termbase.

    Args:
        answer_vi: The generated answer.
        source_text: The retrieved English chunks, when available. Used only to
            decide whether a protected noun was *supposed* to appear: a noun
            missing from an answer whose sources never mentioned it is not a
            violation.

    Returns:
        Violations, most severe first. An empty list means the answer is clean.
    """
    found: list[Violation] = []
    folded_answer = fold(answer_vi)
    tb = termbase()

    # 1. Forbidden synonyms for locked terms.
    for entry in tb["glossary"]:
        for bad in entry.get("forbidden", []):
            if _contains_phrase(folded_answer, bad):
                found.append(Violation(
                    kind="forbidden_term",
                    severity="error",
                    found=bad,
                    expected=entry["vi"],
                    note=entry.get("note", f"Locked term for '{entry['en']}'."),
                ))

    # 2. Disrespectful or over-familiar address.
    for bad in tb["register"]["forbidden_address"]:
        if _contains_phrase(folded_answer, bad):
            found.append(Violation(
                kind="address",
                severity="error",
                found=bad,
                expected=tb["register"]["preferred_address"][0],
                note="The reader is a senior; peer or junior address is disrespectful.",
            ))

    # 3. Proper nouns that were translated away.
    if source_text:
        folded_source = fold(source_text)
        for noun in tb["protected_nouns"]:
            in_source = _contains_phrase(folded_source, noun)
            in_answer = _contains_phrase(folded_answer, noun)
            if in_source and not in_answer:
                found.append(Violation(
                    kind="untranslated_noun",
                    severity="warning",
                    found=f"(missing) {noun}",
                    expected=noun,
                    note="Named in the sources but absent from the answer; "
                         "the reader cannot follow a step that names no app.",
                ))

    # 4. Formal register where a plain word exists.
    for formal, plain in tb["plain_language"]["prefer_plain"].items():
        if _contains_phrase(folded_answer, formal):
            found.append(Violation(
                kind="formal_register",
                severity="warning",
                found=formal,
                expected=plain,
                note="Correct Vietnamese, but harder reading than it needs to be.",
            ))

    found.sort(key=lambda v: _SEVERITY_RANK.get(v.severity, 9))
    return found
