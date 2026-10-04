"""Stage 02 — Content Extraction.

trafilatura strips nav/ads/footers from HTML -> clean text + provenance +
language. Extended (deliberately, on top of README_rag.md's original
wording) to also extract real text from PDFs via pypdf, since Scamwatch's
real sitemap links 44 of them — a page's-worth of trusted content that
"only handle HTML" would silently drop.

Design decisions made explicit here:

- Core extraction functions (extract_page, extract_pages) take plain
  in-memory data — a PageRecord plus optional raw bytes — not file paths.
  Reading from disk (cache dirs, fixture files) is a thin adapter at the
  edges (load_extraction_inputs_from_cache / _from_fixture). Same pattern
  as stage 01's injectable httpx.Client: keep the logic testable without
  needing real files or a real crawl to test it against.
- A page's raw HTML lives directly on its PageRecord (stage 01 stores it
  there for text content). A page's raw PDF bytes do NOT — stage 01
  deliberately keeps binary content out of the `html: str` field and
  caches it separately as <hash>.bin. ExtractionInput.raw_bytes is how
  that binary content reaches this stage.
- PDF text extraction includes a de-duplication pass: real PDFs (the
  Scamwatch "Little Book of Scams" fixture confirmed this) commonly repeat
  a running header/footer line on every page. trafilatura strips this kind
  of boilerplate automatically for HTML; pypdf does not for PDF, so we do
  it ourselves — any line appearing on more than half the document's pages
  is treated as boilerplate and dropped.
- Document-level de-duplication by exact text match: confirmed on real
  Scamwatch data that 125 of 477 docs (26%) were byte-identical duplicates
  — the same page fetched as both http:// and https://, discovered as two
  separate sitemap entries. Deliberately not "fixed" at stage 01 by
  recording the post-redirect resolved URL instead: that wouldn't actually
  prevent the duplicate fetch (both URLs are still separately discovered
  and crawled), and it would need cached pages' metadata to carry the
  resolved URL too for a cache-hit re-run to benefit, which is more
  surface area for a bug than the problem justifies. Deduplicating the
  output here is simpler, solves the measured problem directly, and needs
  no re-crawl.
- Known, deliberately deferred gap: trafilatura returned nothing at all
  (not "too short" — nothing) for two real Scamwatch pages, the Chinese
  Simplified and Traditional versions of a "scams targeting the Chinese
  community" page. This is a documented real limitation of readability-
  style extractors on CJK text: their content-vs-boilerplate heuristics
  commonly rely on word/whitespace counting, which breaks down on text
  with no spaces between words. Not fixed here — logged as a known
  limitation rather than silently accepted, so it doesn't get rediscovered
  from scratch when multilingual sourcing gets a real look later.
- Single-column tables are unwrapped into plain paragraphs (both in text
  and content_xml). Confirmed on real eSafety data: 80 of 294 docs wrap a
  whole video transcript in a one-column table headed "Audio". In text that
  came out as markdown table rows ("| Audio |", "|---|", then the entire
  transcript squashed into one "| ... |" cell line); in content_xml as a
  <table> stage 03 would have to know to look inside. A table with only one
  column has no tabular meaning — it's layout — so unwrapping it is a
  general rule, not an eSafety special case. Real multi-column tables are
  left exactly as they are.
- Missing-title fallback. Confirmed on real eSafety data: all 56 /media
  pages had title "| eSafety Commissioner" — the site-name suffix with an
  empty page name in front, because those pages' <title>/og:title are
  blank before the separator. A title that is empty or starts with a
  separator is treated as missing and replaced by the page's first heading
  (else first text line), keeping the site suffix for consistency:
  "Changing passwords on Macs | eSafety Commissioner".
- Within-document clean-up (_clean_document_xml / _clean_document_text),
  all measured on the real chunk files before writing it:
  * Repeated content: on 212 of 929 Be Connected pages the video transcript
    appeared twice — once as clean sentences, once line-wrapped under
    "Topic outline > General" — so ~20% of Be Connected chunks (and ~42% of
    its tokens) were copies of other chunks in the same page, and two copies
    of one page took 2 of 5 retrieval slots. A text block whose whitespace-
    normalised text is already contained in earlier text of the SAME page is
    dropped (first copy kept). Whitespace-normalised because the copies
    differ only in where lines wrap. Blocks under MIN_REPEAT_CHARS are never
    dropped this way: short lines can legitimately repeat.
  * UI boilerplate: Be Connected's "Join or sign in / Sign in to save your
    progress..." (262 chunks) and course menus "3 Signing in to myGov 6 min
    Start now" (513 lines). Exact whole-block patterns only.
  * Oversized blocks: 122 Be Connected chunks exceeded 500 tokens (max
    2,642) because a whole transcript was one block, which stage 03 can't
    split. Three real shapes: a long <p>; a long <p> inside a list item; and
    (84 pages) one list item holding many normal <p> — see
    PROSE_LIST_MIN_CHARS. <p>/<quote> over MAX_PARAGRAPH_CHARS are split at sentence ends
    (inline formatting inside them is flattened), and a <list> with an item
    that long is turned into paragraphs, since stage 03 keeps lists whole.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from xml.sax import saxutils

import trafilatura
from langdetect import LangDetectException, detect
from pydantic import HttpUrl
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from rag.schemas import ExtractedDoc, ExtractionRunSummary, PageRecord

logger = logging.getLogger("rag.extract")

# Content types this stage knows how to extract. Anything else (RSS feeds,
# zip files, images) is skipped with a counted, logged reason — not
# silently dropped, not guessed at.
HTML_CONTENT_TYPES_PREFIX = "text/html"
PDF_CONTENT_TYPE = "application/pdf"

LANG_DETECT_SAMPLE_CHARS = 2000  # enough for a reliable langdetect call, fast even on a 40-page PDF
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


def _detect_lang(text: str) -> str:
    sample = text[:LANG_DETECT_SAMPLE_CHARS].strip()
    if not sample:
        return "unknown"
    try:
        return detect(sample)
    except LangDetectException:
        return "unknown"


def _extract_html(html: str, url: str) -> tuple[str, str, str] | None:
    """Returns (title, text, content_xml), or None if trafilatura found
    nothing usable (e.g. a page that's all navigation, or malformed markup
    it can't parse).

    content_xml uses trafilatura's XML output, not markdown — confirmed on
    real data that markdown's *text serialization* introduces real
    structural bugs XML doesn't have (see the field's docstring in
    schemas.py for the two confirmed cases: a heading glued onto its own
    following paragraph with no newline, and a heading nested inside a
    list item rendered with no separator). Both were clean, unambiguous
    separate elements in the same page's XML output.

    Includes a recovery pass for a real, confirmed failure mode: trafilatura
    silently dropped an entire numbered "what to do if you've been scammed"
    procedure on a real Scamwatch page, because it's wrapped in a Drupal
    component literally classed paragraph--type--accc-next-steps-call-out —
    a reusable "callout" block type. Confirmed at scale afterward: 315 of
    929 real Be Connected docs and 34 of 314 real Scamwatch docs gained
    recovered content this way, over 1,000,000 characters total — mostly
    full video transcripts hidden behind a similar toggle/expand component.
    Recovered content is appended to both text and content_xml (as a plain
    paragraph and as a <p> element respectively) so heading-based
    chunking in stage 03 doesn't lose it either — as plain paragraphs, not
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
        # Deliberately <p> paragraphs, not <list><item> — confirmed real bug:
        # representing recovered content as a <list> made stage 03 treat it
        # as an atomic, unsplittable unit (correct for a genuine short
        # numbered procedure, catastrophic for what most recovered content
        # actually is). Real example: a recovered podcast transcript became
        # a single 8,968-token chunk — 18x the 500-token budget — because
        # it was structurally a <ul><li> accordion widget in the source
        # HTML, not a procedure, and got list-shaped recovery formatting
        # regardless. Paragraphs let normal size-based packing apply. The
        # one confirmed genuine short procedure this recovery exists for
        # (the "Act fast / Get help / Report the scam" 3-item list) is
        # short enough to still land in one chunk under normal packing —
        # this trades a small, unconfirmed risk of splitting a short
        # recovered procedure for definitely fixing a large, confirmed one.
        xml_items = "\n".join(
            f"  <p>{saxutils.escape(line)}</p>"
            for block in recovered
            for line in block.split("\n")
        )
        content_xml = content_xml.replace("</main>", f"{xml_items}\n</main>", 1)

    content_xml, tables_unwrapped = _unwrap_single_column_tables_xml(content_xml)
    if tables_unwrapped:
        text = _unwrap_single_column_tables_text(text)
    content_xml, _cleanup_counts = _clean_document_xml(content_xml)
    text = _clean_document_text(text)
    if _title_is_missing(title):
        title = _fallback_title(title, content_xml, text)

    return title, text, content_xml


