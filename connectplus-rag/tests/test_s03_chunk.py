"""Tests for stage 03.

Uses a lightweight stand-in token counter throughout — not BGE-m3's real
tokenizer. This sandbox's network can't reach huggingface.co to download
it, so the counter here (word count) is purely for exercising the
chunking *logic* (boundaries, merging, list atomicity) deterministically.
Production code calls get_default_token_counter(), which uses the real
tokenizer and is not itself under test here.
"""

from __future__ import annotations

from pathlib import Path

from rag.s02_extract import extract_pages, load_extraction_inputs_from_fixture
from rag.s03_chunk import (
    MAX_CHUNK_TOKENS,
    _parse_blocks,
    chunk_doc,
    chunk_docs,
)
from rag.schemas import ExtractedDoc

FIXTURES_DIR = Path(__file__).parent.parent / "rag" / "fixtures"


def word_count(text: str) -> int:
    """Stand-in token counter for tests — see module docstring."""
    return max(1, len(text.split()))


def _doc(content_xml: str = "", text: str = "placeholder text long enough to pass extraction" * 3,
         doc_id: str = "doc-test") -> ExtractedDoc:
    return ExtractedDoc(
        doc_id=doc_id, url="https://example.test/page", domain="example.test",
        title="Test Doc", lang="en", fetched_at="2026-01-01T00:00:00+00:00",
        text=text, content_xml=content_xml, source_content_type="text/html",
    )


# ---------------------------------------------------------------------------
# Real fixture regression tests
# ---------------------------------------------------------------------------

def _real_docs():
    inputs = load_extraction_inputs_from_fixture(FIXTURES_DIR / "f01_pages.json", FIXTURES_DIR)
    docs, _ = extract_pages(inputs)
    return docs


def test_real_recovered_procedure_stays_in_one_chunk() -> None:
    """The exact real-world case this stage's numbered-list-safety
    requirement exists for: the recovered "what to do if scammed"
    procedure (Act fast / Get help / Report the scam) must appear whole in
    a single chunk's text, never split across two."""
    docs = _real_docs()
    doc = next(d for d in docs if "scamwatch.gov.au/types-of-scams/text-or-sms-scams" in str(d.url))
    chunks = chunk_doc(doc, count_tokens=word_count)

    matches = [c for c in chunks if "act fast" in c.text.lower() and "report the scam" in c.text.lower()]
    assert len(matches) == 1, "the recovered procedure must land whole in exactly one chunk"


def test_real_docs_all_chunk_without_crashing() -> None:
    """Every real doc — HTML with headings, HTML without any, and a PDF —
    must chunk successfully. This is the practical equivalent of running
    the real corpus through and checking nothing blows up."""
    docs = _real_docs()
    for doc in docs:
        chunks = chunk_doc(doc, count_tokens=word_count)
        assert len(chunks) > 0, f"expected at least one chunk from {doc.url}"


def test_real_html_doc_produces_heading_paths() -> None:
    docs = _real_docs()
    doc = next(d for d in docs if "what-is-a-text-or-sms-scam" in str(d.url))
    chunks = chunk_doc(doc, count_tokens=word_count)
    assert any(c.heading_path for c in chunks)


def test_real_headingless_page_still_chunks_with_empty_heading_path() -> None:
    """The one real page confirmed to have zero recoverable headings —
    must produce valid chunks with heading_path == [], not an error."""
    docs = _real_docs()
    doc = next(d for d in docs if str(d.url) == "https://scamwatch.gov.au/types-of-scams/text-or-sms-scams")
    chunks = chunk_doc(doc, count_tokens=word_count)
    assert len(chunks) >= 1
    assert all(c.heading_path == [doc.title] for c in chunks)  # page-title fallback


def test_real_pdf_chunks_with_empty_heading_path() -> None:
    docs = _real_docs()
    pdf_doc = next(d for d in docs if d.source_content_type == "application/pdf")
    chunks = chunk_doc(pdf_doc, count_tokens=word_count)
    assert len(chunks) >= 1
    assert all(c.heading_path == [pdf_doc.title] for c in chunks)  # page-title fallback
    assert all(c.url == pdf_doc.url for c in chunks)


