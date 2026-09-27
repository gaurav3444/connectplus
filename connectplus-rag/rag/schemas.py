"""Frozen contracts for every stage boundary in connectplus-rag.

Changes here need team agreement - every stage downstream is built and
tested against these shapes via the fixtures/ directory. Do not add fields
silently; extend deliberately and update the matching fixture.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field, HttpUrl


class ApprovedDomain(BaseModel):
    """One row of the approved_domains allowlist.

    This mirrors the shape the client's `approved_domains` Supabase table
    will eventually have (see README_rag.md, "Adding an approved domain").
    Until that table exists, `rag/config/approved_domains.json` is the
    source of truth and this model validates it on load.
    """

    domain: str = Field(description="Bare hostname, e.g. 'scamwatch.gov.au'")
    added_by: str = Field(description="Who approved this domain (curator name)")
    approved_at: str = Field(description="ISO date the domain was approved")
    notes: str = Field(default="", description="Why this domain is trusted")


class PageRecord(BaseModel):
    """Stage 01 output: one fetched (or attempted) page.

    `status` is the HTTP status code when a response was received, or -1
    when the request failed before a response arrived (DNS failure,
    timeout, connection refused). `html` is empty in that case.
    This -1 convention is our addition on top of the README's
    {url, domain, html, fetched_at, status} contract - not a schema change,
    since `status` was left unspecified there.
    """

    url: HttpUrl
    domain: str
    html: str
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    status: int
    content_type: str = Field(
        default="",
        description=(
            "Response Content-Type, e.g. 'text/html; charset=utf-8'. Added on top of "
            "the README's original {url, domain, html, fetched_at, status} contract so "
            "stage 02 can tell a real HTML page apart from a PDF or a bot-check response "
            "labelled text/html but not actually HTML. Empty for cached records written "
            "before this field existed, and for network-level failures (status = -1)."
        ),
    )


class ExtractedDoc(BaseModel):
    """Stage 02 output: one cleaned document per successfully-extracted page.

    README's original contract is {doc_id, url, domain, title, lang,
    fetched_at, text}. `source_content_type` is our addition, same
    reasoning as PageRecord.content_type - downstream stages and any
    citation UI benefit from knowing "this came from a PDF" vs a web page.
    """

    doc_id: str = Field(description="Stable hash of the source URL - see _doc_id()")
    url: HttpUrl
    domain: str
    title: str
    lang: str = Field(description="ISO 639-1 code from langdetect, or 'unknown' if detection failed")
    fetched_at: datetime
    text: str
    content_xml: str = Field(
        default="",
        description=(
            "trafilatura's XML output for the same content - <head rend='h1'/'h2'/etc.> "
            "for headings, <p> for paragraphs, <list><item> for lists, in document order. "
            "Stage 03 derives heading_path from this, not from `text` or a markdown "
            "rendering: confirmed on real data that trafilatura's markdown *serializer* "
            "introduces real bugs (a heading glued onto adjacent content or a list item "
            "with no separating newline) that don't exist in its XML output, where "
            "headings and paragraphs are distinct elements with no ambiguity. Empty for "
            "PDFs: pypdf has no heading-level information to preserve, so stage 03's "
            "heading-based chunking falls back to token-only splitting for PDF-sourced docs."
        ),
    )
    source_content_type: str = Field(default="")


class ExtractionRunSummary(BaseModel):
    """Visibility into what stage 02 did with a batch of stage 01 pages -
    mirrors IngestRunSummary's philosophy: every skip has a counted,
    named reason, nothing just silently disappears.
    """

    total_input_pages: int
    extracted: int
    skipped_non_200_status: int
    skipped_unsupported_content_type: int
    skipped_empty_after_extraction: int
    deduplicated_exact_text_matches: int = Field(
        default=0,
        description=(
            "Docs dropped for having identical text to another doc already kept - "
            "confirmed real cause: Scamwatch's sitemap lists both http:// and https:// "
            "for many pages, fetched as separate URLs but serving identical content."
        ),
    )


class Chunk(BaseModel):
    """Stage 03 output - one retrievable unit. Matches README_rag.md's
    frozen contract: {id, doc_id, url, domain, title, lang, fetched_at,
    heading_path, text, token_count, order_idx}.

    `title`, `lang`, `fetched_at`, `url`, `domain` are denormalized from
    the parent ExtractedDoc onto every chunk deliberately - a chunk needs
    to be citable and provenance-traceable on its own, without a join back
    to its parent doc, since that's what stage 06 retrieves and stage 08
    verifies against.
    """

    id: str = Field(description="f'{doc_id}-chunk-{order_idx:03d}' - deterministic, stable across re-runs")
    doc_id: str
    url: HttpUrl
    domain: str
    title: str
    lang: str
    fetched_at: datetime
    heading_path: list[str] = Field(
        default_factory=list,
        description=(
            "Breadcrumb from the page's top-level heading down to the most specific "
            "heading covering this chunk's content. Empty when the source doc has no "
            "recoverable heading structure (confirmed real case: PDFs, and one real "
            "Scamwatch page where trafilatura excluded all its headings) - an empty "
            "heading_path is a valid, expected value, not an error."
        ),
    )
    text: str
    token_count: int = Field(
        description=(
            "Counted with BGE-m3's own tokenizer (see stage 03's get_default_token_counter) - "
            "matches the model these chunks actually get embedded with in stage 04, rather than "
            "an approximation from an unrelated model's vocabulary."
        )
    )
    order_idx: int = Field(description="0-based position within the parent doc's chunk sequence")


class IngestRunSummary(BaseModel):
    """One ingest run's outcome for a single domain - written to manifest.json
    and used to decide whether a re-run can skip the network entirely."""

    domain: str
    started_at: datetime
    finished_at: datetime
    pages_fetched: int
    pages_failed: int
    pages_disallowed_by_robots: int
    truncated: bool = Field(
        description="True if the crawl hit max_pages before exhausting discovered URLs"
    )
    circuit_breaker_tripped: bool = Field(
        default=False,
        description=(
            "True if the crawl stopped early after too many consecutive fetch failures - "
            "usually means the domain is blocking or rate-limiting this crawler, not that "
            "the pages themselves don't exist. Worth a manual look, not a re-run."
        ),
    )


class EmbeddedChunk(BaseModel):
    """Stage 04 output: a Chunk plus its dense embedding vector, ready to
    upsert into Supabase Postgres. Model name and dimension travel with
    every row (not just recorded once somewhere) - README's own reasoning:
    "store model name and dimensions alongside the vectors... you need to
    be able to tell" if the embedding model ever changes, since that
    silently invalidates the whole index and a per-row GROUP BY is how
    you'd notice a partial re-index with a different model.
    """

    id: str
    doc_id: str
    url: HttpUrl
    domain: str
    title: str
    lang: str
    fetched_at: datetime
    heading_path: list[str] = Field(default_factory=list)
    text: str
    token_count: int
    order_idx: int
    embedding: list[float]
    embedding_model: str
    embedding_dim: int


class IndexRunSummary(BaseModel):
    """What stage 04 actually did with a batch of chunks - same
    counted-reason philosophy as the other stages' run summaries."""

    total_chunks: int
    embedded: int
    upserted: int
    embedding_model: str
    embedding_dim: int
    batches: int