# ---------------------------------------------------------------------------
# Single-column table unwrapping + missing-title fallback (see module docstring)
# ---------------------------------------------------------------------------

_HEADER_LABEL_MAX_CHARS = 40  # "Audio", "Transcript" — a label, not content
_MD_ONE_COL_SEPARATOR = re.compile(r"^\|\s*:?-{3,}:?\s*\|\s*$")
_TITLE_SEPARATORS = ("|", "-", "\u2013", "\u2014", ":")


def _is_single_column(table: ElementTree.Element) -> bool:
    rows = table.findall("row")
    return bool(rows) and all(len(row.findall("cell")) <= 1 for row in rows)


def _unwrap_single_column_tables_xml(content_xml: str) -> tuple[str, int]:
    """Replaces each one-column <table> with its cells' contents, in place.
    A short header-cell label ("Audio") is dropped; any other cell text is
    kept as a <p>. Returns (content_xml, tables_unwrapped). Multi-column
    tables and unparseable XML are returned untouched."""
    if "<table" not in content_xml:
        return content_xml, 0
    try:
        root = ElementTree.fromstring(content_xml)
    except ElementTree.ParseError:
        return content_xml, 0

    unwrapped = 0
    for parent in list(root.iter()):
        for table in [c for c in parent if c.tag == "table" and _is_single_column(c)]:
            replacement: list[ElementTree.Element] = []
            for row in table.findall("row"):
                for cell in row.findall("cell"):
                    cell_text = (cell.text or "").strip()
                    is_label = (cell.get("role") == "head" and len(cell) == 0
                                and len(cell_text) <= _HEADER_LABEL_MAX_CHARS)
                    if is_label:
                        continue
                    if cell_text:
                        p = ElementTree.Element("p")
                        p.text = cell_text
                        replacement.append(p)
                    replacement.extend(list(cell))
            if replacement and table.tail and table.tail.strip():
                replacement[-1].tail = (replacement[-1].tail or "") + table.tail
            position = list(parent).index(table)
            parent.remove(table)
            for offset, element in enumerate(replacement):
                parent.insert(position + offset, element)
            unwrapped += 1
    if not unwrapped:
        return content_xml, 0
    ElementTree.indent(root)
    return ElementTree.tostring(root, encoding="unicode"), unwrapped


