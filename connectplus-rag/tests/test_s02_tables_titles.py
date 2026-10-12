"""Tests for stage 02's post-trafilatura clean-up:
- single-column-table unwrapping and missing-title fallback (HTML mirrors a
  real eSafety /media video page; runs the real trafilatura, not a mock);
- within-document clean-up: repeated passages, UI boilerplate and oversized
  paragraphs (shapes mirror the real Be Connected and myGov pages the rules
  were measured on)."""

from __future__ import annotations

import logging
from xml.etree import ElementTree

from pydantic import HttpUrl

from rag.s02_extract import (
    MAX_PARAGRAPH_CHARS,
    ExtractionInput,
    _clean_document_text,
    _clean_document_xml,
    _unwrap_single_column_tables_text,
    _unwrap_single_column_tables_xml,
    extract_page,
)
from rag.schemas import PageRecord

LOG = logging.LoggerAdapter(logging.getLogger("test"), {"run_id": "t"})

TRANSCRIPT = [
    "From online shopping and banking to staying in contact with friends and family, "
    "your computer has become central to modern-day life.",
    "It is therefore important that your Mac is thoroughly secured against prying eyes.",
    "Open System Preferences, then Users and Groups, then select Change Password.",
]


def _page(title: str, body: str) -> str:
    return f"""<html><head><title>{title}</title><meta property="og:title" content="{title}"></head>
<body><nav><ul><li><a href="/">Home</a></li></ul></nav>
<main><article>{body}</article></main><footer>Copyright</footer></body></html>"""


def _extract(html: str):  # type: ignore[no-untyped-def]
    record = PageRecord(url=HttpUrl("https://www.esafety.gov.au/media/changing-passwords-on-macs"),
                        domain="esafety.gov.au", html=html, status=200, content_type="text/html")
    doc = extract_page(ExtractionInput(record=record), LOG)
    assert doc is not None
    return doc


MEDIA_BODY = "<h1>Changing passwords on Macs</h1><table><thead><tr><th>Audio</th></tr></thead>" \
             "<tbody><tr><td>" + "".join(f"<p>{p}</p>" for p in TRANSCRIPT) + "</td></tr></tbody></table>"


def test_esafety_media_page_gets_a_real_title_with_site_suffix() -> None:
    doc = _extract(_page(" | eSafety Commissioner", MEDIA_BODY))
    assert doc.title == "Changing passwords on Macs | eSafety Commissioner"


def test_transcript_table_is_unwrapped_in_xml_and_text() -> None:
    doc = _extract(_page(" | eSafety Commissioner", MEDIA_BODY))
    assert "<table" not in doc.content_xml
    assert doc.content_xml.count("<p>") == len(TRANSCRIPT)           # paragraphs preserved
    assert "Audio" not in doc.content_xml                             # header label dropped
    assert "|" not in doc.text and "Audio" not in doc.text
    assert TRANSCRIPT[2] in doc.text


def test_good_titles_are_left_alone() -> None:
    doc = _extract(_page("Online scams | eSafety Commissioner", MEDIA_BODY))
    assert doc.title == "Online scams | eSafety Commissioner"


def test_multi_column_tables_are_left_exactly_as_they_are() -> None:
    xml = """<doc><main><head rend="h1">Script</head><table>
<row><cell role="head">Visual</cell><cell role="head">Audio</cell></row>
<row><cell>Laila films Ryan.</cell><cell>Ryan: Check this!</cell></row>
</table></main></doc>"""
    assert _unwrap_single_column_tables_xml(xml) == (xml, 0)
    text = "| Visual | Audio |\n|---|---|\n| Laila films Ryan. | Ryan: Check this! |"
    assert _unwrap_single_column_tables_text(text) == text


def test_long_header_cell_is_content_not_a_label_and_is_kept() -> None:
    long_header = "Transcript of the eSafety video about protecting your accounts online"
    xml = f"""<doc><main><table><row><cell role="head">{long_header}</cell></row>
<row><cell><p>First line.</p></cell></row></table></main></doc>"""
    out, n = _unwrap_single_column_tables_xml(xml)
    assert n == 1 and long_header in out and "First line." in out
    text = f"| {long_header} |\n|---|\n| First line. |"
    assert _unwrap_single_column_tables_text(text) == f"{long_header}\nFirst line."


def test_text_around_the_table_is_untouched() -> None:
    text = "Intro paragraph.\n| Audio |\n|---|\n| Spoken words here. |\nClosing paragraph."
    expected = "Intro paragraph.\nSpoken words here.\nClosing paragraph."
    assert _unwrap_single_column_tables_text(text) == expected


