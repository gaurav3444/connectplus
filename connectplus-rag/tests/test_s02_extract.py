"""Tests for stage 02.

Two kinds, deliberately: tests against the REAL fixture data (this is what
README_rag.md's stage 02 DONE criterion — "five pages read by eye and
confirmed clean" — becomes as an automated, repeatable check instead of a
one-time manual look), and synthetic edge-case tests for failure paths
real data hasn't (yet) exercised, like malformed PDFs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from rag.s02_extract import (
    ExtractionInput,
    _extract_html,
    _strip_repeated_lines,
    extract_page,
    extract_pages,
    load_extraction_inputs_from_cache,
    load_extraction_inputs_from_fixture,
)
from rag.schemas import ExtractedDoc, PageRecord

FIXTURES_DIR = Path(__file__).parent.parent / "rag" / "fixtures"
NULL_LOG = logging.LoggerAdapter(logging.getLogger("test"), {"run_id": "test"})


# ---------------------------------------------------------------------------
# Real fixture: this is the automated stand-in for "read by eye"
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_docs():
    inputs = load_extraction_inputs_from_fixture(
        FIXTURES_DIR / "f01_pages.json", FIXTURES_DIR
    )
    docs, summary = extract_pages(inputs)
    return docs, summary


def test_all_six_real_fixture_pages_extract_successfully(real_docs) -> None:
    docs, summary = real_docs
    assert summary.total_input_pages == 6
    assert summary.extracted == 6
    assert summary.skipped_non_200_status == 0
    assert summary.skipped_unsupported_content_type == 0
    assert summary.skipped_empty_after_extraction == 0


def test_extracted_text_has_no_leftover_html_markup(real_docs) -> None:
    docs, _ = real_docs
    html_docs = [d for d in docs if d.source_content_type.startswith("text/html")]
    assert len(html_docs) == 5
    for doc in html_docs:
        assert "<div" not in doc.text
        assert "<script" not in doc.text
        assert "<nav" not in doc.text


def test_extracted_text_has_no_boilerplate_leakage(real_docs) -> None:
    docs, _ = real_docs
    boilerplate_phrases = ["accept all cookies", "skip to content", "subscribe to our newsletter"]
    for doc in docs:
        lowered = doc.text.lower()
        for phrase in boilerplate_phrases:
            assert phrase not in lowered, f"{phrase!r} leaked into {doc.url}"


def test_extracted_content_actually_matches_the_known_topic(real_docs) -> None:
    """Spot-checks specific to each real page — this is the part a human
    would do by eye; encoding it means it never has to be re-checked by
    hand again after this."""
    docs, _ = real_docs
    by_url = {str(d.url): d for d in docs}

    sms_doc = by_url["https://beconnected.esafety.gov.au/topic-library/identifying-and-avoiding-scams/text-or-sms-scams/what-is-a-text-or-sms-scam"]
    assert "sms" in sms_doc.text.lower() or "text message" in sms_doc.text.lower()

    mygov_doc = by_url["https://beconnected.esafety.gov.au/topic-library/introduction-to-mygov/all-about-mygov/what-is-mygov"]
    assert "mygov" in mygov_doc.text.lower()

    pdf_doc = by_url["https://scamwatch.gov.au/system/files/little-book-scams-2024-english.pdf"]
    assert "scam" in pdf_doc.text.lower()
    assert pdf_doc.title == "The Little Book of Scams"


def test_pdf_running_header_is_stripped_not_repeated_forty_times(real_docs) -> None:
    """The real PDF fixture repeats 'ACCC | How to spot and avoid scams' on
    every one of its ~40 pages. Without de-duplication this phrase would
    appear ~40 times in the extracted text — a real, confirmed behaviour,
    not a hypothetical, checked against the actual PDF before this test
    was written."""
    docs, _ = real_docs
    pdf_doc = next(d for d in docs if d.source_content_type == "application/pdf")
    occurrences = pdf_doc.text.lower().count("how to spot and avoid scams")
    assert occurrences <= 2, f"expected the repeated header to be stripped, found {occurrences} times"


def test_all_real_pages_detected_as_english(real_docs) -> None:
    docs, _ = real_docs
    for doc in docs:
        assert doc.lang == "en", f"{doc.url} detected as {doc.lang}, expected en"


def test_doc_ids_are_stable_and_unique(real_docs) -> None:
    docs, _ = real_docs
    ids = [d.doc_id for d in docs]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("doc-") for i in ids)


def test_content_xml_preserves_heading_structure_html_lacks(real_docs) -> None:
    """The entire reason this field exists: stage 03 needs heading_path,
    and plain `text` has no way to tell a heading apart from a body line.

    Not a universal guarantee, by design: one real page (Scamwatch's
    text-or-sms-scams, the same heavily Drupal-componentized page the list
    recovery fix targets) has 11 real <h*> tags in its raw HTML but
    trafilatura excludes all of them from main-content extraction — a
    different symptom of the same root cause. Recovering headings with
    correct position (unlike list recovery, which can just append at the
    end) is a materially harder problem, so it's deliberately not attempted
    here. Stage 03 must handle a doc with zero headings as a valid,
    expected case, not an error — this test documents that rather than
    asserting a guarantee real data doesn't support."""
    docs, _ = real_docs
    by_url = {str(d.url): d for d in docs}

    with_headings = [
        "https://beconnected.esafety.gov.au/topic-library/identifying-and-avoiding-scams/text-or-sms-scams/what-is-a-text-or-sms-scam",
        "https://beconnected.esafety.gov.au/topic-library/introduction-to-mygov/all-about-mygov/what-is-mygov",
        "https://beconnected.esafety.gov.au/topic-library/podcast/artificial-intelligence-explained",
        "https://scamwatch.gov.au/about-us/news-and-alerts/australian-taxation-office-ato-and-mygov-impersonation-scams",
    ]
    for url in with_headings:
        assert "<head" in by_url[url].content_xml, f"expected XML headings in {url}"

    known_headingless = "https://scamwatch.gov.au/types-of-scams/text-or-sms-scams"
    assert "<head" not in by_url[known_headingless].content_xml