def test_real_pdf_now_actually_splits_into_multiple_chunks() -> None:
    """Regression test for a real, confirmed bug: the whole ~4000-word PDF
    used to become a single unsplit chunk (one giant block with nothing to
    pack/split between). Must now produce multiple properly-sized chunks."""
    docs = _real_docs()
    pdf_doc = next(d for d in docs if d.source_content_type == "application/pdf")
    chunks = chunk_doc(pdf_doc, count_tokens=word_count)
    assert len(chunks) > 1, "a ~4000-word PDF must not become one giant chunk"
    for c in chunks:
        assert c.token_count <= MAX_CHUNK_TOKENS + 50  # small slack for overlap/paragraph granularity


def test_every_real_chunk_has_a_resolving_url_matching_its_doc() -> None:
    """README's stage 03 DONE criterion: every chunk has a resolving URL."""
    docs = _real_docs()
    all_chunks = chunk_docs(docs, count_tokens=word_count)
    assert len(all_chunks) > 0
    by_doc = {d.doc_id: d for d in docs}
    for chunk in all_chunks:
        assert str(chunk.url) == str(by_doc[chunk.doc_id].url)


def test_nested_elements_inside_a_list_are_not_double_counted() -> None:
    """Regression test for a real, confirmed bug found on the AI-explained
    fixture page: lists containing nested <p>/<head> elements were being
    counted twice — once via the list's own text aggregation, once again
    as a standalone paragraph/heading during the same tree walk."""
    docs = _real_docs()
    doc = next(d for d in docs if "artificial-intelligence-explained" in str(d.url))
    chunks = chunk_doc(doc, count_tokens=word_count)
    full_text = " ".join(c.text for c in chunks)
    # The known duplicated fragment from the real bug: "General" appearing
    # via both the list item and the nested heading. After the fix this
    # should appear as plain deduped content, not doubled up absurdly.
    assert full_text.lower().count("general general") <= 1


def test_native_list_with_nested_headings_is_unwrapped_not_atomic() -> None:
    """Regression test for a real, confirmed bug: trafilatura natively
    captured an entire podcast transcript — headings and all — inside a
    single <ul><li>, because the source HTML used an accordion/"read
    transcript" toggle widget, not because it's a numbered procedure.
    Treating it as atomic produced a single 2,630-token, heading-less
    chunk. Unwrapped, it must split into properly-sized, correctly
    heading-attributed chunks instead."""
    docs = _real_docs()
    doc = next(d for d in docs if "artificial-intelligence-explained" in str(d.url))
    chunks = chunk_doc(doc, count_tokens=word_count)

    assert len(chunks) > 1, "the transcript must be split, not kept as one atomic blob"
    for c in chunks:
        assert c.token_count <= MAX_CHUNK_TOKENS + 50
    # The whole point of unwrapping: real heading attribution instead of [].
    transcript_chunks = [c for c in chunks if "transcript" in [h.lower() for h in c.heading_path]]
    assert len(transcript_chunks) > 0


def test_flat_text_list_is_still_atomic_after_the_unwrap_fix() -> None:
    """Guards against overcorrecting: a genuine short procedure (flat text
    items, no nested headings) must remain atomic. This is the exact real
    case the numbered-list-safety requirement exists for."""
    docs = _real_docs()
    doc = next(d for d in docs if "scamwatch.gov.au/types-of-scams/text-or-sms-scams" in str(d.url))
    chunks = chunk_doc(doc, count_tokens=word_count)
    matches = [c for c in chunks if "act fast" in c.text.lower() and "report the scam" in c.text.lower()]
    assert len(matches) == 1


def test_synthetic_list_with_nested_heading_unwraps_into_separate_blocks() -> None:
    xml = """<doc><main>
      <list rend="ul"><item>
        <head rend="h2">Episode notes</head>
        <p>This is real prose content wrapped in a list purely for accordion styling.</p>
        <head rend="h2">Credits</head>
        <p>More real prose content here, under a different nested heading.</p>
      </item></list>
    </main></doc>"""
    blocks = _parse_blocks(xml)
    assert all(not b.is_list for b in blocks), "a list with nested headings must not stay atomic"
    paths = {b.heading_path for b in blocks}
    assert ("Episode notes",) in paths
    assert ("Credits",) in paths


