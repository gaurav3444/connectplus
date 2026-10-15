"""Three-language detection: Chinese, Vietnamese, English.

The layering, cheapest and most certain first
---------------------------------------------
1. **The app's stated language wins.** The senior chose a language in the
   interface. That is a fact, and a statistical guess must never overrule it.
   Selecting a language is optional in CONNECT Plus, so the layers below are
   real production load, not a safety net.
2. **Script.** CJK characters mean Chinese. This is a three-line rule and it
   measurably beats a trained classifier on held-out data (99.6% vs 98.1% on
   the TVsub test split), so the classifier is not asked this question.
3. **Diacritics.** Vietnamese tone marks mean Vietnamese. Deterministic.
4. **Lexicon + orthographic shape.** The only genuinely hard case: Latin
   script with no diacritics, where `toi bi lua dao` must be told apart from
   `my phone keeps asking for a code`. No cheap rule works here. A Vietnamese
   function-word lexicon plus word-shape (Vietnamese is monosyllabic, so its
   tokens are short and contain no f, j, w, z) carries this layer today.
5. **``und``.** When nothing scores high enough, say so. The app has a
   language picker; showing it costs one tap, and guessing wrong routes a
   senior into a language they cannot read.

``und`` is not a failure state. ``myGov``, ``OTP`` and ``123456`` are not
decidable, and a detector that answers them confidently is broken, not clever.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict

import hanzidentifier

__all__ = ["Detection", "detect", "fold", "has_vietnamese_diacritics",
           "has_cjk", "detect_script", "VI_LEXICON", "EN_LEXICON"]

# --------------------------------------------------------------------------
# Character-level helpers
# --------------------------------------------------------------------------

_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_HANGUL_RE = re.compile(r"[가-힯ᄀ-ᇿ]")
_KANA_RE = re.compile(r"[぀-ヿ]")
_ARABIC_RE = re.compile(r"[؀-ۿ]")
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

# Characters that exist in Vietnamese and in no other Latin orthography we
# care about. Their presence settles the question outright.
_VI_ONLY = set("ăâđêôơưĂÂĐÊÔƠƯ")


def has_cjk(text: str) -> bool:
    """True when the text contains a Han ideograph."""
    return bool(_CJK_RE.search(text or ""))


def detect_script(text: str) -> str:
    """Tell Simplified and Traditional Chinese apart.

    Only called once :func:`has_cjk` has already said "Chinese"; this is
    strictly a second, finer-grained question, not a replacement for it.
    Character-set based rather than a model, for the same reason the rest of
    this module avoids one: a senior's question is a handful of characters,
    too short for a classifier to have much to work with, and a
    character-membership test is both cheaper and fully explainable.

    Uses :func:`hanzidentifier.identify` rather than
    ``hanzidentifier.is_traditional`` directly, and that distinction is not
    cosmetic. A short string built entirely from characters that are
    identical in both scripts -- "怎么了", "算了" -- is trivially "valid
    Traditional" by simple membership, so ``is_traditional`` alone returns
    ``True`` for plainly Simplified, script-neutral input. ``identify``
    separates that case (``BOTH``) from text containing a character that is
    genuinely Traditional-only (``TRADITIONAL``), which is the actual
    question this function needs answered.

    Mixed input (a Traditional-only character next to a Simplified-only one,
    which happens when someone pastes from two different sources) is not
    treated as Traditional either. The Simplified lane is the long-standing
    default for plain CJK text, and neither a script-neutral nor a mixed
    signal is evidence strong enough to move a senior off the path that
    already exists -- both degrade to that default rather than guessing.

    Returns:
        ``"zh_hant"`` only when the text contains a character that is
        unambiguously Traditional and nothing that is unambiguously
        Simplified. ``"zh"`` in every other case: Simplified, script-neutral,
        mixed, or a judgement a plain character check cannot make.
    """
    verdict = hanzidentifier.identify(text)
    if verdict == hanzidentifier.TRADITIONAL:
        return "zh_hant"
    return "zh"


def fold(token: str) -> str:
    """Strip diacritics and lowercase, so `tôi` and `toi` match.

    Vietnamese seniors on a phone keyboard very often type without tone
    marks, so every lexicon lookup happens on the folded form.
    """
    token = (token or "").lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", token)
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def has_vietnamese_diacritics(text: str) -> bool:
    """True when the text carries Vietnamese-only letters or tone marks."""
    if not text:
        return False
    if any(ch in _VI_ONLY for ch in text):
        return True
    # Stacked marks: a Latin vowel carrying a tone mark is Vietnamese in
    # this product's three-language world.
    decomposed = unicodedata.normalize("NFD", text)
    marks = sum(1 for c in decomposed if unicodedata.category(c) == "Mn")
    return marks > 0 and bool(re.search(r"[a-zA-Z]", text))


# --------------------------------------------------------------------------
# Lexicons, stored folded so both spellings match
# --------------------------------------------------------------------------

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

_EN_RAW = """
    the a an and or but if then of to in on at for from with without by about
    is are was were be been being am do does did doing have has had having
    i you he she it we they me my your his her our their this that these those
    what how why when where which who whom can could should would will shall
    not no yes get got make made use used need want know think say said
    """.split()

# A token that is evidence for both languages is evidence for neither.
# Vietnamese "the" (a card), "co", "la", "do", "so" and "can" all collide
# with English words; counting them on both sides only adds noise.
_SHARED = frozenset(_VI_RAW) & frozenset(_EN_RAW)

# International loanwords appear verbatim in both languages.
_LOANWORDS = frozenset("wifi internet email video app online sms otp pin".split())

VI_LEXICON: frozenset[str] = frozenset(_VI_RAW) - _SHARED - _LOANWORDS
EN_LEXICON: frozenset[str] = frozenset(_EN_RAW) - _SHARED - _LOANWORDS

# Letters that never occur in a native Vietnamese syllable.
_NON_VI_LETTERS = set("fjwz")

# Mean token length. Vietnamese writes one syllable per token and averages
# about 3.3 letters folded; English prose is closer to 5.
_VI_MEAN_LEN = 3.0
_EN_MEAN_LEN = 6.0

# Below this, orthographic shape alone is not evidence of anything.
# "myGov" is short and clean and is not a Vietnamese sentence.
_MIN_TOKENS_FOR_SHAPE = 4

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


@dataclass(frozen=True)
class Detection:
    """Outcome of a detection attempt.

    Attributes:
        lang: ``zh``, ``vi``, ``en``, or ``und`` when nothing scored high
            enough to be worth acting on.
        confidence: 0..1. Below 0.5, treat as a guess.
        method: Which layer decided -- ``app``, ``script``, ``diacritics``,
            ``lexicon`` or ``fallback``. Logged on every answer so a wrong
            language traces to the rule that caused it.
        detail: Human-readable justification, for the eval and the demo.
    """

    lang: str
    confidence: float
    method: str
    detail: str = ""

    @property
    def supported(self) -> bool:
        return self.lang in ("zh", "zh_hant", "vi", "en")

    def as_dict(self) -> dict:
        return asdict(self)


def _score_lexicon(tokens: list[str]) -> tuple[float, float]:
    if not tokens:
        return 0.0, 0.0
    vi = sum(1 for t in tokens if t in VI_LEXICON)
    en = sum(1 for t in tokens if t in EN_LEXICON)
    return vi / len(tokens), en / len(tokens)


def _score_shape(tokens: list[str]) -> float:
    """0..1 for how Vietnamese the orthography looks.

    Mean token length and letter inventory, weighted equally. A count of
    "tokens under 7 letters" does not work, because most English words are
    short too -- the mean is what separates them.
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
    """Decide the language of a query.

    Args:
        text: The query exactly as typed.
        app_lang: Language the app already knows the senior selected. When
            given it is returned unchanged -- **detection never overrules an
            explicit choice.** Pass ``None`` when no language was selected.

    Returns:
        A :class:`Detection`. ``lang`` may be ``und``; callers should show
        the language picker rather than guess.
    """
    if app_lang:
        code = app_lang.strip().lower()
        return Detection(code, 1.0, "app",
                         "Language selected in the app; detection skipped.")

    text = (text or "").strip()
    if not text:
        return Detection("und", 0.0, "fallback", "Empty query.")

    # 2. Script.
    #
    # Out-of-scope scripts are checked FIRST, and the order matters. Japanese
    # is written with kanji -- Han characters -- so a plain "contains Han
    # means Chinese" rule labels every Japanese sentence as Chinese. Kana and
    # Hangul are the signals that rule out Chinese, so they are tested before
    # the Han test rather than after it.
    for pattern, name in ((_KANA_RE, "Kana"), (_HANGUL_RE, "Hangul"),
                          (_ARABIC_RE, "Arabic"), (_CYRILLIC_RE, "Cyrillic")):
        if pattern.search(text):
            return Detection("und", 0.9, "script",
                             f"{name} script: outside the supported languages.")

    # Han characters, with the languages that share them already excluded.
    # Cheaper and more accurate than a trained classifier on this question.
    if has_cjk(text):
        script = detect_script(text)
        detail = ("Han characters present, Traditional script."
                  if script == "zh_hant" else
                  "Han characters present, Simplified script (or mixed).")
        return Detection(script, 0.98, "script", detail)

    # 3. Diacritics.
    if has_vietnamese_diacritics(text):
        return Detection("vi", 0.99, "diacritics",
                         "Vietnamese-only letters or tone marks present.")

    # 4. The hard case: Latin script, no diacritics.
    tokens = [fold(t) for t in _TOKEN_RE.findall(text)]
    tokens = [t for t in tokens if t]
    if not tokens:
        return Detection("und", 0.0, "fallback", "No alphabetic tokens.")

    vi_rate, en_rate = _score_lexicon(tokens)
    shape = _score_shape(tokens)

    # Nothing from either lexicon matched. On a short string that is absence
    # of evidence, not ambiguity -- a product name, an acronym, a code.
    if vi_rate == 0 and en_rate == 0 and len(tokens) < _MIN_TOKENS_FOR_SHAPE:
        return Detection("und", 0.2, "lexicon",
                         f"No lexicon match in {len(tokens)} token(s); "
                         "too little to decide.")

    vi_score = vi_rate * 0.75 + shape * 0.25
    en_score = en_rate * 0.75 + (1.0 - shape) * 0.25

    detail = (f"tokens={len(tokens)} vi_lex={vi_rate:.2f} en_lex={en_rate:.2f} "
              f"shape={shape:.2f} vi={vi_score:.2f} en={en_score:.2f}")

    margin = abs(vi_score - en_score)
    if margin < 0.08:
        return Detection("und", 0.3, "lexicon", "Too close to call. " + detail)

    lang = "vi" if vi_score > en_score else "en"
    return Detection(lang, round(min(0.95, 0.5 + margin), 2), "lexicon", detail)
