"""Stage 01 — Source Ingestion.

Allowlist -> robots.txt/sitemap -> polite crawl -> raw HTML disk cache.

Design decisions made explicit here (see chat log / commit message for the
reasoning, since none of this is dictated word-for-word by README_rag.md):

- Discovery is domain-level (sitemap.xml, falling back to same-domain link
  following from the homepage), not a hand-maintained URL list. This
  matches the "Approved domain list" input the stage map documents.
- "Crawl the whole domain" is bounded by MAX_PAGES_PER_DOMAIN as a safety
  cap, not a hard scope restriction — filtering happens later. Hitting the
  cap is logged and recorded in the run summary, never silent.
- Idempotency (README stage 01 DONE: "a second run makes zero network
  calls") is implemented via a per-domain manifest.json cache. If it
  exists, ingest_domain() returns it without touching the network at all.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from pydantic import HttpUrl

from rag.schemas import ApprovedDomain, IngestRunSummary, PageRecord

logger = logging.getLogger("rag.ingest")

USER_AGENT = (
    "ConnectPlusBot/0.1 (+CW2 digital literacy platform prototype; "
    "contact: TODO-team-email@example.edu)"
)
REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
DEFAULT_TIMEOUT = 15.0
DEFAULT_DELAY_SECONDS = 1.0  # politeness floor; robots crawl-delay can raise this
MAX_PAGES_PER_DOMAIN = 500
CONSECUTIVE_FAILURE_LIMIT = 5  # abort the rest of a domain's crawl past this many fetch failures in a row


class DomainNotApprovedError(Exception):
    """Raised when ingest is asked to crawl a domain not in the allowlist.

    This must be raised before any network call is made — that's the
    enforcement point README_rag.md means by "enforced in code, at fetch
    time."
    """


class _JsonLogAdapter(logging.LoggerAdapter):
    """Attaches a run_id to every log line and renders as one JSON object
    per line, so a bad ingest run can be grepped by run_id across a huge
    log file without hand-parsing prose."""

    def process(self, msg, kwargs):
        extra = kwargs.setdefault("extra", {})
        extra["run_id"] = self.extra["run_id"]
        return msg, kwargs


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "run_id": getattr(record, "run_id", None),
            "event": record.getMessage(),
        }
        for key in ("domain", "url", "status", "cache_hit"):
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


class _LinkExtractor(HTMLParser):
    """Pulls same-scheme hrefs out of a page. Used only as the fallback
    discovery path when a domain has no usable sitemap."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                self.hrefs.append(value)


def load_approved_domains(path: Path) -> list[ApprovedDomain]:
    raw = json.loads(path.read_text())
    return [ApprovedDomain.model_validate(row) for row in raw]


def _check_allowed(domain: str, approved: list[ApprovedDomain]) -> None:
    if domain not in {a.domain for a in approved}:
        raise DomainNotApprovedError(
            f"{domain!r} is not in the approved_domains allowlist. "
            "A curator must add it before it can be crawled."
        )


def _cache_paths(cache_dir: Path, domain: str) -> dict[str, Path]:
    domain_dir = cache_dir / domain
    return {
        "domain_dir": domain_dir,
        "robots": domain_dir / "robots.txt",
        "sitemap": domain_dir / "sitemap.xml",
        "pages": domain_dir / "pages",
        "manifest": domain_dir / "manifest.json",
    }


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _get_robot_parser(
    domain: str, client: httpx.Client, paths: dict[str, Path], log: logging.LoggerAdapter
) -> RobotFileParser:
    robots_url = f"https://{domain}/robots.txt"
    parser = RobotFileParser()
    try:
        resp = client.get(robots_url, timeout=DEFAULT_TIMEOUT, headers=REQUEST_HEADERS)
        content = resp.text if resp.status_code == 200 else ""
    except httpx.RequestError:
        log.warning("robots_fetch_failed", extra={"domain": domain, "url": robots_url})
        content = ""
    paths["robots"].write_text(content)
    parser.parse(content.splitlines())
    parser.set_url(robots_url)
    return parser