def _unwrap_single_column_tables_text(text: str) -> str:
    """Text-side twin of the XML unwrap. trafilatura renders a one-column
    table as markdown rows: '| Audio |', '|---|', then '| ...content... |'.
    Drops a short header label + separator and strips the cell pipes."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if line.startswith("|") and line.endswith("|") and _MD_ONE_COL_SEPARATOR.match(nxt):
            header = line.strip("|").strip()
            if header and len(header) > _HEADER_LABEL_MAX_CHARS:
                out.append(header)
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cell = lines[i].strip()
                cell = cell[1:] if cell.startswith("|") else cell
                cell = cell[:-1] if cell.endswith("|") else cell
                if cell.strip():
                    out.append(cell.strip())
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Within-document clean-up: repeated content, UI boilerplate, oversized
# paragraphs (see module docstring for the real data behind each)
# ---------------------------------------------------------------------------

MIN_REPEAT_CHARS = 40          # shorter lines ("Start now", "FAQs") may legitimately repeat
LONG_REPEAT_CHARS = 250        # a repeated block this long is a copied passage on its own
MIN_REPEAT_RUN_CHARS = 800     # ...or consecutive repeated blocks totalling this much (see below)
LABEL_PREFIX_MAX_CHARS = 120   # "Transcript: <video title> " in front of a copied passage
MAX_PARAGRAPH_CHARS = 1200     # ~270 BGE-m3 tokens: comfortably under stage 03's 500-token budget
TARGET_SPLIT_CHARS = 900
PROSE_LIST_MIN_CHARS = 2000    # ~450 tokens: a list shorter than this fits in one chunk anyway
_BLOCK_TAGS = {"p", "item", "quote"}
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\u2018\u201c(\[])")

# Whole-block UI text, matched against a block's full whitespace-normalised
# text. All confirmed on real Be Connected course pages (262 and 513 chunks).
BOILERPLATE_BLOCK_PATTERNS = [
    re.compile(r"(Join or sign in\s*)?Sign in to save your progress( and earn a certificate)?"
               r"(\s*Join / Sign in)?"),
    re.compile(r"\d+\s+.{3,150}?\s+\d+\s+min\s+(Start now|Continue|Review|Completed|Start again)"),
]


def _norm_ws(s: str) -> str:
    return " ".join(s.split())


def _is_boilerplate(normalised: str) -> bool:
    return any(p.fullmatch(normalised) for p in BOILERPLATE_BLOCK_PATTERNS)


def _is_labelled_copy(text: str, seen: str) -> bool:
    """A long block that is an earlier passage with a short label in front.
    Confirmed real case (Be Connected): the second transcript copy is one
    block starting "Transcript: How to make a video call with WhatsApp", then
    the same text as the clean copy earlier on the page, so a whole-block
    containment check never matches. Only for long blocks, and the part that
    must already be present is everything after the first ~quarter (capped
    at LABEL_PREFIX_MAX_CHARS)."""
    if len(text) < LONG_REPEAT_CHARS:
        return False
    skip = min(LABEL_PREFIX_MAX_CHARS, len(text) // 4)
    return text[skip:] in seen


def _repeated_block_indexes(texts: list[str]) -> set[int]:
    """Which blocks are copies of earlier content in the same document.

    A block is a *candidate* if its normalised text (>= MIN_REPEAT_CHARS) is
    contained in the text before it. Candidates are only dropped when they're
    clearly a copied passage: long on their own (>= LONG_REPEAT_CHARS), or
    part of a consecutive run of candidates totalling >= MIN_REPEAT_RUN_CHARS.

    Why not drop every candidate: procedures legitimately repeat steps.
    Confirmed on my.gov.au: "Select Get started in the Digital ID
    (Recommended) box and follow the prompts." appears in several separate
    procedures on one page, and set-up-the-mygov-app repeats a 4-step run
    for two devices. Removing them from the later procedure breaks it.
    800 chars comes from the real data: every repeated run on myGov and
    Scamwatch is <= 753 chars (repeated procedures), while the duplicated
    Be Connected transcripts this exists for are 900-10,000 chars."""
    candidate: list[bool] = []
    seen = ""
    for text in texts:
        candidate.append(len(text) >= MIN_REPEAT_CHARS and (text in seen or _is_labelled_copy(text, seen)))
        seen = f"{seen} {text}"
    drop: set[int] = set()
    i = 0
    while i < len(texts):
        if not candidate[i]:
            i += 1
            continue
        j = i
        while j < len(texts) and candidate[j]:
            j += 1
        run = range(i, j)
        if sum(len(texts[k]) for k in run) >= MIN_REPEAT_RUN_CHARS:
            drop.update(run)
        else:
            drop.update(k for k in run if len(texts[k]) >= LONG_REPEAT_CHARS)
        i = j
    return drop


def _split_long_paragraph(text: str) -> list[str]:
    """Sentence-boundary split into pieces of roughly TARGET_SPLIT_CHARS.
    A single sentence longer than that stays whole (never cut mid-sentence)."""
    sentences = _SENTENCE_END.split(text)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + 1 + len(sentence) > TARGET_SPLIT_CHARS:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        pieces.append(current)
    return pieces


def _outermost_list(
    element: ElementTree.Element, parent_of: dict[ElementTree.Element, ElementTree.Element]
) -> ElementTree.Element | None:
    """The outermost <list> containing `element` (stage 03 keeps that whole
    list together, nested lists included), or None."""
    found = None
    node = parent_of.get(element)
    while node is not None:
        if node.tag == "list":
            found = node
        node = parent_of.get(node)
    return found


def _list_text_units(lst: ElementTree.Element) -> list[str]:
    """One text unit per leaf block (<p>/<quote>/<item> holding no other
    blocks) inside the list, in document order, so paragraph breaks inside
    an item survive the flattening."""
    units = []
    for el in lst.iter():
        if el.tag not in _BLOCK_TAGS:
            continue
        if any(child.tag in _BLOCK_TAGS for child in el.iter() if child is not el):
            continue
        text = _norm_ws("".join(el.itertext()))
        if text:
            units.append(text)
    return units


def _replace_with_paragraphs(
    parent: ElementTree.Element, old: ElementTree.Element, pieces: list[str]
) -> None:
    """Swap `old` for one plain <p> per piece, in place, keeping its tail."""
    position = list(parent).index(old)
    tail = old.tail
    parent.remove(old)
    for offset, piece in enumerate(pieces):
        new_p = ElementTree.Element("p")
        new_p.text = piece
        parent.insert(position + offset, new_p)
    if pieces and tail and tail.strip():
        parent[position + len(pieces) - 1].tail = tail


def _clean_document_xml(content_xml: str) -> tuple[str, dict[str, int]]:
    """One pass over content_xml's text blocks (<p>, <item>, <quote>), in
    document order:
    - drops UI boilerplate blocks;
    - drops a block whose whitespace-normalised text is already contained in
      what came before it in the same document (keeps the FIRST copy);
    - splits an over-long <p>/<quote> into several <p> at sentence ends, and
      turns a <list> containing an over-long item into paragraphs.
    Returns (content_xml, counts). Unparseable XML is returned untouched."""
    counts = {"boilerplate": 0, "repeated": 0, "split": 0}
    if not content_xml:
        return content_xml, counts
    try:
        root = ElementTree.fromstring(content_xml)
    except ElementTree.ParseError:
        return content_xml, counts

    parent_of = {child: parent for parent in root.iter() for child in parent}
    blocks: list[tuple[ElementTree.Element, str]] = []
    for block in [el for el in root.iter() if el.tag in _BLOCK_TAGS]:
        if any(child.tag in _BLOCK_TAGS for child in block.iter() if child is not block):
            continue  # container (e.g. an <item> holding <p>s): judge its leaf blocks instead
        text = _norm_ws("".join(block.itertext()))
        if not text or parent_of.get(block) is None:
            continue
        if _is_boilerplate(text):
            parent_of[block].remove(block)
            counts["boilerplate"] += 1
            continue
        blocks.append((block, text))

    repeated = _repeated_block_indexes([text for _, text in blocks])
    lists_to_flatten: list[ElementTree.Element] = []
    for index, (block, text) in enumerate(blocks):
        parent = parent_of[block]
        if index in repeated:
            parent.remove(block)
            counts["repeated"] += 1
            continue
        if len(text) > MAX_PARAGRAPH_CHARS:
            enclosing_list = _outermost_list(block, parent_of)
            if enclosing_list is not None and enclosing_list.find(".//head") is None:
                # Splitting a block that sits inside a heading-less list
                # wouldn't help: the pieces stay in the list, and stage 03
                # keeps such lists whole. Confirmed real shape on Be Connected:
                # <list><item><p>whole transcript</p></item></list>.
                lists_to_flatten.append(enclosing_list)
            elif block.tag in ("p", "quote"):
                # Includes paragraphs inside a list that DOES contain headings:
                # stage 03 already unwraps those lists itself (see its test
                # test_native_list_with_nested_headings_is_unwrapped_not_atomic),
                # so the list and its headings are left alone and only the
                # over-long paragraph is split, ready for stage 03's packing.
                pieces = _split_long_paragraph(text)
                if len(pieces) > 1:
                    _replace_with_paragraphs(parent, block, pieces)
                    counts["split"] += 1

    # Prose wrapped in a list: one <item> holding several ordinary-sized <p>,
    # so no single block is long but the list is. Confirmed real shape on 84
    # Be Connected pages (e.g. "iPad: Listening to podcasts"):
    # <list rend="ul"><item><p>Welcome to...</p><p>A podcast is...</p>...
    # which stage 03 kept whole as one chunk of up to 2,508 tokens. An item
    # made of 2+ paragraphs is prose, not a procedure step; real bullet lists
    # (e.g. eSafety's checklists) have one line per item and are untouched.
    for lst in [el for el in root.iter("list") if _outermost_list(el, parent_of) is None]:
        if lst.find(".//head") is not None:
            continue  # stage 03 unwraps lists with headings itself
        has_prose_item = any(len(item.findall("p")) >= 2 for item in lst.iter("item"))
        if has_prose_item and len(_norm_ws("".join(lst.itertext()))) > PROSE_LIST_MIN_CHARS:
            lists_to_flatten.append(lst)

    # Stage 03 keeps a <list> whole (right for a short procedure). A list
    # with an item longer than MAX_PARAGRAPH_CHARS isn't a procedure: on real
    # Be Connected pages it's a whole video transcript in one <li> (122
    # chunks of 500-2,642 tokens, all the first block on the page). Turn
    # such a list into paragraphs so normal size-based packing applies.
    for lst in dict.fromkeys(lists_to_flatten):
        holder = parent_of.get(lst)
        if holder is None or lst not in list(holder):
            continue
        paragraphs = [piece
                      for unit in _list_text_units(lst)
                      for piece in _split_long_paragraph(unit)
                      if piece]
        _replace_with_paragraphs(holder, lst, paragraphs)
        counts["split"] += 1

    # A <list> whose every item was removed would be an empty shell.
    for parent in list(root.iter()):
        for child in [c for c in parent if c.tag == "list" and not c.findall("item")]:
            parent.remove(child)

    if not any(counts.values()):
        return content_xml, counts
    ElementTree.indent(root)
    return ElementTree.tostring(root, encoding="unicode"), counts


def _clean_document_text(text: str) -> str:
    """Text-side twin of _clean_document_xml (boilerplate + repeats, line by
    line, same rules), so `text` and `content_xml` tell the same story."""
    lines = [ln for ln in text.split("\n") if not _is_boilerplate(_norm_ws(ln))]
    content = [(i, _norm_ws(ln)) for i, ln in enumerate(lines) if _norm_ws(ln)]
    repeated = {content[k][0] for k in _repeated_block_indexes([t for _, t in content])}
    kept = [ln for i, ln in enumerate(lines) if i not in repeated]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def _title_is_missing(title: str) -> bool:
    stripped = title.strip()
    return not stripped or stripped.startswith(_TITLE_SEPARATORS)


def _fallback_title(title: str, content_xml: str, text: str) -> str:
    """Only called when _title_is_missing(title). Prefers the first heading
    in content_xml, then the first real text line; keeps the original site
    suffix ("| eSafety Commissioner") when there is one."""
    page_name = ""
    if content_xml:
        try:
            head = ElementTree.fromstring(content_xml).find(".//head")
            if head is not None:
                page_name = " ".join("".join(head.itertext()).split())
        except ElementTree.ParseError:
            pass
    if not page_name:
        page_name = next((ln.strip() for ln in text.splitlines()
                          if ln.strip() and not ln.strip().startswith("|")), "")
    page_name = page_name[:150]
    suffix = title.strip()
    if page_name and suffix:
        return f"{page_name} {suffix}"
    return page_name or suffix


def _list_item_texts(html: str) -> list[list[str]]:
    """Returns the plain text of each <li> within each top-level <ol>/<ul>
    in the document, one inner list per outer list found. Uses a small
    HTMLParser rather than regex — nested lists and nested tags inside
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
    except Exception:  # noqa: BLE001 — same reasoning as the link-extraction guard in stage 01
        return []
    return [items for items in parser.lists if items]