def test_unparseable_xml_is_returned_untouched() -> None:
    broken = "<doc><main><table><row><cell>oops</main>"
    assert _unwrap_single_column_tables_xml(broken) == (broken, 0)


# --------------------------------------------------------------------------- within-document clean-up

SENTENCE = "Julie types her email address into the box and selects Next to continue. "
LONG_TRANSCRIPT = SENTENCE * 20                                   # ~1,500 chars, like a real transcript


def _doc(*blocks: str) -> str:
    return "<doc><main>" + "".join(blocks) + "</main></doc>"


def _paragraphs(xml: str) -> list[str]:
    return [" ".join("".join(p.itertext()).split()) for p in ElementTree.fromstring(xml).iter("p")]


def _wrap(text: str, width: int = 90) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    return lines + [line]


def test_line_wrapped_second_copy_of_a_transcript_is_removed() -> None:
    """Be Connected: clean transcript first, the same transcript line-wrapped
    under 'Topic outline > General' later. Keep the first copy only."""
    copy = "".join(f"<p>{ln}</p>" for ln in _wrap(LONG_TRANSCRIPT))
    heading = '<head rend="h2">General</head>'
    xml, counts = _clean_document_xml(_doc(f"<p>{LONG_TRANSCRIPT}</p>", heading, copy))
    joined = " ".join(_paragraphs(xml))
    assert joined.count("Julie types her email address") == 20     # once per sentence, not twice
    assert counts["repeated"] >= len(_wrap(LONG_TRANSCRIPT)) - 1


def test_repeated_procedure_steps_are_kept() -> None:
    """my.gov.au: the same steps legitimately appear in two procedures."""
    steps = ["Select Get started in the Digital ID (Recommended) box and follow the prompts.",
             "Select Yes to Do you have or know your Medicare card and Individual Reference Number?",
             "Enter your details and select Next."]
    section = "".join(f"<p>{s}</p>" for s in steps)
    xml, counts = _clean_document_xml(_doc('<head rend="h2">Link Medicare</head>', section,
                                           '<head rend="h2">Link Centrelink</head>', section))
    assert counts["repeated"] == 0
    assert _paragraphs(xml).count(steps[0]) == 2


def test_be_connected_ui_boilerplate_is_removed() -> None:
    xml, counts = _clean_document_xml(_doc(
        "<p>Join or sign in Sign in to save your progress and earn a certificate Join / Sign in</p>",
        "<p>In this course you will learn how to make a video call.</p>",
        "<list><item>1 Getting ready to use WhatsApp 5 min Start now</item>"
        "<item>2 Adding contacts in WhatsApp 5 min Start now</item></list>",
    ))
    assert counts["boilerplate"] == 3
    assert _paragraphs(xml) == ["In this course you will learn how to make a video call."]
    assert "<list" not in xml                                    # emptied list removed too


def test_oversized_paragraph_is_split_at_sentence_ends() -> None:
    xml, counts = _clean_document_xml(_doc(f"<p>{LONG_TRANSCRIPT}</p>"))
    paras = _paragraphs(xml)
    assert counts["split"] == 1 and len(paras) > 1
    assert all(len(p) <= MAX_PARAGRAPH_CHARS for p in paras)
    assert all(p.endswith(".") for p in paras)                   # never cut mid-sentence
    assert " ".join(paras) == " ".join(LONG_TRANSCRIPT.split())       # nothing lost


def test_clean_pages_are_returned_byte_for_byte() -> None:
    xml = _doc("<p>One short paragraph.</p>", "<p>Another, different paragraph.</p>")
    assert _clean_document_xml(xml) == (xml, {"boilerplate": 0, "repeated": 0, "split": 0})


def test_text_twin_applies_the_same_rules() -> None:
    lines = _wrap(LONG_TRANSCRIPT)
    signin = "Join or sign in Sign in to save your progress and earn a certificate"
    text = "\n".join([LONG_TRANSCRIPT.strip(), signin, *lines, "Select Next.", "Select Next."])
    out = _clean_document_text(text)
    assert out.count("Julie types her email address") == 20
    assert "Sign in to save your progress" not in out
    assert out.endswith("Select Next.\nSelect Next.")            # short repeats survive


def test_labelled_second_copy_is_removed() -> None:
    """Be Connected WhatsApp page: second copy is ONE block with a
    'Transcript: <title>' label in front, so it isn't a plain substring."""
    xml, counts = _clean_document_xml(_doc(
        f"<p>{LONG_TRANSCRIPT}</p>", '<head rend="h2">General</head>',
        f"<p>Transcript: How to make a video call with WhatsApp {LONG_TRANSCRIPT}</p>"))
    assert counts["repeated"] == 1
    assert " ".join(_paragraphs(xml)).count("Julie types her email address") == 20