def _discover_via_sitemap(
    domain: str,
    robots: RobotFileParser,
    client: httpx.Client,
    paths: dict[str, Path],
    log: logging.LoggerAdapter,
) -> list[str]:
    sitemap_urls = list(robots.site_maps() or [])
    if not sitemap_urls:
        sitemap_urls = [f"https://{domain}/sitemap.xml"]

    discovered: list[str] = []
    seen_sitemaps: set[str] = set()
    queue = list(sitemap_urls)

    while queue:
        sm_url = queue.pop(0)
        if sm_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sm_url)
        try:
            resp = client.get(sm_url, timeout=DEFAULT_TIMEOUT, headers=REQUEST_HEADERS)
            if resp.status_code != 200:
                continue
            paths["sitemap"].write_text(resp.text)
            root = ElementTree.fromstring(resp.content)
        except (httpx.RequestError, ElementTree.ParseError):
            log.warning("sitemap_unusable", extra={"domain": domain, "url": sm_url})
            continue

        tag = root.tag.lower()
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        if tag.endswith("sitemapindex"):
            queue.extend(loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text)
        else:
            discovered.extend(loc.text.strip() for loc in root.findall(".//sm:loc", ns) if loc.text)

    return discovered


def _extract_links(html: str, base_url: str, domain: str, log: logging.LoggerAdapter) -> list[str]:
    """Pulls same-domain hrefs out of a page's HTML.

    Two defensive layers, because stdlib HTMLParser assumes well-formed
    HTML and will raise on garbage input:
    1. The caller should already have checked Content-Type looks like
       HTML before calling this — see _discover_via_links.
    2. Even a text/html-labelled response can contain a byte sequence
       HTMLParser chokes on (seen in practice: a WAF/bot-check response
       served with an HTML content-type but non-HTML, sometimes
       binary-looking, body). That must never take down the whole
       ingest run over one page's links — we just get zero links from
       that page and move on.
    """
    extractor = _LinkExtractor()
    try:
        extractor.feed(html)
    except Exception:  # noqa: BLE001 — HTMLParser's failure modes aren't a fixed, documented set
        log.warning("link_extraction_failed", extra={"domain": domain, "url": base_url})
        return []

    links: list[str] = []
    for href in extractor.hrefs:
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != domain or parsed.scheme not in ("http", "https"):
            continue
        links.append(absolute.split("#")[0])
    return links


def _discover_via_links(
    domain: str,
    robots: RobotFileParser,
    client: httpx.Client,
    pages_dir: Path,
    max_pages: int,
    log: logging.LoggerAdapter,
) -> list[str]:
    """Breadth-first same-domain link crawl, used only when no sitemap
    yields anything. Deliberately simple: stdlib HTMLParser, no JS
    rendering, no external crawler framework — matches the stack table's
    "no crawler framework needed for a handful of domains."

    Fetches go through _fetch_page, the same disk-cache path the main
    ingest loop uses. That means a page found and fetched here is
    already cached by the time the main loop asks for it again —
    without this, every discovered page was being fetched twice
    (once here, once in the main loop), doubling the request count
    against a site we're specifically trying to be polite to.
    """
    start = f"https://{domain}/"
    seen = {start}
    queue = [start]
    discovered: list[str] = []

    while queue and len(discovered) < max_pages:
        url = queue.pop(0)
        if not robots.can_fetch(USER_AGENT, url):
            continue

        record, cache_hit = _fetch_page(url, domain, client, pages_dir, log)
        if record.status != 200:
            continue
        discovered.append(url)

        if record.content_type and "html" not in record.content_type.lower():
            continue
        for link in _extract_links(record.html, url, domain, log):
            if link not in seen:
                seen.add(link)
                queue.append(link)

        if not cache_hit:
            delay = robots.crawl_delay(USER_AGENT) or DEFAULT_DELAY_SECONDS
            time.sleep(float(delay))

    return discovered


def _is_text_content(content_type: str) -> bool:
    """Whether a Content-Type is safe to decode as text. Deliberately
    conservative allowlist rather than a "not obviously binary" denylist —
    a new binary type we haven't seen yet should fail safe (cached as raw
    bytes) rather than get corrupted through .text, which is exactly the
    bug this function exists to prevent.
    """
    ct = content_type.split(";")[0].strip().lower()
    return ct.startswith("text/") or ct in (
        "application/xml", "application/rss+xml", "application/xhtml+xml", "application/json",
    )


