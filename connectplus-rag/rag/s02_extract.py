"""Stage 02 - Content Extraction.

trafilatura strips nav/ads/footers from HTML -> clean text + provenance +
language. Extended (deliberately, on top of README_rag.md's original
wording) to also extract real text from PDFs via pypdf, since Scamwatch's
real sitemap links 44 of them - a page's-worth of trusted content that
"only handle HTML" would silently drop.

Design decisions made explicit here:

- Core extraction functions (extract_page, extract_pages) take plain
  in-memory data - a PageRecord plus optional raw bytes - not file paths.
  Reading from disk (cache dirs, fixture files) is a thin adapter at the
  edges (load_extraction_inputs_from_cache / _from_fixture). Same pattern
  as stage 01's injectable httpx.Client: keep the logic testable without
  needing real files or a real crawl to test it against.
- A page's raw HTML lives directly on its PageRecord (stage 01 stores it
  there for text content). A page's raw PDF bytes do NOT - stage 01
  deliberately keeps binary content out of the `html: str` field and
  caches it separately as <hash>.bin. ExtractionInput.raw_bytes is how
  that binary content reaches this stage.
- PDF text extraction includes a de-duplication pass: real PDFs (the
  Scamwatch "Little Book of Scams" fixture confirmed this) commonly repeat
  a running header/footer line on every page. trafilatura strips this kind
  of boilerplate automatically for HTML; pypdf does not for PDF, so we do
  it ourselves - any line appearing on more than half the document's pages
  is treated as boilerplate and dropped.
- Document-level de-duplication by exact text match: confirmed on real
  Scamwatch data that 125 of 477 docs (26%) were byte-identical duplicates
  - the same page fetched as both http:// and https://, discovered as two
  separate sitemap entries. Deliberately not "fixed" at stage 01 by
  recording the post-redirect resolved URL instead: that wouldn't actually
  prevent the duplicate fetch (both URLs are still separately discovered
  and crawled), and it would need cached pages' metadata to carry the
  resolved URL too for a cache-hit re-run to benefit, which is more
  surface area for a bug than the problem justifies. Deduplicating the
  output here is simpler, solves the measured problem directly, and needs
  no re-crawl.
- Known, deliberately deferred gap: trafilatura returned nothing at all
  (not "too short" - nothing) for two real Scamwatch pages, the Chinese
  Simplified and Traditional versions of a "scams targeting the Chinese
  community" page. This is a documented real limitation of readability-
  style extractors on CJK text: their content-vs-boilerplate heuristics
  commonly rely on word/whitespace counting, which breaks down on text
  with no spaces between words. Not fixed here - logged as a known
  limitation rather than silently accepted, so it doesn't get rediscovered
  from scratch when multilingual sourcing gets a real look later.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.sax import saxutils

import trafilatura
from pydantic import HttpUrl
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from rag.lang import detect_lang
from rag.schemas import ExtractedDoc, ExtractionRunSummary, PageRecord

logger = logging.getLogger("rag.extract")

# Content types this stage knows how to extract. Anything else (RSS feeds,
# zip files, images) is skipped with a counted, logged reason - not
# silently dropped, not guessed at.
HTML_CONTENT_TYPES_PREFIX = "text/html"
PDF_CONTENT_TYPE = "application/pdf"

MIN_EXTRACTED_TEXT_LENGTH = 100  # see the comment at its use site for where this number comes from


class _JsonLogAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra["run_id"] = self.extra["run_id"]
        return msg, kwargs


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import datetime as _dt

        payload = {
            "ts": _dt.datetime.now(_dt.UTC).isoformat(),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", None),
            "event": record.getMessage(),
        }
        for key in ("domain", "url", "reason"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


def configure_json_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


@dataclass
class ExtractionInput:
    """Pairs a stage 01 PageRecord with the raw bytes extraction actually
    needs for binary content. `raw_bytes` is None for text content (use
    record.html instead) and for pages that were never fetched successfully.
    """

    record: PageRecord
    raw_bytes: bytes | None = None


def _doc_id(url: str) -> str:
    """Same hashing scheme as stage 01's page cache keys, different
    namespace prefix so a doc_id is never mistaken for a stage 01 cache
    filename even though the underlying hash is identical."""
    return "doc-" + hashlib.sha256(url.encode()).hexdigest()[:16]


def _extract_html(html: str, url: str) -> tuple[str, str, str] | None:
    """Returns (title, text, content_xml), or None if trafilatura found
    nothing usable (e.g. a page that's all navigation, or malformed markup
    it can't parse).

    content_xml uses trafilatura's XML output, not markdown - confirmed on
    real data that markdown's *text serialization* introduces real
    structural bugs XML doesn't have (see the field's docstring in
    schemas.py for the two confirmed cases: a heading glued onto its own
    following paragraph with no newline, and a heading nested inside a
    list item rendered with no separator). Both were clean, unambiguous
    separate elements in the same page's XML output.

    Includes a recovery pass for a real, confirmed failure mode: trafilatura
    silently dropped an entire numbered "what to do if you've been scammed"
    procedure on a real Scamwatch page, because it's wrapped in a Drupal
    component literally classed paragraph--type--accc-next-steps-call-out -
    a reusable "callout" block type. Confirmed at scale afterward: 315 of
    929 real Be Connected docs and 34 of 314 real Scamwatch docs gained
    recovered content this way, over 1,000,000 characters total - mostly
    full video transcripts hidden behind a similar toggle/expand component.
    Recovered content is appended to both text and content_xml (as a plain
    paragraph and as a <p> element respectively) so heading-based
    chunking in stage 03 doesn't lose it either - as plain paragraphs, not
    an atomic list (see the comment at the recovery call site for why).
    """
    result = trafilatura.extract(
        html, url=url, output_format="json", with_metadata=True, favor_precision=True
    )
    if not result:
        return None
    data = json.loads(result)
    text = (data.get("text") or "").strip()
    if not text:
        return None
    title = (data.get("title") or "").strip()

    content_xml = trafilatura.extract(html, url=url, output_format="xml", favor_precision=True) or ""
    content_xml = content_xml.strip()

    recovered = _recover_missed_lists(html, text)
    if recovered:
        text = text + "\n\n" + "\n\n".join(recovered)
        # Deliberately <p> paragraphs, not <list><item> - confirmed real bug:
        # representing recovered content as a <list> made stage 03 treat it
        # as an atomic, unsplittable unit (correct for a genuine short
        # numbered procedure, catastrophic for what most recovered content
        # actually is). Real example: a recovered podcast transcript became
        # a single 8,968-token chunk - 18x the 500-token budget - because
        # it was structurally a <ul><li> accordion widget in the source
        # HTML, not a procedure, and got list-shaped recovery formatting
        # regardless. Paragraphs let normal size-based packing apply. The
        # one confirmed genuine short procedure this recovery exists for
        # (the "Act fast / Get help / Report the scam" 3-item list) is
        # short enough to still land in one chunk under normal packing -
        # this trades a small, unconfirmed risk of splitting a short
        # recovered procedure for definitely fixing a large, confirmed one.
        xml_items = "\n".join(
            f"  <p>{saxutils.escape(line)}</p>"
            for block in recovered
            for line in block.split("\n")
        )
        content_xml = content_xml.replace("</main>", f"{xml_items}\n</main>", 1)

    return title, text, content_xml


def _list_item_texts(html: str) -> list[list[str]]:
    """Returns the plain text of each <li> within each top-level <ol>/<ul>
    in the document, one inner list per outer list found. Uses a small
    HTMLParser rather than regex - nested lists and nested tags inside
    <li> (a <p> inside an <a> inside an <li>, seen in the real failing
    case) aren't reliably matchable with regex.
    """

    class ListExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.lists: list[list[str]] = []
            self._depth = 0
            self._current_item: list[str] | None = None

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in ("ol", "ul"):
                if self._depth == 0:
                    self.lists.append([])
                self._depth += 1
            elif tag == "li" and self._depth >= 1:
                self._current_item = []

        def handle_endtag(self, tag: str) -> None:
            if tag in ("ol", "ul") and self._depth > 0:
                self._depth -= 1
            elif tag == "li" and self._current_item is not None:
                if self.lists:
                    self.lists[-1].append(" ".join(self._current_item).strip())
                self._current_item = None

        def handle_data(self, data: str) -> None:
            if self._current_item is not None:
                stripped = data.strip()
                if stripped:
                    self._current_item.append(stripped)

    parser = ListExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 - same reasoning as the link-extraction guard in stage 01
        return []
    return [items for items in parser.lists if items]


def _recover_missed_lists(html: str, extracted_text: str) -> list[str]:
    """Finds <ol>/<ul> lists whose content isn't already in trafilatura's
    output and that look like real content rather than navigation, and
    returns their text as recoverable blocks.

    The content-vs-navigation distinction is a length heuristic, not a
    class-name allowlist - deliberately, so it isn't hand-tuned to this one
    Drupal component and silently misses the next site's equivalent. Real
    nav/breadcrumb items are short ("Home", "About us"); the real recovered
    case here averages well over 40 characters per item.
    """
    MIN_AVG_ITEM_LENGTH = 40
    MIN_TOTAL_LENGTH = 100

    recovered = []
    for items in _list_item_texts(html):
        combined = " ".join(items)
        if not items or len(combined) < MIN_TOTAL_LENGTH:
            continue
        avg_len = sum(len(i) for i in items) / len(items)
        if avg_len < MIN_AVG_ITEM_LENGTH:
            continue  # short items - looks like nav/breadcrumb, not content

        # Already captured? Check the first item's text as a fingerprint -
        # cheap, and good enough since a coincidental full-sentence match
        # is vanishingly unlikely.
        fingerprint = items[0][:60]
        if fingerprint and fingerprint in extracted_text:
            continue

        recovered.append("\n".join(items))
    return recovered


def _strip_repeated_lines(pages_text: list[str]) -> list[str]:
    """Drops lines that repeat across more than half a PDF's pages -
    running headers/footers like page numbers and a document title banner.
    Confirmed necessary against a real fixture, not a hypothetical: every
    page of the Scamwatch "Little Book of Scams" PDF repeats
    'ACCC | How to spot and avoid scams' plus a page number.
    """
    if len(pages_text) < 3:
        return pages_text  # too few pages for "repeated" to mean anything

    line_counts: Counter[str] = Counter()
    for page in pages_text:
        # count each distinct line once per page, not once per occurrence,
        # so a line repeated twice on one page doesn't skew the threshold
        for line in {line.strip() for line in page.splitlines() if line.strip()}:
            line_counts[line] += 1

    threshold = len(pages_text) / 2
    boilerplate = {line for line, count in line_counts.items() if count > threshold}

    cleaned = []
    for page in pages_text:
        kept_lines = [line for line in page.splitlines() if line.strip() not in boilerplate]
        cleaned.append("\n".join(kept_lines))
    return cleaned


def _extract_pdf(raw_bytes: bytes) -> tuple[str, str, str] | None:
    """Returns (title, text, content_xml), or None if the PDF can't be
    parsed at all or yields no extractable text (e.g. a scanned image PDF
    with no text layer - a real possibility we haven't hit yet but
    shouldn't crash on). content_xml is empty, not a copy of text: pypdf
    gives no font-size or heading-tag information, so there's no real
    structure to represent, and pretending otherwise (e.g. by echoing text
    into content_xml) would be a lie stage 03 would have to know to distrust.
    """
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except (PdfReadError, ValueError):
        return None

    pages_text = []
    for page in reader.pages:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - pypdf's per-page failure modes aren't a fixed set either
            pages_text.append("")

    pages_text = _strip_repeated_lines(pages_text)
    text = "\n\n".join(p.strip() for p in pages_text if p.strip()).strip()
    if not text:
        return None

    title = ""
    if reader.metadata and reader.metadata.title:
        title = str(reader.metadata.title).strip()
    if not title:
        title = text.splitlines()[0].strip()[:150]
    return title, text, ""


@dataclass
class ExtractionOutcome:
    """What happened to one page: either a doc, or exactly one named skip
    reason. Keeping this as a single source of truth (rather than having
    extract_pages re-derive "why" from a bare None) is what let removing
    the earlier duplicated-classification bug be a one-function fix."""

    doc: ExtractedDoc | None
    skip_reason: str | None  # "non_200_status" | "unsupported_content_type" | "empty_after_extraction"


def _extract_page_outcome(inp: ExtractionInput, log: logging.LoggerAdapter) -> ExtractionOutcome:
    record = inp.record
    url = str(record.url)

    if record.status != 200:
        log.info("skipped_non_200_status", extra={"domain": record.domain, "url": url})
        return ExtractionOutcome(doc=None, skip_reason="non_200_status")

    content_type = record.content_type.split(";")[0].strip().lower()
    extracted: tuple[str, str, str] | None

    if content_type.startswith(HTML_CONTENT_TYPES_PREFIX):
        extracted = _extract_html(record.html, url)
    elif content_type == PDF_CONTENT_TYPE:
        if inp.raw_bytes is None:
            log.warning("pdf_missing_raw_bytes", extra={"domain": record.domain, "url": url})
            return ExtractionOutcome(doc=None, skip_reason="empty_after_extraction")
        extracted = _extract_pdf(inp.raw_bytes)
    else:
        log.info(
            "skipped_unsupported_content_type",
            extra={"domain": record.domain, "url": url, "reason": content_type or "(empty)"},
        )
        return ExtractionOutcome(doc=None, skip_reason="unsupported_content_type")

    if extracted is None:
        log.warning("skipped_empty_after_extraction", extra={"domain": record.domain, "url": url})
        return ExtractionOutcome(doc=None, skip_reason="empty_after_extraction")

    title, text, content_xml = extracted
    if len(text) < MIN_EXTRACTED_TEXT_LENGTH:
        # Threshold set from real data, not a guess: real Be Connected SCORM
        # mini-game pages extract to exactly "Please rotate your device\nThis
        # game is designed for use in Portrait Mode" (72 chars) - UI chrome,
        # not content. The shortest genuinely real page found across the
        # whole corpus was 145 chars (a category landing blurb). 100 sits
        # cleanly in the 73-character gap between the two, confirmed against
        # the full real dataset before picking this number.
        log.warning(
            "skipped_empty_after_extraction",
            extra={"domain": record.domain, "url": url, "reason": f"only {len(text)} chars"},
        )
        return ExtractionOutcome(doc=None, skip_reason="empty_after_extraction")
    doc = ExtractedDoc(
        doc_id=_doc_id(url), url=HttpUrl(url), domain=record.domain, title=title,
        lang=detect_lang(text), fetched_at=record.fetched_at, text=text, content_xml=content_xml,
        source_content_type=record.content_type,
    )
    return ExtractionOutcome(doc=doc, skip_reason=None)


def extract_page(inp: ExtractionInput, log: logging.LoggerAdapter) -> ExtractedDoc | None:
    """Single-page convenience wrapper. Returns None (and logs exactly why)
    for anything that shouldn't become a doc: a failed fetch, an
    unsupported content type, or content that parsed but yielded nothing
    usable. Use extract_pages for a batch - it gets the skip reasons for
    free from the same underlying logic, no re-derivation.
    """
    return _extract_page_outcome(inp, log).doc


def deduplicate_docs(docs: list[ExtractedDoc], log: logging.LoggerAdapter) -> tuple[list[ExtractedDoc], int]:
    """Drops exact-text duplicates, keeping one canonical doc per unique
    text. When duplicates differ only by http:// vs https://, keeps the
    https version deterministically - not just "whichever came first",
    since that depends on manifest ordering, not anything meaningful.
    """
    groups: dict[str, list[ExtractedDoc]] = {}
    for doc in docs:
        groups.setdefault(doc.text, []).append(doc)

    kept: list[ExtractedDoc] = []
    removed = 0
    for text, group in groups.items():
        if len(group) == 1:
            kept.append(group[0])
            continue
        # Prefer https, then shorter URL, then doc_id - all just tie-breaks
        # for determinism; which exact duplicate survives doesn't matter,
        # only that the choice doesn't silently change between runs.
        group.sort(key=lambda d: (not str(d.url).startswith("https://"), len(str(d.url)), d.doc_id))
        survivor, dupes = group[0], group[1:]
        kept.append(survivor)
        removed += len(dupes)
        for dupe in dupes:
            log.info(
                "deduplicated_exact_text_match",
                extra={"domain": dupe.domain, "url": str(dupe.url), "reason": f"kept {survivor.url}"},
            )
    return kept, removed


def extract_pages(
    inputs: list[ExtractionInput], run_id: str | None = None
) -> tuple[list[ExtractedDoc], ExtractionRunSummary]:
    run_id = run_id or str(uuid.uuid4())
    log = _JsonLogAdapter(logger, {"run_id": run_id})

    docs: list[ExtractedDoc] = []
    skip_counts: Counter[str] = Counter()

    for inp in inputs:
        outcome = _extract_page_outcome(inp, log)
        if outcome.doc is not None:
            docs.append(outcome.doc)
        elif outcome.skip_reason is not None:
            skip_counts[outcome.skip_reason] += 1

    docs, deduplicated_count = deduplicate_docs(docs, log)

    summary = ExtractionRunSummary(
        total_input_pages=len(inputs), extracted=len(docs),
        skipped_non_200_status=skip_counts["non_200_status"],
        skipped_unsupported_content_type=skip_counts["unsupported_content_type"],
        skipped_empty_after_extraction=skip_counts["empty_after_extraction"],
        deduplicated_exact_text_matches=deduplicated_count,
    )
    return docs, summary


def load_extraction_inputs_from_cache(pages: list[PageRecord], cache_dir: Path) -> list[ExtractionInput]:
    """Production adapter: pairs each PageRecord with its raw bytes from
    stage 01's on-disk cache when the content is binary. Text content
    doesn't need this - record.html already has it.
    """
    inputs = []
    for record in pages:
        raw_bytes = None
        content_type = record.content_type.split(";")[0].strip().lower()
        if content_type == PDF_CONTENT_TYPE:
            key = hashlib.sha256(str(record.url).encode()).hexdigest()[:16]
            bin_path = cache_dir / record.domain / "pages" / f"{key}.bin"
            if bin_path.exists():
                raw_bytes = bin_path.read_bytes()
        inputs.append(ExtractionInput(record=record, raw_bytes=raw_bytes))
    return inputs


def load_extraction_inputs_from_fixture(fixture_json_path: Path, fixture_dir: Path) -> list[ExtractionInput]:
    """Fixture adapter for f01_pages.json: PDF entries in that file have
    html="" by design (see rag/fixtures/f01_pages.json) with the real bytes
    in a sibling file - sample_little_book_of_scams.pdf for the one PDF we
    currently have. Extend PDF_FIXTURE_FILES if more binary fixtures are added.
    """
    PDF_FIXTURE_FILES = {
        "https://scamwatch.gov.au/system/files/little-book-scams-2024-english.pdf":
            "sample_little_book_of_scams.pdf",
    }
    pages = [PageRecord.model_validate(p) for p in json.loads(fixture_json_path.read_text(encoding="utf-8"))]
    inputs = []
    for record in pages:
        raw_bytes = None
        pdf_filename = PDF_FIXTURE_FILES.get(str(record.url))
        if pdf_filename:
            raw_bytes = (fixture_dir / pdf_filename).read_bytes()
        inputs.append(ExtractionInput(record=record, raw_bytes=raw_bytes))
    return inputs