def _recover_missed_lists(html: str, extracted_text: str) -> list[str]:
    """Finds <ol>/<ul> lists whose content isn't already in trafilatura's
    output and that look like real content rather than navigation, and
    returns their text as recoverable blocks.

    The content-vs-navigation distinction is a length heuristic, not a
    class-name allowlist — deliberately, so it isn't hand-tuned to this one
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
            continue  # short items — looks like nav/breadcrumb, not content

        # Already captured? Check the first item's text as a fingerprint —
        # cheap, and good enough since a coincidental full-sentence match
        # is vanishingly unlikely.
        fingerprint = items[0][:60]
        if fingerprint and fingerprint in extracted_text:
            continue

        recovered.append("\n".join(items))
    return recovered


def _strip_repeated_lines(pages_text: list[str]) -> list[str]:
    """Drops lines that repeat across more than half a PDF's pages —
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
    with no text layer — a real possibility we haven't hit yet but
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
        except Exception:  # noqa: BLE001 — pypdf's per-page failure modes aren't a fixed set either
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
        # game is designed for use in Portrait Mode" (72 chars) — UI chrome,
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
        lang=_detect_lang(text), fetched_at=record.fetched_at, text=text, content_xml=content_xml,
        source_content_type=record.content_type,
    )
    return ExtractionOutcome(doc=doc, skip_reason=None)


