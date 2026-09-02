"""The Vietnamese readability proxy."""

from llm.vi.readability import score

PLAIN = """Thưa ông/bà, đây là tin nhắn lừa đảo.
1. Xin ông/bà đừng bấm vào đường liên kết.
2. Xin ông/bà xóa tin nhắn này.
3. Nếu ông/bà đã bấm vào, xin đổi mật khẩu ngay."""

BUREAUCRATIC = (
    "Trong trường hợp quý khách tiến hành truy cập vào hệ thống và thực hiện "
    "việc cung cấp thông tin cá nhân cho các đối tượng lừa đảo thông qua đường "
    "liên kết được đính kèm trong tin nhắn, quý khách cần khẩn trương tiến "
    "hành thực hiện việc thay đổi mật khẩu đồng thời liên hệ với ngân hàng để "
    "được hỗ trợ xử lý theo quy định hiện hành."
)


def test_plain_language_beats_officialese_by_a_wide_margin():
    """The discrimination Flesch-Kincaid cannot make. Both passages say
    roughly the same thing; one is readable by the intended reader."""
    assert score(PLAIN).score - score(BUREAUCRATIC).score > 40


def test_grades():
    assert score(PLAIN).grade == "easy"
    assert score(BUREAUCRATIC).grade == "hard"


def test_untranslated_english_is_penalised():
    """An answer that leaves the instructions in English has failed the reader
    even if every sentence is short."""
    mixed = ("Ông hãy mở settings rồi chọn security và bấm verify "
             "identity ngay.")
    r = score(mixed)
    assert r.loanword_rate > 0.1
    assert "settings" in r.offenders["loanwords"]


def test_approved_proper_nouns_are_not_counted_as_loanwords():
    """myGov and Medicare must stay in English; penalising them would push the
    prompt towards translating them, which breaks the instruction."""
    r = score("Xin ông/bà mở myGov và chọn Medicare.")
    assert r.loanword_rate == 0.0


def test_long_sentences_are_caught_even_with_a_good_average():
    text = "Ông mở máy. Ông bấm nút. " + " ".join(["từ"] * 40) + "."
    assert score(text).long_sentence_rate > 0


def test_empty_answer_scores_zero_rather_than_raising():
    r = score("")
    assert r.score == 0.0 and r.grade == "hard"


def test_mostly_english_answer_cannot_score_as_easy():
    """Regression. An answer that left its content in English scored 'easy'
    because its sentences were short. Readability presumes the reader can read
    the words at all, so heavy untranslated English caps the score."""
    mixed = ("Thưa ông/bà: Scammers send text messages that look like they "
             "come from a bank. You can report a scam to Scamwatch online.")
    r = score(mixed)
    assert r.grade == "hard"
    assert r.offenders["capped_for_untranslated_english"]