def test_pdf_content_xml_is_empty_not_a_fake_copy_of_text(real_docs) -> None:
    """pypdf gives no heading-level info — content_xml is honestly empty
    for PDFs, not a lie that there's structure where there isn't."""
    docs, _ = real_docs
    pdf_doc = next(d for d in docs if d.source_content_type == "application/pdf")
    assert pdf_doc.content_xml == ""


# ---------------------------------------------------------------------------
# Synthetic edge cases
# ---------------------------------------------------------------------------

def _page(status=200, content_type="text/html", html="", url="https://example.test/page"):
    return PageRecord(url=url, domain="example.test", html=html, status=status, content_type=content_type)


def test_non_200_page_is_skipped_not_extracted() -> None:
    inp = ExtractionInput(record=_page(status=404))
    doc = extract_page(inp, NULL_LOG)
    assert doc is None


def test_unsupported_content_type_is_skipped() -> None:
    inp = ExtractionInput(record=_page(content_type="application/rss+xml", html="<rss>...</rss>"))
    doc = extract_page(inp, NULL_LOG)
    assert doc is None


def test_html_with_no_real_content_yields_no_doc() -> None:
    nav_only = "<html><body><nav><a href='/'>Home</a><a href='/about'>About</a></nav></body></html>"
    inp = ExtractionInput(record=_page(html=nav_only))
    doc = extract_page(inp, NULL_LOG)
    assert doc is None


def test_malformed_pdf_bytes_do_not_crash_extraction() -> None:
    """A PDF-labelled response that isn't a real PDF (truncated download,
    server error page served with the wrong content-type) must be skipped,
    not raise."""
    inp = ExtractionInput(
        record=_page(content_type="application/pdf"),
        raw_bytes=b"this is not a real pdf file at all",
    )
    doc = extract_page(inp, NULL_LOG)  # must not raise
    assert doc is None


def test_pdf_with_missing_raw_bytes_is_skipped_not_crashed() -> None:
    inp = ExtractionInput(record=_page(content_type="application/pdf"), raw_bytes=None)
    doc = extract_page(inp, NULL_LOG)
    assert doc is None