def _fetch_page(
    url: str,
    domain: str,
    client: httpx.Client,
    pages_dir: Path,
    log: logging.LoggerAdapter,
) -> tuple[PageRecord, bool]:
    """Returns (record, cache_hit). Cache is checked before any network call.

    Text and binary content are cached differently on purpose: httpx's
    `.text` decodes bytes using a detected/declared encoding, which is
    correct for HTML but silently corrupts anything binary (a PDF's bytes
    round-tripped through `.text` come back different from what the server
    sent — confirmed empirically, not assumed). Binary content — Scamwatch
    alone links 44 PDFs, 7 RSS feeds, 3 zips — is written to <hash>.bin as
    raw, untouched bytes. `PageRecord.html` stays "" for these; a future
    stage that wants the PDF text needs to read the .bin file itself with
    a real PDF library, not expect it pre-decoded into a text field.
    """
    key = _url_hash(url)
    html_path = pages_dir / f"{key}.html"
    bin_path = pages_dir / f"{key}.bin"
    meta_path = pages_dir / f"{key}.meta.json"

    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        is_text = _is_text_content(meta.get("content_type", ""))
        html = html_path.read_text() if is_text and html_path.exists() else ""
        record = PageRecord(
            url=HttpUrl(url), domain=domain, html=html,
            fetched_at=meta["fetched_at"], status=meta["status"],
            content_type=meta.get("content_type", ""),
        )
        return record, True

    content_type = ""
    is_text = True
    raw_bytes = b""
    html = ""
    try:
        resp = client.get(url, timeout=DEFAULT_TIMEOUT, headers=REQUEST_HEADERS)
        status = resp.status_code
        content_type = resp.headers.get("content-type", "")
        is_text = _is_text_content(content_type)
        if status == 200:
            if is_text:
                html = resp.text
            else:
                raw_bytes = resp.content
    except httpx.RequestError:
        log.warning("page_fetch_failed", extra={"domain": domain, "url": url})
        status = -1

    fetched_at = datetime.now(UTC)
    record = PageRecord(
        url=HttpUrl(url), domain=domain, html=html, fetched_at=fetched_at,
        status=status, content_type=content_type,
    )

    pages_dir.mkdir(parents=True, exist_ok=True)
    if is_text:
        html_path.write_text(html)
    else:
        bin_path.write_bytes(raw_bytes)
    meta_path.write_text(json.dumps({
        "fetched_at": fetched_at.isoformat(), "status": status, "content_type": content_type,
    }))
    log.info(
        "page_fetched",
        extra={"domain": domain, "url": url, "status": status, "cache_hit": False},
    )
    return record, False


def _rehydrate_page_record(
    entry: dict, pages_dir: Path, log: logging.LoggerAdapter
) -> PageRecord:
    """Reconstructs a full PageRecord from a manifest entry that doesn't
    carry the HTML itself — see the comment where manifest.json is written.
    Reads the body back from pages/<hash>.html for text content; binary
    content (PDFs etc.) stays as "" here too, same as on first fetch — the
    raw bytes live in pages/<hash>.bin for whoever needs them later.
    """
    key = _url_hash(entry["url"])
    content_type = entry.get("content_type", "")
    html = ""
    if _is_text_content(content_type):
        html_path = pages_dir / f"{key}.html"
        if html_path.exists():
            html = html_path.read_text()
        else:
            # Shouldn't happen in normal operation — the manifest is only
            # written after every page in it was fetched — but disk state can
            # be edited or partially deleted by hand, so fail soft, not loud.
            log.warning("cached_html_missing", extra={"domain": entry["domain"], "url": entry["url"]})
    return PageRecord(
        url=HttpUrl(entry["url"]), domain=entry["domain"], html=html,
        fetched_at=entry["fetched_at"], status=entry["status"],
        content_type=content_type,
    )


def load_pages_from_manifest(domain: str, cache_dir: Path) -> list[PageRecord]:
    """Public entry point for other stages (currently: stage 02, via the
    CLI's `extract` command) to load a domain's already-ingested pages
    without needing to know manifest.json's on-disk layout or that HTML
    gets rehydrated from a separate cache file. ingest_domain() itself
    doesn't use this — it has its own cache-hit path with the approved-domain
    check still in front of it; this is for read-only access after the fact.
    """
    paths = _cache_paths(cache_dir, domain)
    if not paths["manifest"].exists():
        raise FileNotFoundError(
            f"No manifest.json for {domain!r} at {paths['manifest']} — run ingest for it first"
        )
    log = _JsonLogAdapter(logger, {"run_id": str(uuid.uuid4())})
    manifest = json.loads(paths["manifest"].read_text())
    return [_rehydrate_page_record(p, paths["pages"], log) for p in manifest["pages"]]