def extract_page(inp: ExtractionInput, log: logging.LoggerAdapter) -> ExtractedDoc | None:
    """Single-page convenience wrapper. Returns None (and logs exactly why)
    for anything that shouldn't become a doc: a failed fetch, an
    unsupported content type, or content that parsed but yielded nothing
    usable. Use extract_pages for a batch — it gets the skip reasons for
    free from the same underlying logic, no re-derivation.
    """
    return _extract_page_outcome(inp, log).doc


def deduplicate_docs(docs: list[ExtractedDoc], log: logging.LoggerAdapter) -> tuple[list[ExtractedDoc], int]:
    """Drops exact-text duplicates, keeping one canonical doc per unique
    text. When duplicates differ only by http:// vs https://, keeps the
    https version deterministically — not just "whichever came first",
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
        # Prefer https, then shorter URL, then doc_id — all just tie-breaks
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
    doesn't need this — record.html already has it.
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
    in a sibling file — sample_little_book_of_scams.pdf for the one PDF we
    currently have. Extend PDF_FIXTURE_FILES if more binary fixtures are added.
    """
    PDF_FIXTURE_FILES = {
        "https://scamwatch.gov.au/system/files/little-book-scams-2024-english.pdf":
            "sample_little_book_of_scams.pdf",
    }
    pages = [PageRecord.model_validate(p) for p in json.loads(fixture_json_path.read_text())]
    inputs = []
    for record in pages:
        raw_bytes = None
        pdf_filename = PDF_FIXTURE_FILES.get(str(record.url))
        if pdf_filename:
            raw_bytes = (fixture_dir / pdf_filename).read_bytes()
        inputs.append(ExtractionInput(record=record, raw_bytes=raw_bytes))
    return inputs