def test_strip_repeated_lines_removes_running_header() -> None:
    pages = [
        "1\nACME Corp Footer\nReal content for page one about scams.",
        "2\nACME Corp Footer\nDifferent real content for page two.",
        "3\nACME Corp Footer\nYet more unique content on page three.",
        "4\nACME Corp Footer\nAnd a fourth unique page of content.",
    ]
    cleaned = _strip_repeated_lines(pages)
    for page in cleaned:
        assert "ACME Corp Footer" not in page
    assert "Real content for page one about scams." in cleaned[0]
    assert "Different real content for page two." in cleaned[1]


def test_strip_repeated_lines_leaves_short_documents_alone() -> None:
    """With only 1-2 pages, "repeated" isn't a meaningful signal — must not
    strip content from a short real document just because a line happens
    to appear on both its pages."""
    pages = ["Same line\nUnique content A", "Same line\nUnique content B"]
    cleaned = _strip_repeated_lines(pages)
    assert cleaned == pages


def test_extract_pages_summary_counts_each_skip_reason_correctly() -> None:
    ok_html = (
        "<html><body><article><p>"
        + "Real scam-safety content. " * 30
        + "</p></article></body></html>"
    )
    empty_html = "<html><body><nav>x</nav></body></html>"
    inputs = [
        ExtractionInput(record=_page(url="https://example.test/ok", html=ok_html)),
        ExtractionInput(record=_page(url="https://example.test/notfound", status=404)),
        ExtractionInput(
            record=_page(url="https://example.test/feed", content_type="application/rss+xml")
        ),
        ExtractionInput(record=_page(url="https://example.test/empty", html=empty_html)),
    ]
    docs, summary = extract_pages(inputs)
    assert summary.total_input_pages == 4
    assert summary.extracted == 1
    assert summary.skipped_non_200_status == 1
    assert summary.skipped_unsupported_content_type == 1
    assert summary.skipped_empty_after_extraction == 1


def test_scorm_ui_chrome_text_is_filtered_as_not_real_content() -> None:
    """Regression test for a real finding: 4 real Be Connected SCORM
    mini-game pages all extracted to this exact 72-character string — UI
    chrome from the game player, not course content. It's longer than the
    original 50-char floor (which is why raising the threshold, not just
    adding a denylist entry, was the right fix)."""
    junk_html = (
        "<html><body><div>Please rotate your device\n"
        "This game is designed for use in Portrait Mode</div></body></html>"
    )
    inp = ExtractionInput(record=_page(html=junk_html))
    doc = extract_page(inp, NULL_LOG)
    assert doc is None


def test_short_but_real_content_survives_the_threshold() -> None:
    """The shortest genuinely real page in the full corpus was 145 chars —
    a category landing blurb. The threshold must not be raised so far that
    content like this gets wrongly filtered."""
    real_short_html = (
        "<html><body><article><p>Connecting to others. Need a helping hand "
        "with video calls, messaging apps, or staying in touch with family "
        "and friends online? Start here.</p></article></body></html>"
    )
    inp = ExtractionInput(record=_page(html=real_short_html))
    doc = extract_page(inp, NULL_LOG)
    assert doc is not None


def test_lang_detect_falls_back_to_unknown_on_empty_text() -> None:
    from rag.s02_extract import _detect_lang
    assert _detect_lang("") == "unknown"


# ---------------------------------------------------------------------------
# List recovery — built from a real, confirmed content-loss bug: trafilatura
# silently dropped an entire numbered "what to do if scammed" procedure on a
# real Scamwatch page because it's wrapped in a Drupal "callout" component.
# ---------------------------------------------------------------------------

def test_real_missing_procedure_is_recovered() -> None:
    """The actual real-world failure this fix exists for."""
    data = json.loads((FIXTURES_DIR / "f01_pages.json").read_text())
    page = next(p for p in data if "scamwatch.gov.au/types-of-scams/text-or-sms-scams" in p["url"])

    result = _extract_html(page["html"], page["url"])
    assert result is not None
    _, text, _ = result
    assert "act fast" in text.lower()
    assert "idcare" in text.lower()
    assert "report the scam" in text.lower()