def test_synthetic_flat_list_remains_atomic() -> None:
    xml = """<doc><main>
      <list rend="ol">
        <item>Step one: do this.</item>
        <item>Step two: do that.</item>
      </list>
    </main></doc>"""
    blocks = _parse_blocks(xml)
    assert len(blocks) == 1
    assert blocks[0].is_list is True


# ---------------------------------------------------------------------------
# Synthetic structural tests
# ---------------------------------------------------------------------------

def test_heading_hierarchy_builds_correct_heading_path() -> None:
    xml = """<doc><main>
      <head rend="h1">Staying safe</head>
      <head rend="h2">Recognising scam texts</head>
      <p>Some real content about recognising scam texts, long enough to count.</p>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)
    assert chunks[0].heading_path == ["Staying safe", "Recognising scam texts"]


def test_sibling_heading_replaces_previous_at_same_level() -> None:
    xml = """<doc><main>
      <head rend="h1">Topic</head>
      <head rend="h2">Section A</head>
      <p>Content for section A, long enough to be real content here.</p>
      <head rend="h2">Section B</head>
      <p>Content for section B, also long enough to be real content here.</p>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)
    paths = {tuple(c.heading_path) for c in chunks}
    assert ("Topic", "Section A") in paths or ("Topic",) in paths
    # Section A must not still be active by the time Section B's content appears
    b_chunk = next(c for c in chunks if "section b" in c.text.lower())
    assert "Section A" not in b_chunk.heading_path


def test_list_is_never_split_even_when_it_would_exceed_budget() -> None:
    """The core DONE criterion, forced deliberately: a list big enough
    that splitting mid-list would otherwise be tempting under a tight
    token budget must still come out whole in one chunk."""
    long_items = "\n".join(
        f"<item>Step {i}: do something specific and detailed here.</item>" for i in range(40)
    )
    xml = f"""<doc><main>
      <head rend="h1">Procedure</head>
      <list rend="ol">{long_items}</list>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)

    list_chunks = [c for c in chunks if "Step 0:" in c.text]
    assert len(list_chunks) == 1
    for i in range(40):
        assert f"Step {i}:" in list_chunks[0].text, f"Step {i} missing or split out of the list's chunk"


def test_small_sibling_sections_merge_using_common_ancestor() -> None:
    xml = """<doc><main>
      <head rend="h1">Getting started</head>
      <head rend="h2">Intro</head>
      <p>Short.</p>
      <head rend="h2">More</head>
      <p>Also short.</p>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)
    # Both tiny sections share "Getting started" as a common ancestor —
    # should merge into fewer chunks than sections, using that shared path.
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Getting started"]


def test_oversized_section_splits_with_consistent_heading_path() -> None:
    paragraphs = "\n".join(f"<p>{'word ' * 30} paragraph number {i}.</p>" for i in range(20))
    xml = f"""<doc><main>
      <head rend="h1">Big section</head>
      {paragraphs}
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)
    assert len(chunks) > 1
    assert all(c.heading_path == ["Big section"] for c in chunks)
    assert all(c.token_count <= MAX_CHUNK_TOKENS + 20 for c in chunks)  # small slack for overlap


def test_single_oversized_paragraph_gets_sentence_split() -> None:
    """Regression test for a real, confirmed bug: 160 real Be Connected
    chunks (across 149 distinct pages) were stuck at 500-2,446 tokens
    because a single oversized <p> — a whole video transcript trafilatura
    merged into one paragraph element — had no mechanism to split it
    internally. Unlike a list, a paragraph has no correctness reason to
    stay whole."""
    long_sentence_run = (
        ". ".join(f"This is sentence number {i} of a long transcript" for i in range(150)) + "."
    )
    xml = f"""<doc><main>
      <head rend="h1">Topic outline</head>
      <head rend="h2">General</head>
      <p>{long_sentence_run}</p>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)

    assert len(chunks) > 1, "a single oversized paragraph must be split, not kept as one blob"
    for c in chunks:
        assert c.token_count <= MAX_CHUNK_TOKENS + 20
        assert c.heading_path == ["Topic outline", "General"]