def test_oversized_paragraph_with_inline_markup_is_split() -> None:
    para = f"<p>Welcome to the <hi rend='#i'>Setting up</hi> course. {LONG_TRANSCRIPT}</p>"
    xml, counts = _clean_document_xml(_doc(para))
    assert counts["split"] == 1 and all(len(p) <= MAX_PARAGRAPH_CHARS for p in _paragraphs(xml))


def test_list_holding_a_whole_transcript_becomes_paragraphs() -> None:
    """Stage 03 keeps <list> whole; a transcript inside one <item> made
    500-2,642-token chunks on real Be Connected pages."""
    xml, counts = _clean_document_xml(_doc(f"<list><item>{LONG_TRANSCRIPT}</item></list>"))
    assert "<list" not in xml and "<item" not in xml
    assert counts["split"] == 1 and all(len(p) <= MAX_PARAGRAPH_CHARS for p in _paragraphs(xml))


def test_short_procedure_lists_stay_lists() -> None:
    xml = _doc("<list><item>Open Settings.</item><item>Select Notifications.</item></list>")
    assert _clean_document_xml(xml)[0] == xml


def test_sign_in_boilerplate_without_certificate_wording_is_removed() -> None:
    signin = "<p>Join or sign in Sign in to save your progress Join / Sign in</p>"
    xml, counts = _clean_document_xml(_doc(signin, "<p>Real course content about Bluetooth.</p>"))
    assert counts["boilerplate"] == 1


def test_transcript_paragraph_inside_a_list_item_flattens_the_list() -> None:
    """The real Be Connected shape: <list><item><p>whole transcript</p></item></list>.
    Splitting the <p> alone would leave the pieces inside the list, which
    stage 03 keeps whole, so the list itself must become paragraphs."""
    xml, counts = _clean_document_xml(_doc(
        f"<list><item><p>Video: Setting up</p><p>{LONG_TRANSCRIPT}</p></item></list>"))
    paras = _paragraphs(xml)
    assert "<list" not in xml and "<item" not in xml
    assert paras[0] == "Video: Setting up"                          # paragraph breaks kept
    assert all(len(p) <= MAX_PARAGRAPH_CHARS for p in paras)
    assert counts["split"] == 1


def test_list_containing_headings_is_left_for_stage_03() -> None:
    """Regression guard: stage 03 unwraps lists that contain headings itself
    (real Be Connected podcast page, test_s03_chunk.py). Stage 02 must keep
    that list AND its headings, and only split the over-long paragraph."""
    xml, counts = _clean_document_xml(_doc(
        f'<list><item><head rend="h2">Transcript</head><p>{LONG_TRANSCRIPT}</p></item></list>'))
    root = ElementTree.fromstring(xml)
    assert root.find(".//list") is not None                       # list kept
    assert [h.text for h in root.iter("head")] == ["Transcript"]  # heading kept
    assert counts["split"] == 1
    assert all(len(p) <= MAX_PARAGRAPH_CHARS for p in _paragraphs(xml))


def test_list_item_holding_many_normal_paragraphs_is_flattened() -> None:
    """Real shape on 84 Be Connected pages ("iPad: Listening to podcasts"):
    one <item> with many ordinary-sized <p>. No block is long, but stage 03
    kept the whole list as one 2,508-token chunk."""
    paras = [f"Step {i}: {SENTENCE * 2}" for i in range(20)]          # each ~150 chars, ~3,000 total
    paras.append("Remember, you can always change this in your iPad's Settings app later on.")
    item = "".join(f"<p>{p}</p>" for p in paras)
    xml, counts = _clean_document_xml(_doc(f'<list rend="ul"><item>{item}</item></list>'))
    assert "<list" not in xml
    assert _paragraphs(xml) == [" ".join(p.split()) for p in paras]   # every paragraph kept, in order
    assert counts["split"] == 1


def test_bullet_lists_with_one_line_per_item_are_never_flattened() -> None:
    """eSafety's long checklists: many single-line items. Stage 03's
    keep-lists-whole behaviour must still apply to them."""
    items = "".join(f"<item>Check your setting number {i} and turn off sharing you don't need.</item>"
                    for i in range(40))
    xml = _doc(f'<list rend="ul">{items}</list>')
    assert _clean_document_xml(xml)[0] == xml


def test_short_multi_paragraph_item_is_left_alone() -> None:
    xml = _doc("<list><item><p>First short paragraph.</p><p>Second short paragraph.</p></item></list>")
    assert _clean_document_xml(xml)[0] == xml