def test_real_negative_control_pages_get_nothing_appended() -> None:
    """The other 4 real fixture HTML pages must NOT have anything appended —
    proves the fix is precise (fires on the one page with a real problem),
    not just broadly permissive (which would silently let nav/breadcrumb
    boilerplate back in everywhere)."""
    import trafilatura as traf

    data = json.loads((FIXTURES_DIR / "f01_pages.json").read_text())
    for page in data:
        if page["content_type"].startswith("application"):
            continue
        if "scamwatch.gov.au/types-of-scams/text-or-sms-scams" in page["url"]:
            continue  # the one real page that SHOULD get a recovery
        base = traf.extract(
            page["html"], url=page["url"], output_format="json",
            with_metadata=True, favor_precision=True,
        )
        base_text = json.loads(base)["text"] if base else ""
        result = _extract_html(page["html"], page["url"])
        assert result is not None
        _, full_text, _ = result
        assert full_text == base_text.strip(), f"unexpected content appended for {page['url']}"


def test_short_nav_like_list_is_not_recovered() -> None:
    from rag.s02_extract import _recover_missed_lists

    nav_html = (
        "<ul><li><a href='/'>Home</a></li><li><a href='/about'>About</a></li>"
        "<li><a href='/contact'>Contact</a></li></ul>"
    )
    recovered = _recover_missed_lists(nav_html, extracted_text="")
    assert recovered == []


def test_long_content_list_not_already_captured_is_recovered() -> None:
    from rag.s02_extract import _recover_missed_lists

    content_html = (
        "<ol><li>Contact your bank immediately to freeze the affected account.</li>"
        "<li>Change every password that might have been exposed in the breach.</li></ol>"
    )
    recovered = _recover_missed_lists(content_html, extracted_text="unrelated other text")
    assert len(recovered) == 1
    assert "freeze the affected account" in recovered[0]


def test_already_captured_list_is_not_duplicated() -> None:
    from rag.s02_extract import _recover_missed_lists

    content_html = (
        "<ol><li>Contact your bank immediately to freeze the affected account.</li>"
        "<li>Change every password that might have been exposed in the breach.</li></ol>"
    )
    already_have_it = (
        "Some intro text. Contact your bank immediately to freeze the affected account. More text."
    )
    recovered = _recover_missed_lists(content_html, extracted_text=already_have_it)
    assert recovered == []


def test_list_extractor_does_not_crash_on_malformed_html() -> None:
    from rag.s02_extract import _list_item_texts

    garbled = "<ol><li>ok item<![\x0c\x00garbage"
    result = _list_item_texts(garbled)  # must not raise
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Deduplication — built directly from a real finding: 125 of 477 real
# Scamwatch docs were byte-identical duplicates (same page fetched as both
# http:// and https://, discovered as separate sitemap entries).
# ---------------------------------------------------------------------------

def _doc(url, text, doc_id=None):
    from rag.s02_extract import _doc_id
    return ExtractedDoc(
        doc_id=doc_id or _doc_id(url), url=url, domain="scamwatch.gov.au", title="t",
        lang="en", fetched_at="2026-01-01T00:00:00+00:00", text=text,
        source_content_type="text/html",
    )


def test_dedup_removes_http_https_duplicate_keeping_https() -> None:
    from rag.s02_extract import deduplicate_docs

    same_text = "Identical scam-safety content, fetched under two schemes."
    docs = [
        _doc("http://scamwatch.gov.au/example", same_text),
        _doc("https://scamwatch.gov.au/example", same_text),
    ]
    kept, removed = deduplicate_docs(docs, NULL_LOG)
    assert removed == 1
    assert len(kept) == 1
    assert str(kept[0].url).startswith("https://")


def test_dedup_leaves_genuinely_different_docs_alone() -> None:
    from rag.s02_extract import deduplicate_docs

    docs = [
        _doc("https://scamwatch.gov.au/a", "Content about text message scams."),
        _doc("https://scamwatch.gov.au/b", "Content about phone call scams."),
    ]
    kept, removed = deduplicate_docs(docs, NULL_LOG)
    assert removed == 0
    assert len(kept) == 2


