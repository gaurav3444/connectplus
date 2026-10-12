"""Vietnamese terminology and register lock.

ATTRIBUTION -- READ BEFORE EDITING
-----------------------------------
The Vietnamese lane is **Deval Patel's work**. This module is a slim,
functionally equivalent stand-in so the integrated pipeline runs and the
demo can show both languages side by side.

**On merge, replace this package with his actual files** from
``connectplus-llm`` branch ``Deval`` -- ``llm/vi/termbase.py``,
``normalize.py``, ``readability.py`` and ``data/termbase.json``. His versions
carry 29 locked terms, 36 protected nouns, a 16-pair plain-language map and
a 42-entry query-expansion table; this one carries enough of each to exercise
the pipeline honestly, and no more.

The interface below is the contract the rest of the pipeline uses, so
swapping his implementation in requires no change above this file.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, asdict
from functools import lru_cache

__all__ = ["glossary_block", "register_block", "protected_nouns",
           "expand", "audit", "Violation"]

REQUIRED_ADDRESS = "ông/bà"
SELF_REFERENCE = "chúng tôi"

# Addressing a 75-year-old as `bạn` is not informal, it is disrespectful --
# and `bạn` is what every model reaches for, because web copy is written for
# thirty-year-olds. Same class of problem as 你 vs 您 in the Chinese lane.
FORBIDDEN_ADDRESS = [
    ("bạn", "error", "Familiar second person. Use ông/bà for an older reader."),
    ("mày", "error", "Rude second person."),
    ("cậu", "error", "Peer address; wrong for a senior."),
    ("em", "warn", "Addresses the reader as junior."),
]

GLOSSARY = [
    ("xác thực hai bước", "two-factor authentication", ["xác minh 2 yếu tố", "xác thực 2 lớp"]),
    ("mã xác minh", "verification code", ["mã OTP", "mã kiểm tra"]),
    ("mật khẩu", "password", ["mã khẩu"]),
    ("tài khoản", "account", ["trương mục"]),
    ("đăng nhập", "log in", ["truy nhập"]),
    ("tin nhắn lừa đảo", "scam text message", ["tin nhắn gian lận"]),
    ("trang web giả mạo", "phishing website", ["web lừa"]),
    ("kẻ lừa đảo", "scammer", ["đối tượng lừa đảo"]),
    ("đường dẫn", "link", ["liên kết"]),
    ("ứng dụng", "app", ["phần mềm ứng dụng"]),
    ("cài đặt", "settings", ["thiết lập"]),
    ("chặn", "block", ["ngăn chặn"]),
    ("báo cáo", "report", ["trình báo"]),
    ("gọi video", "video call", ["cuộc gọi hình ảnh"]),
    ("thông dịch viên", "interpreter", ["phiên dịch viên"]),
]

PROTECTED_NOUNS = [
    "myGov", "Centrelink", "Medicare", "Services Australia", "Scamwatch",
    "eSafety", "Be Connected", "ACMA", "ATO", "TIS National",
    "Telstra", "Optus", "NBN", "Zalo", "Viber", "WhatsApp", "Facebook",
    "Messenger", "Gmail", "Outlook", "Google", "Apple", "iPhone", "Android",
    "Wi-Fi", "SMS", "PIN", "OTP", "PayPal", "Australia Post",
]

PLAIN_LANGUAGE = {
    "truy cập": "vào",
    "thực hiện": "làm",
    "tiến hành": "làm",
    "nhằm": "để",
    "đồng thời": "và",
    "trong trường hợp": "nếu",
    "vui lòng": "xin",
    "tuyệt đối không": "đừng",
}

QUERY_EXPANSION = {
    "lừa đảo": ["scam", "fraud", "phishing"],
    "lua dao": ["scam", "fraud", "phishing"],
    "mat tien": ["scam victim", "contact bank", "report a scam"],
    "mất tiền": ["scam victim", "contact bank", "report a scam"],
    "tin nhắn": ["text message", "sms", "scam", "phishing"],
    "tin nhan": ["text message", "sms", "scam", "phishing"],
    "tin nhắn lạ": ["suspicious text message", "scam sms", "phishing"],
    "doc ma": ["never share", "verification code", "scam"],
    "đọc mã": ["never share", "verification code", "scam"],
    "camera": ["camera", "permission", "video call"],
    "mien phi": ["free"],
    "miễn phí": ["free"],
    "mã": ["verification code", "two-factor authentication"],
    "ma xac minh": ["verification code", "two-factor authentication"],
    "mật khẩu": ["password", "reset"],
    "mat khau": ["password", "reset"],
    "quên mật khẩu": ["forgot password", "reset password"],
    "quen mat khau": ["forgot password", "reset password"],
    "ngân hàng": ["bank", "account security"],
    "ngan hang": ["bank", "account security"],
    "trúng thưởng": ["prize scam", "lottery scam"],
    "trung thuong": ["prize scam", "lottery scam"],
    "báo cáo": ["report a scam", "Scamwatch"],
    "bao cao": ["report a scam", "Scamwatch"],
    "chặn": ["block number", "block calls"],
    "chan so": ["block number", "block calls"],
    "gọi video": ["video call", "how to"],
    "goi video": ["video call", "how to"],
    "thông dịch": ["interpreter", "TIS National", "translation service"],
    "thong dich": ["interpreter", "TIS National", "translation service"],
    "chữ nhỏ": ["increase text size", "accessibility"],
    "chu nho": ["increase text size", "accessibility"],
    "điện thoại chậm": ["phone running slow", "storage"],
    "dien thoai cham": ["phone running slow", "storage"],
    "wifi": ["wifi", "connect", "troubleshooting"],
    "học": ["digital literacy training", "Be Connected"],
    "hoc": ["digital literacy training", "Be Connected"],
    "medicare": ["Medicare claim", "app"],
    "mygov": ["myGov", "account", "sign in"],
    "centrelink": ["Centrelink", "phone service"],
}

_LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'\-\.]*")
_CITATION_RE = re.compile(r"\[\d{1,2}\]")

# Letters that never occur in a native Vietnamese syllable.
_NON_VI_LETTERS = set("fjwz")

# English function words. Deliberately short: these appear in English prose
# and never inside a Vietnamese sentence, so a hit is real evidence rather
# than a guess about vocabulary.
_EN_MARKERS = frozenset("""
    the a an and or but if then of to in on at for from with without by about
    is are was were be been being am do does did have has had you your this
    that these those what how why when where which who can could should would
    will not your please click here message account password code scam link
    """.split())


@dataclass(frozen=True)
class Violation:
    kind: str
    severity: str
    found: str
    expected: str
    note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _fold(text: str) -> str:
    text = (text or "").lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", text)
                   if unicodedata.category(c) != "Mn")


def glossary_block() -> str:
    lines = []
    for term, en, avoid in GLOSSARY:
        line = f"- {term} ({en})"
        if avoid:
            line += f" — không dùng: {', '.join(avoid)}"
        lines.append(line)
    return "\n".join(lines)


def register_block() -> str:
    lines = [
        f"- Gọi người đọc là «{REQUIRED_ADDRESS}».",
        f"- Gọi chúng ta là «{SELF_REFERENCE}».",
    ]
    for form, _sev, note in FORBIDDEN_ADDRESS:
        lines.append(f"- Tuyệt đối không dùng «{form}»: {note}")
    return "\n".join(lines)


def protected_nouns() -> list[str]:
    return list(PROTECTED_NOUNS)


def expand(query: str, limit: int = 8) -> list[str]:
    """Vietnamese query to English retrieval terms, with no model.

    Matching happens on the folded form, so `mat khau` and `mật khẩu` both
    hit -- which is the whole point, since seniors type without diacritics.

    Matching is on **whole syllables**, not substrings. Vietnamese is written
    one syllable per token and many keys are a single short syllable, so a
    substring match is badly wrong: folded `mã` is `ma`, which is inside
    `mat`, so "mat tien" (lost money) used to retrieve two-factor
    authentication pages. Word boundaries fix it; Chinese needs no equivalent
    because it has no whitespace to anchor to.
    """
    folded = _fold(query or "")
    hits: list[str] = []

    # Service names first, and verbatim -- see the note in zh/termbase.py.
    # These are the highest-value retrieval terms in the query and must reach
    # the RAG team unchanged.
    for noun in sorted(PROTECTED_NOUNS, key=len, reverse=True):
        if noun.lower() in (query or "").lower() and noun not in hits:
            hits.append(noun)

    for key in sorted(QUERY_EXPANSION, key=len, reverse=True):
        pattern = r"\b" + r"\s+".join(re.escape(p) for p in _fold(key).split()) + r"\b"
        if re.search(pattern, folded):
            for term in QUERY_EXPANSION[key]:
                if term not in hits:
                    hits.append(term)
    return hits[:limit]


@lru_cache(maxsize=1)
def _protected_re() -> re.Pattern:
    names = sorted(PROTECTED_NOUNS, key=len, reverse=True)
    return re.compile("|".join(re.escape(n) for n in names), re.IGNORECASE)


def audit(answer: str, *, source_text: str = "") -> list[Violation]:
    """Check a generated Vietnamese answer against the termbase."""
    text = _CITATION_RE.sub("", answer or "")
    folded = _fold(text)
    out: list[Violation] = []

    # Match the form of address on the ORIGINAL text, tone marks intact.
    #
    # Folding first looked tidy and was wrong: `mày` (rude "you") folds to
    # `may`, and so does `máy` as in `máy tính`, a computer. Every answer
    # that mentioned a computer was reported as insulting the reader. `cậu`
    # and `câu` (a sentence) collide the same way. Diacritics are the whole
    # difference between these words, so this is the one check that must not
    # discard them.
    #
    # Folded matching is kept only for text that carries no diacritics at
    # all -- a senior typing without tone marks -- where there is nothing
    # left to distinguish and a warning is better than silence.
    has_marks = folded != text.lower().replace("đ", "d")
    for form, severity, note in FORBIDDEN_ADDRESS:
        if has_marks:
            hit = re.search(rf"(?<![\wÀ-ỹ]){re.escape(form)}"
                            rf"(?![\wÀ-ỹ])", text, re.IGNORECASE)
        else:
            hit = re.search(rf"\b{re.escape(_fold(form))}\b", folded)
        if hit:
            out.append(Violation("address", severity, form,
                                 REQUIRED_ADDRESS, note))

    for term, en, avoid in GLOSSARY:
        for wrong in avoid:
            if _fold(wrong) in folded:
                out.append(Violation("term", "error", wrong, term,
                                     f"Locked term for {en}."))

    for formal, plain in PLAIN_LANGUAGE.items():
        if _fold(formal) in folded:
            out.append(Violation("formal", "warn", formal, plain,
                                 "Formal register; a plainer word exists."))

    # Untranslated English.
    #
    # This cannot work the way the Chinese lane's version does. In Chinese,
    # Latin letters are foreign by definition, so "any Latin run" is a sound
    # test. Vietnamese IS written in Latin script, so that same test flags
    # the entire answer -- `nghe`, `ngay` and `giao` were all reported as
    # English words a Vietnamese reader could not decode.
    #
    # Two signals that actually discriminate, and nothing else:
    #   1. f, j, w, z never occur in a native Vietnamese syllable.
    #   2. a short list of English function words that no Vietnamese
    #      sentence contains.
    # Both are conservative on purpose. A missed loanword is a small loss;
    # a false accusation on every second word makes the metric useless.
    protected = _protected_re()
    source_lower = (source_text or "").lower()
    seen: set[str] = set()
    for run in _LATIN_RUN_RE.findall(text):
        low = run.lower()
        if len(run) < 3 or low in seen or protected.fullmatch(run):
            continue
        looks_english = bool(_NON_VI_LETTERS & set(low)) or low in _EN_MARKERS
        if not looks_english:
            continue
        seen.add(low)
        severity = "warn" if low in source_lower else "error"
        out.append(Violation("untranslated", severity, run, "Vietnamese",
                             "English a Vietnamese-only reader cannot decode."))

    out.sort(key=lambda v: 0 if v.severity == "error" else 1)
    return out