def test_oversized_list_is_still_not_split_after_the_paragraph_fix() -> None:
    """Guards against overcorrecting: adding paragraph-splitting must not
    weaken the hard list-atomicity guarantee. This is the exact case the
    numbered-list-safety requirement exists for."""
    long_items = "\n".join(
        f"<item>Step {i}: do something specific and detailed here.</item>" for i in range(60)
    )
    xml = f"""<doc><main>
      <head rend="h1">Procedure</head>
      <list rend="ol">{long_items}</list>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)

    list_chunks = [c for c in chunks if "Step 0:" in c.text]
    assert len(list_chunks) == 1
    for i in range(60):
        assert f"Step {i}:" in list_chunks[0].text


def test_run_on_text_with_no_punctuation_gets_token_boundary_split() -> None:
    """Regression test for the gap the token-boundary fallback closes: text
    with no sentence-ending punctuation at all used to be accepted as one
    oversized chunk with no further recourse. Now it must actually split."""
    run_on = " ".join(f"word{i}" for i in range(1000))  # no periods anywhere
    xml = f"""<doc><main>
      <head rend="h1">Transcript</head>
      <p>{run_on}</p>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)

    assert len(chunks) > 1, "run-on text with no punctuation must still be split"
    for c in chunks:
        assert c.token_count <= MAX_CHUNK_TOKENS + 5
    # No words lost or duplicated across the split.
    all_words = " ".join(c.text for c in chunks).split()
    assert all_words == [f"word{i}" for i in range(1000)]


def test_single_oversized_sentence_gets_token_boundary_split() -> None:
    """A single sentence (correctly identified as one by punctuation) that
    is itself still oversized must not be accepted whole — falls through
    to the same token-boundary fallback."""
    huge_sentence = " ".join(f"word{i}" for i in range(900)) + "."
    normal_sentence = "This is a short second sentence."
    xml = f"""<doc><main>
      <head rend="h1">Section</head>
      <p>{huge_sentence} {normal_sentence}</p>
    </main></doc>"""
    doc = _doc(content_xml=xml)
    chunks = chunk_doc(doc, count_tokens=word_count)

    assert len(chunks) > 1
    for c in chunks:
        assert c.token_count <= MAX_CHUNK_TOKENS + 5
    assert any("short second sentence" in c.text for c in chunks)


def test_malformed_xml_falls_back_to_plain_text_not_crash() -> None:
    fallback_text = "Fallback plain text content here, long enough."
    doc = _doc(content_xml="<doc><main><p>unterminated", text=fallback_text)
    chunks = chunk_doc(doc, count_tokens=word_count)  # must not raise
    assert len(chunks) >= 1
    assert chunks[0].heading_path == ["Test Doc"]  # page-title fallback


def test_empty_content_xml_falls_back_to_plain_text() -> None:
    doc = _doc(content_xml="", text="Some plain text with no structure at all, long enough to count as real.")
    chunks = chunk_doc(doc, count_tokens=word_count)
    assert len(chunks) == 1
    assert chunks[0].heading_path == ["Test Doc"]  # page-title fallback
    assert "plain text" in chunks[0].text.lower()


def test_doc_with_no_content_at_all_produces_no_chunks() -> None:
    doc = _doc(content_xml="", text="")
    chunks = chunk_doc(doc, count_tokens=word_count)
    assert chunks == []


def test_chunk_ids_are_sequential_and_stable() -> None:
    xml = """<doc><main>
      <head rend="h1">A</head><p>First real paragraph of decent length here.</p>
      <head rend="h1">B</head><p>Second real paragraph of decent length here.</p>
    </main></doc>"""
    doc = _doc(content_xml=xml, doc_id="doc-abc123")
    chunks = chunk_doc(doc, count_tokens=word_count)
    for i, c in enumerate(chunks):
        assert c.id == f"doc-abc123-chunk-{i:03d}"
        assert c.order_idx == i


def test_parse_blocks_handles_completely_invalid_xml() -> None:
    assert _parse_blocks("not xml at all <<<") == []
    assert _parse_blocks("") == []
