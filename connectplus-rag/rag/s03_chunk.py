"""Stage 03 — Chunking.

Heading-aware splitting with overlap. A numbered procedure never gets split
mid-sequence.

Design decisions made explicit here (on top of README_rag.md's brief
description):

- Structure comes from ExtractedDoc.content_xml (stage 02's trafilatura XML
  output — <head rend="h1"/"h2"/etc.>, <p>, <list><item>), not from raw
  HTML and not from plain `text`. Plain text has no way to distinguish a
  heading from a body line at all. An earlier version of this parsed
  markdown text instead; that was abandoned after finding two real,
  confirmed bugs in trafilatura's markdown *serializer* specifically (a
  heading glued onto its immediately-following paragraph with no
  separating newline, and a heading nested inside a list item rendered
  with no separator) that don't exist in its XML output for the same
  content, where headings and paragraphs are distinct, unambiguous
  elements. XML in, real elements out — no string-parsing heuristics
  guessing where a heading ends and a paragraph begins.
- heading_path is best-effort, not guaranteed: one real Scamwatch page has
  its headings entirely excluded by trafilatura (a different symptom of
  the same root cause as the list-recovery fix in stage 02). A doc with no
  usable content_xml still chunks correctly — just with an empty
  heading_path — rather than being treated as an error case.
- "Never split a numbered procedure" is implemented as "never split any
  <list> element", not just numbered ones. trafilatura's XML uses the same
  <list rend="ul"|"ol"> element shape for both; there's no reliable signal
  in the real corpus to treat them differently, so every list is treated
  as atomic. This is a deliberately conservative choice: it protects real
  numbered procedures and costs nothing beyond (rarely) keeping a bullet
  list together that didn't strictly need to be.
- Chunk boundaries respect heading structure semantically, not just
  textually: small adjacent sections under the same parent heading merge
  together (using their common ancestor as the merged heading_path) to
  avoid producing lots of tiny sub-100-token chunks; a section that's too
  large for one chunk splits internally at paragraph/list-block
  boundaries, with every piece keeping the SAME full heading_path (since
  splitting never crosses a heading boundary, only ever content within
  one section).
- Token counting is injectable (a callable, not a hardcoded tokenizer
  call) for the same testability reason stage 01 injects httpx.Client:
  this sandbox's network can't reach huggingface.co to download BGE-m3's
  tokenizer, so the chunking *logic* is tested here against a lightweight
  stand-in counter, while get_default_token_counter() uses the real
  tokenizer for production use.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from xml.etree import ElementTree

from rag.schemas import Chunk, ExtractedDoc

TokenCounter = Callable[[str], int]

MIN_CHUNK_TOKENS = 300
MAX_CHUNK_TOKENS = 500
# Sections smaller than this merge forward with a sibling rather than
# standing alone as their own under-sized chunk.
MERGE_BELOW_TOKENS = 150
# When a section must be split across multiple chunks, this many tokens of
# the previous piece's tail are repeated at the start of the next piece —
# the "with overlap" part of the README's stage 03 description. Only
# applies to within-section splits (see design note above on why overlap
# never crosses a heading boundary).
OVERLAP_TOKENS = 40

HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}


@lru_cache(maxsize=1)
def get_default_token_counter() -> TokenCounter:
    """BGE-m3's own tokenizer (via transformers), loaded once per process —
    deliberately not tiktoken, an earlier choice since revised: tiktoken
    (OpenAI's tokenizer) handles non-Latin scripts inefficiently, and this
    corpus has confirmed real content in Vietnamese, Chinese, Hindi, and
    Greek — Scamwatch's in-your-language section and several translated
    PDFs. Measuring chunk size with the tokenizer belonging to the model
    these chunks actually get embedded with (stage 04's BGE-m3) is more
    correct than an approximation borrowed from an unrelated model's
    vocabulary. Loads only the tokenizer, not the full ~2GB model — a
    much smaller download, and keeps stage 03 independently runnable
    without stage 04's model in memory.

    Not used by any test in this repo — this sandbox can't reach
    huggingface.co to download it and verify it actually works (the same
    restriction that blocked testing BGE-m3's encoder in stage 04), so
    tests inject a stand-in counter instead (see tests/test_s03_chunk.py).
    This function is what production code (the CLI) actually calls.
    """
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-m3")
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False))


@dataclass
class _Block:
    """One paragraph or one whole atomic list, tagged with the full
    heading_path active at that point in the document."""

    heading_path: tuple[str, ...]
    text: str
    is_list: bool


@dataclass
class _Section:
    heading_path: tuple[str, ...]
    blocks: list[_Block] = field(default_factory=list)

    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


def _element_text(el: ElementTree.Element) -> str:
    """All text within an element, including nested tags (e.g. a <p>
    containing an inline <ref> link) — .itertext() walks the whole subtree,
    not just el.text (which would miss anything after a child element)."""
    return " ".join(t.strip() for t in el.itertext() if t.strip())


def _parse_blocks(content_xml: str) -> list[_Block]:
    """Walks trafilatura's XML output in document order, tracking the
    active heading stack via each <head rend="hN"> element's level, and
    emits one _Block per <p> and one atomic _Block per genuine list (all
    its <item>s joined — this is the mechanism that makes "never split a
    list" possible downstream: a real list simply never exists as more
    than one indivisible unit in the first place).

    A <list> is only treated as atomic if its items are flat text. Confirmed
    real counter-case: trafilatura natively captured an entire podcast
    transcript — headings and all — inside a single <ul><li>, because the
    source HTML used an accordion/"read transcript" toggle widget built
    with <ul><li>, not because it's a numbered procedure. Protecting that
    as atomic produced a single 2,630-token chunk with no way to split it.
    A <list> whose items contain their own nested <head> is "unwrapped"
    instead: its headings and paragraphs are walked as ordinary document
    structure, exactly as if the <list> wrapper weren't there.

    Walks every element in the tree (.iter(), not just <main>'s direct
    children) since real content nests — e.g. a <list><item> containing a
    stray <head>, a real quirk found in real data — but only <head>/<p>/
    <list> elements at any depth are treated as content; anything else
    (the <doc> wrapper, <comments>) is ignored.
    """
    try:
        root = ElementTree.fromstring(content_xml)
    except ElementTree.ParseError:
        return []

    blocks: list[_Block] = []
    heading_stack: list[tuple[int, str]] = []

    def current_path() -> tuple[str, ...]:
        return tuple(text for _level, text in heading_stack)

    # A list is genuinely atomic only if it has no nested headings — see
    # the docstring above for the real case that makes this necessary.
    atomic_lists: set[int] = {
        id(lst) for lst in root.iter("list") if lst.find(".//head") is None
    }

    # Elements nested inside a GENUINELY ATOMIC list (confirmed real: one
    # real page has a list containing 32 nested <p> and 3 nested <head>
    # elements) must be skipped during the flat walk below — their text is
    # already captured once via the list's own _element_text() aggregation.
    # Non-atomic ("unwrapped") lists are deliberately excluded from this set:
    # their children need to be walked individually, not skipped.
    inside_a_list: set[int] = set()
    for lst in root.iter("list"):
        if id(lst) not in atomic_lists:
            continue
        for descendant in lst.iter():
            if descendant is not lst:
                inside_a_list.add(id(descendant))

    # iter() is document order (depth-first), which is exactly reading
    # order for this tree shape — headings and paragraphs are siblings
    # under <main>, so walking every element and filtering by tag name
    # reconstructs the right sequence without needing to special-case
    # <main>'s structure.
    for el in root.iter():
        if id(el) in inside_a_list:
            continue
        tag = el.tag
        if tag == "head":
            level = HEADING_LEVELS.get(el.get("rend", "h1"), 1)
            text = _element_text(el)
            if not text:
                continue
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
        elif tag == "p":
            text = _element_text(el)
            if text:
                blocks.append(_Block(heading_path=current_path(), text=text, is_list=False))
        elif tag == "list":
            if id(el) not in atomic_lists:
                continue  # unwrapped — its <head>/<p> children are walked individually instead
            items = [
                _element_text(item) for item in el.findall("item") if _element_text(item)
            ]
            if items:
                blocks.append(
                    _Block(heading_path=current_path(), text="\n".join(items), is_list=True)
                )

    return blocks


def _group_into_sections(blocks: list[_Block]) -> list[_Section]:
    """Groups consecutive blocks sharing the same heading_path into one
    section. Trafilatura's output commonly repeats the page title as both
    an "h2" and an "h1" heading at the very top with nothing in between
    (confirmed on real data) — that produces a heading_path change with
    zero blocks attached, which simply never becomes a section (sections
    need at least one block), so no empty chunk results from it.
    """
    sections: list[_Section] = []
    for block in blocks:
        if sections and sections[-1].heading_path == block.heading_path:
            sections[-1].blocks.append(block)
        else:
            sections.append(_Section(heading_path=block.heading_path, blocks=[block]))
    return sections


def _common_prefix(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
    prefix = []
    for x, y in zip(a, b):
        if x != y:
            break
        prefix.append(x)
    return tuple(prefix)


def _merge_small_sections(sections: list[_Section], count_tokens: TokenCounter) -> list[_Section]:
    """Merges a section below MERGE_BELOW_TOKENS forward into the next one,
    using their common heading ancestor as the merged path — deliberately
    conservative: only merges with the *next* section (document order),
    never reorders content, and never merges across a top-level heading
    change (a merged path shorter than 1 element means "no shared heading
    left", at which point merging would make heading_path meaningless
    rather than just less specific).
    """
    if not sections:
        return sections

    merged: list[_Section] = [sections[0]]
    for section in sections[1:]:
        prev = merged[-1]
        prev_tokens = count_tokens(prev.text())
        if prev_tokens < MERGE_BELOW_TOKENS:
            shared = _common_prefix(prev.heading_path, section.heading_path)
            if shared:
                prev.heading_path = shared
                prev.blocks.extend(section.blocks)
                continue
        merged.append(section)
    return merged


SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[.!?])\s+")


def _split_by_token_boundary(text: str, count_tokens: TokenCounter) -> list[str]:
    """Last-resort fallback: proportionally slices text to fit
    MAX_CHUNK_TOKENS, snapped to the nearest word boundary, verifying the
    actual result before accepting it (the character/token ratio is an
    estimate, not exact, so it shrinks further if the estimate overshot).

    Exists for the case even sentence-splitting can't handle: a run of
    text with no sentence-ending punctuation to split on at all (real
    transcript and PDF text can do this). This is not a real
    tokenizer-aware split — that would need the tokenizer's actual
    encode/decode, not just a token-count callable — but a bounded
    guarantee that no piece leaves this function over budget, which is
    the correctness property that actually matters here.
    """
    pieces: list[str] = []
    remaining = text.strip()

    while remaining:
        total_tokens = count_tokens(remaining)
        if total_tokens <= MAX_CHUNK_TOKENS:
            pieces.append(remaining)
            break

        ratio = MAX_CHUNK_TOKENS / total_tokens
        cut = max(1, int(len(remaining) * ratio))
        word_boundary = remaining.rfind(" ", 0, cut)
        if word_boundary > 0:
            cut = word_boundary

        piece = remaining[:cut].rstrip()
        while piece and count_tokens(piece) > MAX_CHUNK_TOKENS:
            shrink = piece.rfind(" ")
            if shrink <= 0:
                break
            piece = piece[:shrink].rstrip()

        if not piece:
            # No safe cut point found at all (one giant unbroken "word") —
            # accept the whole remainder rather than loop forever.
            pieces.append(remaining)
            break

        pieces.append(piece)
        remaining = remaining[len(piece):].lstrip()

    return pieces


def _split_long_paragraph(text: str, count_tokens: TokenCounter) -> list[str]:
    """Splits one oversized non-list block at sentence boundaries into
    pieces that fit MAX_CHUNK_TOKENS, with OVERLAP_TOKENS of trailing
    context carried into each next piece.

    Exists for a real, confirmed case: trafilatura sometimes merges an
    entire video transcript into a single <p> element (using internal line
    breaks rather than separate <p> tags for each spoken line), producing
    one block over 2,000 tokens that the block-level packing in
    _split_oversized_section has no opportunity to split, since it only
    ever splits *between* blocks. Unlike a list, a paragraph has no
    correctness reason to stay whole — splitting it at a sentence boundary
    doesn't corrupt a procedure the way splitting a list would.

    Falls through to _split_by_token_boundary for text with no sentence
    punctuation at all, or for any single sentence that's itself still
    oversized — this used to just be accepted as an oversized exception;
    now it's a real, bounded fallback instead.
    """
    sentences = [s for s in SENTENCE_BOUNDARY_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        return _split_by_token_boundary(text, count_tokens)

    pieces: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)

        if sentence_tokens > MAX_CHUNK_TOKENS:
            # A single sentence alone is oversized — flush what's pending,
            # token-boundary-split just this sentence, and move on.
            if current:
                pieces.append(" ".join(current))
                current, current_tokens = [], 0
            pieces.extend(_split_by_token_boundary(sentence, count_tokens))
            continue

        if current and current_tokens + sentence_tokens > MAX_CHUNK_TOKENS:
            pieces.append(" ".join(current))
            tail = current[-1]
            if count_tokens(tail) <= OVERLAP_TOKENS * 2:
                current = [tail]
                current_tokens = count_tokens(tail)
            else:
                current = []
                current_tokens = 0
        current.append(sentence)
        current_tokens += sentence_tokens
    if current:
        pieces.append(" ".join(current))
    return pieces


def _split_oversized_section(
    section: _Section, count_tokens: TokenCounter
) -> list[tuple[tuple[str, ...], str]]:
    """Splits one section into multiple (heading_path, text) pieces, all
    sharing the section's own heading_path, respecting two hard rules:
    a list block is never split internally, and pieces target
    MAX_CHUNK_TOKENS with OVERLAP_TOKENS worth of trailing context carried
    into the next piece.

    An atomic list block that alone exceeds MAX_CHUNK_TOKENS is kept whole
    anyway and allowed to exceed the budget — the numbered-list-safety
    guarantee is a hard correctness property (README's stage 03 DONE
    criterion), token budget is a soft target. A non-list block that alone
    exceeds the budget is NOT given the same pass — it goes through
    _split_long_paragraph instead. Confirmed real and necessary: 160 real
    Be Connected chunks (across 149 distinct pages) were stuck at
    500-2,446 tokens because a single oversized <p> (a whole transcript
    merged into one paragraph) had nothing to split it internally.
    """
    pieces: list[tuple[tuple[str, ...], str]] = []
    current: list[str] = []
    current_tokens = 0

    def flush() -> None:
        if current:
            pieces.append((section.heading_path, "\n\n".join(current)))

    for block in section.blocks:
        block_tokens = count_tokens(block.text)

        if not block.is_list and block_tokens > MAX_CHUNK_TOKENS:
            flush()
            current, current_tokens = [], 0
            for sub_piece in _split_long_paragraph(block.text, count_tokens):
                pieces.append((section.heading_path, sub_piece))
            continue

        if current and current_tokens + block_tokens > MAX_CHUNK_TOKENS:
            flush()
            # Carry trailing context forward for continuity across the
            # split — only for non-list content, so overlap can't
            # duplicate part of a list into the next chunk.
            tail = current[-1]
            if not block.is_list and count_tokens(tail) <= OVERLAP_TOKENS * 2:
                current = [tail]
                current_tokens = count_tokens(tail)
            else:
                current = []
                current_tokens = 0

        current.append(block.text)
        current_tokens += block_tokens

    flush()
    return pieces if pieces else [(section.heading_path, section.text())]


def _doc_chunk_id(doc_id: str, order_idx: int) -> str:
    return f"{doc_id}-chunk-{order_idx:03d}"


def chunk_doc(doc: ExtractedDoc, count_tokens: TokenCounter | None = None) -> list[Chunk]:
    """Chunks one ExtractedDoc. Falls back cleanly when content_xml is
    empty (a PDF, or the one known real page with no recoverable headings)
    by splitting `text` into paragraph-level blocks (on blank lines) and
    running those through the same section/splitting logic as any other
    doc — NOT by treating the whole doc as one block. Confirmed a real bug
    from the one-block version: the entire ~4000-word "Little Book of
    Scams" PDF became a single unsplit 3949-token chunk, nowhere near the
    300-500 token target, because a single block can't be split internally
    by _split_oversized_section — there was nothing to pack/break between.
    """
    count_tokens = count_tokens or get_default_token_counter()

    blocks = _parse_blocks(doc.content_xml) if doc.content_xml else []
    if not blocks:
        if not doc.text.strip():
            return []
        paragraphs = [p.strip() for p in doc.text.split("\n\n") if p.strip()]
        blocks = [_Block(heading_path=(), text=p, is_list=False) for p in paragraphs]

    sections = _group_into_sections(blocks)
    sections = _merge_small_sections(sections, count_tokens)

    chunks: list[Chunk] = []
    for section in sections:
        section_tokens = count_tokens(section.text())
        if section_tokens <= MAX_CHUNK_TOKENS:
            pieces = [(section.heading_path, section.text())]
        else:
            pieces = _split_oversized_section(section, count_tokens)

        for heading_path, text in pieces:
            if not text.strip():
                continue
            order_idx = len(chunks)
            chunks.append(Chunk(
                id=_doc_chunk_id(doc.doc_id, order_idx), doc_id=doc.doc_id, url=doc.url,
                domain=doc.domain, title=doc.title, lang=doc.lang, fetched_at=doc.fetched_at,
                heading_path=list(heading_path), text=text, token_count=count_tokens(text),
                order_idx=order_idx,
            ))
    return chunks


def chunk_docs(docs: list[ExtractedDoc], count_tokens: TokenCounter | None = None) -> list[Chunk]:
    count_tokens = count_tokens or get_default_token_counter()
    all_chunks: list[Chunk] = []
    for doc in docs:
        all_chunks.extend(chunk_doc(doc, count_tokens))
    return all_chunks