class Retrieved(Chunk):
    """Stage 05 output (README_rag.md's own internal numbering - the
    unified whole-project stage map calls this "stage 06", Hybrid
    Retrieval). Literally README's contract: "Chunk + {score, method}".
    Subclasses Chunk directly rather than repeating every field, since a
    Retrieved chunk carries full provenance forward - stage 08 (guardrails)
    needs the same url/domain/heading_path a plain Chunk has, plus these
    two additional fields.
    """

    score: float = Field(
        description=(
            "Final ranking score. With reranking: bge-reranker-v2-m3's own [0,1] relevance "
            "probability, used directly - this model's default CrossEncoder activation "
            "already calibrates it, so it is NOT re-sigmoided (a real, confirmed bug did "
            "this once: re-applying sigmoid to an already-[0,1] value collapsed every score "
            "toward 0.5 regardless of true relevance). Without reranking: the chunk's own "
            "vector cosine similarity or keyword ts_rank - whichever method found it (vector "
            "preferred when both did). IMPORTANT: without reranking, `score` is only "
            "safely comparable *within* the same `method` - a vector score and a keyword "
            "score are on different, incompatible scales. For any cross-query or "
            "threshold-style decision (e.g. 'is this good enough to answer with'), use "
            "the separate `confidence` value retrieve() returns, not any individual score."
        )
    )
    method: str = Field(
        description=(
            "'vector' or 'keyword' if this chunk was found by only one search method, "
            "'fused' if both methods surfaced it (independently confirmed relevance, not "
            "just a single method's opinion)."
        )
    )