def ingest_domain(
    domain: str,
    approved: list[ApprovedDomain],
    cache_dir: Path,
    client: httpx.Client | None = None,
    max_pages: int = MAX_PAGES_PER_DOMAIN,
    run_id: str | None = None,
) -> list[PageRecord]:
    """Crawl one domain, or return the cached manifest if this domain was
    already ingested. Raises DomainNotApprovedError before any network
    call if the domain isn't allowlisted.
    """
    _check_allowed(domain, approved)  # enforcement point — before any I/O

    run_id = run_id or str(uuid.uuid4())
    log = _JsonLogAdapter(logger, {"run_id": run_id})
    paths = _cache_paths(cache_dir, domain)
    paths["domain_dir"].mkdir(parents=True, exist_ok=True)

    if paths["manifest"].exists():
        log.info("manifest_cache_hit", extra={"domain": domain})
        cached = json.loads(paths["manifest"].read_text())
        return [_rehydrate_page_record(p, paths["pages"], log) for p in cached["pages"]]

    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    started_at = datetime.now(UTC)
    try:
        robots = _get_robot_parser(domain, client, paths, log)

        urls = _discover_via_sitemap(domain, robots, client, paths, log)
        if not urls:
            log.info("sitemap_empty_falling_back_to_links", extra={"domain": domain})
            urls = _discover_via_links(domain, robots, client, paths["pages"], max_pages, log)

        truncated = len(urls) > max_pages
        urls = urls[:max_pages]
        if truncated:
            log.warning("crawl_truncated", extra={"domain": domain})

        records: list[PageRecord] = []
        disallowed = 0
        failed = 0
        consecutive_failures = 0
        circuit_breaker_tripped = False
        for url in urls:
            if not robots.can_fetch(USER_AGENT, url):
                disallowed += 1
                log.info("robots_disallowed", extra={"domain": domain, "url": url})
                continue

            record, cache_hit = _fetch_page(url, domain, client, paths["pages"], log)
            records.append(record)

            if record.status != 200:
                failed += 1
                consecutive_failures += 1
            else:
                consecutive_failures = 0

            if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
                circuit_breaker_tripped = True
                log.warning(
                    "circuit_breaker_tripped",
                    extra={"domain": domain, "status": record.status},
                )
                break  # this domain looks blocked or down; don't burn the timeout N more times

            if not cache_hit:
                delay = robots.crawl_delay(USER_AGENT) or DEFAULT_DELAY_SECONDS
                time.sleep(float(delay))

        finished_at = datetime.now(UTC)
        summary = IngestRunSummary(
            domain=domain, started_at=started_at, finished_at=finished_at,
            pages_fetched=len(records) - failed, pages_failed=failed,
            pages_disallowed_by_robots=disallowed, truncated=truncated,
            circuit_breaker_tripped=circuit_breaker_tripped,
        )
        paths["manifest"].write_text(json.dumps({
            "summary": summary.model_dump(mode="json"),
            # Deliberately excludes "html": each page's HTML already lives in
            # pages/<hash>.html, written by _fetch_page. Storing it a second
            # time here made manifest.json balloon to the size of every
            # fetched page combined — hundreds of MB for a real domain,
            # large enough that some editors refuse to open it at all. This
            # file's job is to be a small, human-readable index, not a
            # second copy of the corpus.
            "pages": [r.model_dump(mode="json", exclude={"html"}) for r in records],
        }))
        log.info("domain_ingest_complete", extra={"domain": domain})
        return records
    finally:
        if owns_client:
            client.close()


def ingest(
    domains: list[str] | None,
    config_path: Path,
    cache_dir: Path,
    max_pages: int = MAX_PAGES_PER_DOMAIN,
    client: httpx.Client | None = None,
) -> dict[str, list[PageRecord]]:
    """Entry point for `python -m rag.main ingest [--domain X] [--max-pages N]`.

    A domain that isn't approved is logged and skipped — it does not abort
    ingestion for the other domains in the same run. `client` is injectable
    for tests, same pattern as ingest_domain — production code never passes it.
    """
    configure_json_logging()
    run_id = str(uuid.uuid4())
    log = _JsonLogAdapter(logger, {"run_id": run_id})
    approved = load_approved_domains(config_path)
    targets = domains or [a.domain for a in approved]

    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    results: dict[str, list[PageRecord]] = {}
    try:
        for domain in targets:
            try:
                results[domain] = ingest_domain(
                    domain, approved, cache_dir, client=client, max_pages=max_pages, run_id=run_id
                )
            except DomainNotApprovedError:
                log.error("domain_rejected", extra={"domain": domain})
    finally:
        if owns_client:
            client.close()
    return results