def test_dedup_is_deterministic_across_runs() -> None:
    """Same input, run twice (e.g. two people extracting independently),
    must keep the same survivor both times — not "whichever happened to
    come first in the list", which would depend on manifest ordering."""
    from rag.s02_extract import deduplicate_docs

    same_text = "Duplicate content for determinism check."
    docs_order_a = [
        _doc("http://scamwatch.gov.au/x", same_text),
        _doc("https://scamwatch.gov.au/x", same_text),
    ]
    docs_order_b = list(reversed(docs_order_a))

    kept_a, _ = deduplicate_docs(docs_order_a, NULL_LOG)
    kept_b, _ = deduplicate_docs(docs_order_b, NULL_LOG)
    assert str(kept_a[0].url) == str(kept_b[0].url)


def test_real_fixture_docs_are_never_wrongly_deduplicated() -> None:
    """Regression guard: the 6 real fixture docs are all genuinely distinct
    pages. Dedup must never merge real, different content just because
    lengths or topics are similar."""
    inputs = load_extraction_inputs_from_fixture(FIXTURES_DIR / "f01_pages.json", FIXTURES_DIR)
    docs, summary = extract_pages(inputs)
    assert summary.deduplicated_exact_text_matches == 0
    assert len(docs) == 6


def test_extract_pages_reports_dedup_count_in_summary() -> None:
    same_html = (
        "<html><body><article><p>" + "Scam safety content. " * 30 + "</p></article></body></html>"
    )
    different_html = same_html.replace("Scam safety", "Totally different")
    inputs = [
        ExtractionInput(record=_page(url="http://example.test/dup", html=same_html)),
        ExtractionInput(record=_page(url="https://example.test/dup", html=same_html)),
        ExtractionInput(record=_page(url="https://example.test/unique", html=different_html)),
    ]
    docs, summary = extract_pages(inputs)
    assert summary.extracted == 2  # one pair collapsed to one, plus the unique one
    assert summary.deduplicated_exact_text_matches == 1


# ---------------------------------------------------------------------------
# End-to-end: stage 01's real cache output -> stage 02, via the same
# adapters the CLI's `extract` command actually uses. Everything above
# tests extraction logic in isolation or against the fixture; this is the
# only test that proves the production code path (ingest_domain ->
# load_pages_from_manifest -> load_extraction_inputs_from_cache ->
# extract_pages) actually connects end to end, including a real PDF
# round-tripping through the .bin cache stage 01 writes it to.
# ---------------------------------------------------------------------------

def test_stage01_to_stage02_end_to_end_including_a_pdf(tmp_path: Path) -> None:
    import httpx

    from rag.s01_ingest import ApprovedDomain, ingest_domain, load_pages_from_manifest

    approved = [ApprovedDomain(domain="example-approved.test", added_by="t", approved_at="2026-01-01")]
    real_pdf_bytes = (FIXTURES_DIR / "sample_little_book_of_scams.pdf").read_bytes()
    sitemap = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example-approved.test/scam-info</loc></url>
      <url><loc>https://example-approved.test/booklet.pdf</loc></url>
    </urlset>"""
    real_html = (
        "<html><body><article><h1>Scam info</h1><p>"
        + "This page explains how to recognise scams. " * 20
        + "</p></article></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example-approved.test/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        if url == "https://example-approved.test/sitemap.xml":
            return httpx.Response(200, text=sitemap)
        if url == "https://example-approved.test/scam-info":
            return httpx.Response(200, text=real_html, headers={"content-type": "text/html"})
        if url == "https://example-approved.test/booklet.pdf":
            return httpx.Response(200, content=real_pdf_bytes, headers={"content-type": "application/pdf"})
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    ingest_domain("example-approved.test", approved, tmp_path, client=client)

    # From here on, nothing touches the network or the ingest internals —
    # this is exactly what `python -m rag.main extract --domain ...` does.
    pages = load_pages_from_manifest("example-approved.test", tmp_path)
    inputs = load_extraction_inputs_from_cache(pages, tmp_path)
    docs, summary = extract_pages(inputs)

    assert summary.extracted == 2
    by_url = {str(d.url): d for d in docs}
    assert "recognise scams" in by_url["https://example-approved.test/scam-info"].text.lower()
    assert "scam" in by_url["https://example-approved.test/booklet.pdf"].text.lower()
    assert by_url["https://example-approved.test/booklet.pdf"].source_content_type == "application/pdf"
