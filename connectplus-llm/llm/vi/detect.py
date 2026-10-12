"""Language detection tuned for the way CONNECT Plus users actually type.

The problem this solves
-----------------------
``langdetect`` is trained on well-formed prose. Two things break it here:

1. **Queries are short.** "toi bi lua dao" is four tokens. Statistical
   detectors are unreliable below roughly ten.
2. **Diacritics are optional.** Vietnamese seniors on a phone keyboard very
   often type without dau. Stripped of its tone marks, Vietnamese loses the
   character-level signal a detector leans on and is regularly reported as
   English, Indonesian, Malay or Somali.

Getting this wrong is not cosmetic. The detected language selects the answer
language, so a misdetection means a Vietnamese senior is answered in English -
exactly the failure CONNECT Plus exists to prevent.

The rule this module enforces
-----------------------------
**The language the app already knows always wins.** The user picked a language
in the interface; that is a stated fact and a detector must never override it.
Detection is a *fallback* for free typed text where no such choice exists, and
:func:`detect` will only disagree with the app when the app said nothing.

Method
------
Diacritics present -> Vietnamese, decided on the character set alone.
Otherwise a lexicon score: Vietnamese function words and everyday nouns
(folded to their no-diacritic spelling) against an English stopword set,
with orthographic shape - Vietnamese is monosyllabic, so its tokens are short -
as the tiebreaker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from .normalize import fold, has_vietnamese_diacritics, syllables

__all__ = ["Detection", "detect", "VI_LEXICON", "EN_LEXICON"]

# --------------------------------------------------------------------------
# Lexicons. Stored folded (no diacritics) so both spellings match.
# --------------------------------------------------------------------------

# Function words, pronouns and the everyday nouns that turn up in digital
# literacy questions. Chosen for frequency, not coverage: a detector wants
# words that appear in almost every sentence.
_VI_RAW = """
    toi minh chung ta ong ba co chu bac anh chi em con chau ho ai
    khong duoc cua va voi cho den di lam nay kia gi sao nao
    khi neu nhung ma tren duoi trong ngoai ra vao len xuong roi chua da se
    dang rat qua hon nhat moi cu van cung chi ca tat deu bi phai can
    muon thich biet hieu noi nghe xem thay giup
    dien thoai may tinh mang tin nhan cuoc goi tai khoan
    mat khau ma so tien ngan hang ung dung trang web thu dien tu
    dang nhap dang ky bam nhan mo tat cai dat xoa gui luu
    bao nhieu dau day gio hom ngay thang nam lan nua tiep tuc
    """.split()

# English stopwords, so an English query is not scored as Vietnamese purely
# because "co", "la" and "ma" happen to look like nothing.
_EN_RAW = """
    the a an and or but if then of to in on at for from with without by about
    is are was were be been being am do does did doing have has had having
    i you he she it we they me my your his her our their this that these those
    what how why when where which who whom can could should would will shall
    not no yes get got make made use used need want know think say said
    """.split()

# Tokens that are evidence for BOTH languages are evidence for neither.
# Vietnamese "the" (the, a card) folds onto the English article; "co", "la",
# "do", "so", "can" and friends collide the same way. Counting them for both
# sides just adds noise, so they are removed from both.
_SHARED = frozenset(_VI_RAW) & frozenset(_EN_RAW)

# International loanwords are also excluded: "wifi", "internet", "email" and
# "video" appear verbatim in Vietnamese sentences and English ones alike.
# Leaving "wifi" in the Vietnamese list made "connect my phone to wifi" score
# as ambiguous, which is exactly the kind of silent miss this set exists to
# prevent.
_LOANWORDS = frozenset("wifi internet email video app online sms otp pin".split())

VI_LEXICON: frozenset[str] = frozenset(_VI_RAW) - _SHARED - _LOANWORDS
EN_LEXICON: frozenset[str] = frozenset(_EN_RAW) - _SHARED - _LOANWORDS

# Latin letters that never occur in native Vietnamese syllables. Their presence
# is strong evidence of an English or borrowed token.
_NON_VI_LETTERS = set("fjwz")

# Mean token length. Vietnamese writes one syllable per token and averages
# around 3.3 letters once diacritics are folded away; English prose averages
# closer to 5. These two bounds map that gap onto 0..1.
_VI_MEAN_LEN = 3.0
_EN_MEAN_LEN = 6.0

# Below this many tokens, orthographic shape alone is not evidence of anything.
# "myGov" is short and clean and is not a Vietnamese sentence.
_MIN_TOKENS_FOR_SHAPE_ONLY = 4

_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_ARABIC_RE = re.compile(r"[؀-ۿ]")


@dataclass(frozen=True)
class Detection:
    """Outcome of a detection attempt.

    Attributes:
        lang: ISO 639-1 code, or ``"und"`` when nothing scored high enough.
        confidence: 0..1. Anything below ``0.5`` should be treated as a guess.
        method: Which path decided it - ``app``, ``diacritics``, ``script``,
            ``lexicon`` or ``fallback``. Logged on every answer so a wrong
            language can be traced to the rule that caused it.
        detail: Human-readable justification, for the eval report.
    """

    lang: str
    confidence: float
    method: str
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _score_lexicon(tokens: list[str]) -> tuple[float, float]:
    """Return (vietnamese_hit_rate, english_hit_rate) over folded tokens."""
    if not tokens:
        return 0.0, 0.0
    vi = sum(1 for t in tokens if t in VI_LEXICON)
    en = sum(1 for t in tokens if t in EN_LEXICON)
    return vi / len(tokens), en / len(tokens)


def _score_shape(tokens: list[str]) -> float:
    """Score 0..1 for how Vietnamese the *orthography* looks.

    Two signals, weighted equally:

    * **Mean token length.** Vietnamese is written one syllable at a time, so
      its tokens are short. A count of "tokens under 7 letters" does not work -
      most English words are under 7 letters too - so this uses the mean.
    * **Letter inventory.** Native Vietnamese syllables contain no f, j, w or z.
    """
    alpha = [t for t in tokens if t.isalpha()]
    if not alpha:
        return 0.0
    mean_len = sum(len(t) for t in alpha) / len(alpha)
    length_signal = (_EN_MEAN_LEN - mean_len) / (_EN_MEAN_LEN - _VI_MEAN_LEN)
    length_signal = max(0.0, min(1.0, length_signal))
    clean = sum(1 for t in alpha if not (_NON_VI_LETTERS & set(t))) / len(alpha)
    return length_signal * 0.5 + clean * 0.5


def detect(text: str, app_lang: str | None = None) -> Detection:
    """Decide the language of a user query.

    Args:
        text: Raw query as typed.
        app_lang: Language the CONNECT Plus app already knows the user chose.
            When supplied this is returned unchanged - **the detector never
            overrules an explicit user choice.**

    Returns:
        A :class:`Detection`.
    """
    if app_lang:
        return Detection(
            lang=app_lang.lower(),
            confidence=1.0,
            method="app",
            detail="Language supplied by the client; detection skipped.",
        )

    text = (text or "").strip()
    if not text:
        return Detection("und", 0.0, "fallback", "Empty query.")

    # Non-Latin scripts are unambiguous; settle them before any scoring.
    if _CJK_RE.search(text):
        return Detection("zh", 0.95, "script", "CJK characters present.")
    if _ARABIC_RE.search(text):
        return Detection("ar", 0.95, "script", "Arabic script present.")

    if has_vietnamese_diacritics(text):
        return Detection(
            "vi", 0.99, "diacritics",
            "Vietnamese-only characters or tone marks present.",
        )

    tokens = [fold(t) for t in syllables(text)]
    tokens = [t for t in tokens if t.isalpha()]
    if not tokens:
        return Detection("und", 0.0, "fallback", "No alphabetic tokens.")

    vi_rate, en_rate = _score_lexicon(tokens)
    shape = _score_shape(tokens)

    # No function word from either language matched. On a short string that is
    # not ambiguity, it is absence of evidence - a product name, an acronym.
    # Guessing here is how "myGov" becomes a Vietnamese sentence.
    if vi_rate == 0 and en_rate == 0 and len(tokens) < _MIN_TOKENS_FOR_SHAPE_ONLY:
        return Detection("und", 0.2, "lexicon",
                         f"No lexicon match in {len(tokens)} token(s); "
                         "too little to decide.")

    # Lexicon hits are the primary evidence; shape only breaks near-ties.
    vi_score = vi_rate * 0.75 + shape * 0.25
    en_score = en_rate * 0.75 + (1.0 - shape) * 0.25

    detail = (
        f"tokens={len(tokens)} vi_lex={vi_rate:.2f} en_lex={en_rate:.2f} "
        f"shape={shape:.2f} vi_score={vi_score:.2f} en_score={en_score:.2f}"
    )

    margin = abs(vi_score - en_score)
    if margin < 0.08:
        # Genuinely ambiguous - usually a two-token query. Say so rather than
        # guessing; the caller should prompt the user or use the app default.
        return Detection("und", 0.3, "lexicon", "Ambiguous. " + detail)

    lang = "vi" if vi_score > en_score else "en"
    confidence = min(0.95, 0.5 + margin)
    return Detection(lang, round(confidence, 2), "lexicon", detail)