class UnderstoodQuery(BaseModel):
    """Stage 06 output (this repo's file numbering - the unified whole-
    project stage map calls this "stage 05", Query Understanding, and
    calls this repo's s05_retrieve "stage 06"; see README's mapping table).

    The stage map's card: IN {query, lang?} -> OUT {original, lang,
    rewritten, expansions[]}.
    """

    original: str = Field(description="The senior's question exactly as typed, unmodified")
    lang: str = Field(
        description=(
            "ISO 639-1 code (langdetect's, so 'zh-cn' not 'zh'), or 'unknown'. Carried "
            "forward separately from `rewritten` on purpose: retrieval wants English, but "
            "the generator downstream has to ANSWER in the language the senior asked in. "
            "Losing this field is how a Mandarin speaker gets an English answer."
        )
    )
    rewritten: str = Field(
        description=(
            "The retrievable form of the question, ALWAYS in English. Two reasons it is "
            "English rather than the original language, both real: (1) keyword search runs "
            "against an 'english' tsvector (rag/config/schema.sql), and a Mandarin string "
            "produces an empty tsquery that matches nothing - this is the value passed to "
            "retrieve(keyword_query=...); (2) the approved corpus is itself almost entirely "
            "English. Also de-vagued, not just translated: the stage map's own example is "
            "'my phone keeps asking for a code' -> 'two-factor authentication'. Falls back "
            "to `original` verbatim when the LLM is unavailable or returns something "
            "unparseable - degraded retrieval beats no retrieval."
        )
    )
    expansions: list[str] = Field(
        default_factory=list,
        description=(
            "A few extra English search terms (near-synonyms, the official name for a "
            "colloquial one). Appended to the KEYWORD query only, never used for the vector "
            "query - extra terms help lexical recall but dilute a dense embedding, which is "
            "why these are a separate field instead of being pasted into `rewritten`."
        ),
    )
    prompt_version: str = Field(
        default="",
        description=(
            "Which prompt produced this rewrite. The stage map's stage 09 card requires "
            "prompt version in the trace log: 'a bad answer has to be traceable'. Empty when "
            "the fallback path produced this object without calling an LLM at all."
        ),
    )


class Citation(BaseModel):
    """One `[n]` marker found in a draft answer, resolved against the chunks
    that were actually retrieved for it."""

    n: int = Field(description="The number inside the marker, e.g. 2 for '[2]'")
    url: str = Field(default="", description="The cited chunk's URL, or '' if the marker resolved to nothing")
    title: str = Field(default="")
    domain: str = Field(default="")
    resolved: bool = Field(
        description=(
            "True only when the marker pointed at a real supplied chunk AND that chunk's "
            "domain is on the approved list. A marker naming a chunk index that was never "
            "supplied is the shape an invented citation takes."
        )
    )


class Verdict(BaseModel):
    """Stage 07 output (this repo's file numbering - the unified whole-project
    stage map calls this "stage 08", Guardrails + Citation Check).

    Matches the outer README's frozen contract: {passed, reason,
    grounded_score, citations, confidence, chunk_ids}.

    A failing verdict means the answer is DROPPED, not patched. What the
    senior gets instead is "I don't have trusted information on that" plus a
    mentor offer. In a scam-and-safety domain a confident wrong answer about
    myGov is real harm, not a quality bug.
    """

    passed: bool
    reason: str | None = Field(
        default=None,
        description=(
            "None when passed. Otherwise the FIRST check that failed, in this fixed "
            "order: 'low_confidence' (there was never good enough source material), "
            "'unsafe' (the answer tells the senior to disclose a credential), "
            "'bad_citation' (a marker resolves to nothing, or off the approved list), "
            "'ungrounded' (a claim is not supported by the supplied chunks). Order is "
            "harm-first, not cost-first: which failure the user is told about matters "
            "more than which was cheapest to detect."
        ),
    )
    grounded_score: float = Field(
        default=0.0,
        description=(
            "Lowest per-sentence entailment across the answer's substantive sentences - "
            "the weakest claim, not the average. An average lets one invented step hide "
            "behind four well-supported ones, and 'one invented step is caught' is this "
            "stage's own acceptance criterion. 0.0 when grounding was not run."
        ),
    )
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(description="Passed through from stage 05, unmodified")
    chunk_ids: list[str] = Field(
        default_factory=list,
        description="Ids of the chunks this answer was checked against - the audit trail.",
    )
