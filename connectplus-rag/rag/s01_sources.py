"""Stage 01 add-on: sources that need special fetch handling.

`s01_ingest.py` (the original sitemap/link crawler) is unchanged and still
handles Be Connected and Scamwatch. This module adds two strategies, picked
per domain in `rag/config/source_strategies.json`:

- "live_scoped" (my.gov.au): server-rendered, so a normal honest crawl
  works, but the same page is linked as `/en/x`, `/content/mygov/en/x.html`
  and with `:443`, and the host also serves the sign-in app and a large,
  mostly off-topic "browse government services" section. So: normalise
  URLs before queueing, and only crawl include_paths minus exclude_paths.

- "wayback" (esafety.gov.au): the live site blocks automated clients (see
  domain_decisions.md). We don't evade that. We read the Internet
  Archive's public copies through its documented APIs instead: the CDX API
  lists captured URLs, and `web/<ts>id_/<url>` returns a capture's raw
  original HTML (no Wayback toolbar or rewritten links).

A domain with no entry in source_strategies.json (or strategy "live") goes
straight to the original `s01_ingest.ingest_domain`.

Output uses exactly the cache layout `s01_ingest` writes (manifest.json
without HTML, pages/<hash>.html or .bin, pages/<hash>.meta.json with
content_type), so `load_pages_from_manifest` and stages 02-05 read these
domains with no changes.

Strategy config deliberately lives outside approved_domains.json:
ApprovedDomain mirrors the future Supabase allowlist table, and "how we
fetch" is an ingest detail, not an allowlist fact.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import Counter, deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from pydantic import BaseModel, Field, HttpUrl

from rag import s01_ingest
from rag.s01_ingest import (
    CONSECUTIVE_FAILURE_LIMIT,
    MAX_PAGES_PER_DOMAIN,
    REQUEST_HEADERS,
    USER_AGENT,
    _cache_paths,
    _is_text_content,
    _JsonLogAdapter,
    _LinkExtractor,
    _rehydrate_page_record,
    _url_hash,
    configure_json_logging,
    load_approved_domains,
    logger,
)
from rag.schemas import IngestRunSummary, PageRecord

DEFAULT_STRATEGIES_PATH = Path(__file__).parent / "config" / "source_strategies.json"
LIVE_TIMEOUT = 20.0
ARCHIVE_TIMEOUT = 60.0  # the archive is much slower than a live site
ARCHIVE_MAX_RETRIES = 4
CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK = "https://web.archive.org/web"
CDX_PAGE_SIZE = 5000
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_SNAPSHOT_TS = re.compile(r"/web/(\d{14})id_/")

Sleep = Callable[[float], None]


# ===========================================================================
# Config
# ===========================================================================

class SourceStrategy(BaseModel):
    domain: str = Field(description="Must match an approved_domains.json entry")
    strategy: Literal["live", "live_scoped", "wayback"] = "live"
    host: str = Field(default="", description="Host pages are served from; defaults to domain")
    start_urls: list[str] = Field(default_factory=list)
    include_paths: list[str] = Field(default_factory=list, description="Empty = whole host")
    exclude_paths: list[str] = Field(default_factory=list)
    url_normaliser: Literal["none", "aem_mygov"] = "none"
    archive_from: str = Field(default="", description="wayback only: earliest capture date, YYYYMMDD")
    max_pages: int = MAX_PAGES_PER_DOMAIN
    delay_seconds: float = 1.0
    max_consecutive_failures: int = CONSECUTIVE_FAILURE_LIMIT
    exclude_url_patterns: list[str] = Field(
        default_factory=list,
        description="Regexes; matching pages stay cached but are skipped by `extract` (any strategy)",
    )
    notes: str = ""

    @property
    def effective_host(self) -> str:
        return self.host or self.domain


def load_strategies(path: Path = DEFAULT_STRATEGIES_PATH) -> dict[str, SourceStrategy]:
    if not path.exists():
        return {}
    return {s.domain: s for s in (SourceStrategy.model_validate(r) for r in json.loads(path.read_text()))}


def filter_pages_for_extraction(
    domain: str, pages: list[PageRecord], strategies_path: Path = DEFAULT_STRATEGIES_PATH,
) -> tuple[list[PageRecord], int]:
    """Drops pages matching the domain's exclude_url_patterns before stage 02.

    Works for every strategy, including plain "live" domains crawled by the
    original s01_ingest (Scamwatch, Be Connected), and needs no re-crawl:
    the pages stay in the cache, they just never become docs. Confirmed real
    case: 179 Scamwatch docs were faceted listing pages
    (browse-news-and-alerts?f[0]=...) — "24 results, showing 1 to 10" plus
    snippets of other alerts — and one took a top-5 retrieval slot."""
    strategy = load_strategies(strategies_path).get(domain)
    if strategy is None or not strategy.exclude_url_patterns:
        return pages, 0
    patterns = [re.compile(p) for p in strategy.exclude_url_patterns]
    kept = [p for p in pages if not any(rx.search(str(p.url)) for rx in patterns)]
    return kept, len(pages) - len(kept)


# ===========================================================================
# URL rules
# ===========================================================================

def normalise_url(url: str, strategy: SourceStrategy) -> str | None:
    """Canonical URL used for dedup, cache keys and PageRecord.url.
    Returns None for off-host or non-http(s) links.

    Query strings and fragments are dropped for these sources: on myGov
    they're tracking/search params, and in the eSafety archive listing
    they're mostly faceted-search pages (the same junk Scamwatch's
    `?f[0]=` pages turned out to be in stage 02).
    """
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    if host != strategy.effective_host.lower():
        return None
    path = parts.path or "/"
    if strategy.url_normaliser == "aem_mygov":
        if path.startswith("/content/mygov/"):
            path = path[len("/content/mygov"):]
        if path.endswith(".html"):
            path = path[: -len(".html")]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit(("https", host, path, "", ""))


def _prefix_match(path: str, prefix: str) -> bool:
    """Segment-aware: '/en/about' matches '/en/about' and '/en/about/x',
    not '/en/aboutface'."""
    prefix = prefix.rstrip("/") or "/"
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")


def path_in_scope(url: str, strategy: SourceStrategy) -> bool:
    path = urlsplit(url).path or "/"
    if any(_prefix_match(path, p) for p in strategy.exclude_paths):
        return False
    return not strategy.include_paths or any(_prefix_match(path, p) for p in strategy.include_paths)


def _crawl_order(url: str) -> tuple[int, str]:
    """Shallow pages first: if max_pages truncates, we lose deep leaf
    pages rather than section landing pages."""
    return (urlsplit(url).path.count("/"), url)


def _parse_robots(content: str, robots_url: str) -> RobotFileParser:
    parser = RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(content.splitlines())
    return parser


# ===========================================================================
# Cache helpers — same on-disk format as s01_ingest._fetch_page
# ===========================================================================

def _cached_record(url: str, domain: str, pages_dir: Path, log: logging.LoggerAdapter) -> PageRecord | None:
    """Per-page cache hit, so an interrupted run resumes instead of refetching."""
    meta_path = pages_dir / f"{_url_hash(url)}.meta.json"
    if not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    return _rehydrate_page_record({"url": url, "domain": domain, **meta}, pages_dir, log)


def _store(
    record: PageRecord, raw_bytes: bytes, pages_dir: Path, extra_meta: dict[str, Any] | None = None
) -> None:
    pages_dir.mkdir(parents=True, exist_ok=True)
    key = _url_hash(str(record.url))
    if _is_text_content(record.content_type):
        (pages_dir / f"{key}.html").write_text(record.html)
    else:
        (pages_dir / f"{key}.bin").write_bytes(raw_bytes)
    meta = {"fetched_at": record.fetched_at.isoformat(), "status": record.status,
            "content_type": record.content_type, **(extra_meta or {})}
    (pages_dir / f"{key}.meta.json").write_text(json.dumps(meta))


def _write_manifest(
    paths: dict[str, Path], *, domain: str, started_at: datetime, records: list[PageRecord],
    disallowed: int, truncated: bool, tripped: bool, source: dict[str, Any],
) -> None:
    failed = sum(1 for r in records if r.status != 200)
    summary = IngestRunSummary(
        domain=domain, started_at=started_at, finished_at=datetime.now(UTC),
        pages_fetched=len(records) - failed, pages_failed=failed,
        pages_disallowed_by_robots=disallowed, truncated=truncated,
        circuit_breaker_tripped=tripped,
    )
    paths["manifest"].write_text(json.dumps({
        "summary": summary.model_dump(mode="json"),
        # Additive provenance key; load_pages_from_manifest only reads "pages".
        "source": source,
        # Same as s01_ingest: HTML lives in pages/<hash>.html, not here.
        "pages": [r.model_dump(mode="json", exclude={"html"}) for r in records],
    }))


def _load_cached_manifest(paths: dict[str, Path], log: logging.LoggerAdapter) -> list[PageRecord] | None:
    if not paths["manifest"].exists():
        return None
    cached = json.loads(paths["manifest"].read_text())
    return [_rehydrate_page_record(p, paths["pages"], log) for p in cached["pages"]]


# ===========================================================================
# Strategy: live_scoped (my.gov.au)
# ===========================================================================

def _live_get(client: httpx.Client, url: str) -> httpx.Response | None:
    try:
        return client.get(url, timeout=LIVE_TIMEOUT, headers=REQUEST_HEADERS)
    except httpx.RequestError:
        return None


def _sitemap_urls(client: httpx.Client, starts: list[str], paths: dict[str, Path] | None,
                  log: logging.LoggerAdapter, domain: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    queue = list(starts)
    while queue and len(seen) < 50:  # sitemap-index safety cap
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        resp = _live_get(client, sm)
        if resp is None or resp.status_code != 200:
            continue
        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError:
            log.warning("sitemap_unusable", extra={"domain": domain, "url": sm})
            continue
        if paths is not None and not paths["sitemap"].exists():
            paths["sitemap"].write_text(resp.text)
        locs = [el.text.strip() for el in root.findall(".//sm:loc", SITEMAP_NS) if el.text]
        (queue if root.tag.lower().endswith("sitemapindex") else found).extend(locs)
    return found


def ingest_live_scoped(
    strategy: SourceStrategy, cache_dir: Path, client: httpx.Client, max_pages: int,
    run_id: str | None = None, sleep: Sleep = time.sleep,
) -> list[PageRecord]:
    """Honest live crawl (same User-Agent, robots.txt, crawl-delay, cache and
    circuit breaker as s01_ingest), with normalisation and path scoping.
    Sitemap URLs and links found on fetched pages feed one queue, so it
    works whether or not the site publishes a usable sitemap."""
    domain, host = strategy.domain, strategy.effective_host
    log = _JsonLogAdapter(logger, {"run_id": run_id or str(uuid.uuid4())})
    paths = _cache_paths(cache_dir, domain)
    paths["domain_dir"].mkdir(parents=True, exist_ok=True)
    cached = _load_cached_manifest(paths, log)
    if cached is not None:
        log.info("manifest_cache_hit", extra={"domain": domain})
        return cached

    started_at = datetime.now(UTC)
    robots_url = f"https://{host}/robots.txt"
    resp = _live_get(client, robots_url)
    robots_txt = resp.text if resp is not None and resp.status_code == 200 else ""
    paths["robots"].write_text(robots_txt)
    robots = _parse_robots(robots_txt, robots_url)
    delay = float(robots.crawl_delay(USER_AGENT) or strategy.delay_seconds)

    sitemap_starts = list(robots.site_maps() or []) or [f"https://{host}/sitemap.xml"]
    queued: set[str] = set()
    initial: list[str] = []
    for raw in strategy.start_urls + _sitemap_urls(client, sitemap_starts, paths, log, domain):
        n = normalise_url(raw, strategy)
        if n and n not in queued and path_in_scope(n, strategy):
            queued.add(n)
            initial.append(n)
    queue = deque(sorted(initial, key=_crawl_order))

    records: list[PageRecord] = []
    disallowed = consecutive_failures = 0
    tripped = False
    while queue and len(records) < max_pages:
        url = queue.popleft()
        if not robots.can_fetch(USER_AGENT, url):
            disallowed += 1
            log.info("robots_disallowed", extra={"domain": domain, "url": url})
            continue

        record = _cached_record(url, domain, paths["pages"], log)
        if record is None:
            resp = _live_get(client, url)
            sleep(delay)
            raw_bytes = b""
            if resp is None:
                record = PageRecord(url=HttpUrl(url), domain=domain, html="", status=-1)
            else:
                if resp.status_code == 200:
                    final = normalise_url(str(resp.url), strategy)
                    if final is None or not path_in_scope(final, strategy):
                        # e.g. a help link that bounces into the sign-in app
                        log.info("redirected_out_of_scope", extra={"domain": domain, "url": url})
                        continue
                ct = resp.headers.get("content-type", "")
                is_text = _is_text_content(ct)
                ok = resp.status_code == 200
                raw_bytes = resp.content if ok and not is_text else b""
                record = PageRecord(url=HttpUrl(url), domain=domain, html=resp.text if ok and is_text else "",
                                    status=resp.status_code, content_type=ct)
            _store(record, raw_bytes, paths["pages"])
            log.info("page_fetched", extra={"domain": domain, "url": url, "status": record.status})
        records.append(record)

        consecutive_failures = 0 if record.status == 200 else consecutive_failures + 1
        if consecutive_failures >= strategy.max_consecutive_failures:
            tripped = True
            log.warning("circuit_breaker_tripped", extra={"domain": domain, "status": record.status})
            break

        if record.html and "html" in record.content_type.lower():
            extractor = _LinkExtractor()
            try:
                extractor.feed(record.html)
            except Exception:  # noqa: BLE001 — same defensive stance as s01_ingest._extract_links
                log.warning("link_extraction_failed", extra={"domain": domain, "url": url})
            for href in extractor.hrefs:
                n = normalise_url(urljoin(url, href), strategy)
                if n and n not in queued and path_in_scope(n, strategy):
                    queued.add(n)
                    queue.append(n)

    _write_manifest(
        paths, domain=domain, started_at=started_at, records=records, disallowed=disallowed,
        truncated=bool(queue), tripped=tripped,
        source={"strategy": "live_scoped", "host": host,
                "include_paths": strategy.include_paths, "exclude_paths": strategy.exclude_paths},
    )
    log.info("domain_ingest_complete", extra={"domain": domain})
    return records


# ===========================================================================
# Strategy: wayback (esafety.gov.au)
# ===========================================================================

def _archive_get(
    client: httpx.Client, url: str, params: list[tuple[str, str | int | float | bool | None]] | None,
    sleep: Sleep, log: logging.LoggerAdapter, domain: str,
) -> httpx.Response | None:
    """The archive rate-limits with 429/503: back off politely rather than
    hammer it. Returns None only after every retry failed."""
    for attempt in range(ARCHIVE_MAX_RETRIES):
        try:
            resp = client.get(url, params=params, timeout=ARCHIVE_TIMEOUT,
                              headers=REQUEST_HEADERS, follow_redirects=True)
        except httpx.RequestError:
            resp = None
        if resp is not None and resp.status_code not in (429, 502, 503, 504):
            return resp
        wait = 5.0 * (2 ** attempt)
        if resp is not None and resp.headers.get("retry-after", "").isdigit():
            wait = max(wait, float(resp.headers["retry-after"]))
        log.warning("archive_backoff", extra={"domain": domain, "url": url})
        sleep(wait)
    return None


def list_archived_urls(strategy: SourceStrategy, client: httpx.Client, sleep: Sleep,
                       log: logging.LoggerAdapter) -> list[str]:
    """Every URL under the host captured since archive_from, HTML + HTTP 200
    captures only, one row per URL (collapse=urlkey)."""
    params: list[tuple[str, str | int | float | bool | None]] = [
        ("url", f"{strategy.effective_host}/*"), ("output", "json"), ("fl", "original"),
        ("filter", "statuscode:200"), ("filter", "mimetype:text/html"),
        ("collapse", "urlkey"), ("limit", str(CDX_PAGE_SIZE)), ("showResumeKey", "true"),
    ]
    if strategy.archive_from:
        params.append(("from", strategy.archive_from))

    urls: list[str] = []
    resume_key = ""
    for _ in range(200):  # hard stop far beyond any real need
        page = params + ([("resumeKey", resume_key)] if resume_key else [])
        resp = _archive_get(client, CDX_ENDPOINT, page, sleep, log, strategy.domain)
        if resp is None or resp.status_code != 200 or not resp.text.strip():
            break
        rows = resp.json()
        resume_key = ""
        if len(rows) >= 2 and rows[-2] == []:  # layout: [header, rows..., [], [resumeKey]]
            resume_key = rows[-1][0]
            rows = rows[:-2]
        urls.extend(r[0] for r in rows[1:] if r)
        if not resume_key:
            break
        sleep(strategy.delay_seconds)
    return urls


def _archive_robots(
    strategy: SourceStrategy, client: httpx.Client, now_ts: str,
    paths: dict[str, Path] | None, sleep: Sleep, log: logging.LoggerAdapter,
) -> RobotFileParser:
    """Live robots.txt first (it loaded fine even when pages were blocked),
    archived copy as fallback. We follow eSafety's stated rules either way."""
    robots_url = f"https://{strategy.effective_host}/robots.txt"
    content = ""
    resp = _live_get(client, robots_url)
    if resp is not None and resp.status_code == 200:
        content = resp.text
    if not content:
        archived_url = f"{WAYBACK}/{now_ts}id_/{robots_url}"
        archived = _archive_get(client, archived_url, None, sleep, log, strategy.domain)
        if archived is not None and archived.status_code == 200:
            content = archived.text
    if not content:
        log.warning("robots_unavailable_allowing_all", extra={"domain": strategy.domain, "url": robots_url})
    if paths is not None:
        paths["robots"].write_text(content)
    return _parse_robots(content, robots_url)


def ingest_wayback(
    strategy: SourceStrategy, cache_dir: Path, client: httpx.Client, max_pages: int,
    run_id: str | None = None, sleep: Sleep = time.sleep, now: datetime | None = None,
) -> list[PageRecord]:
    """PageRecord.url keeps the ORIGINAL esafety.gov.au URL (citations point
    at eSafety, not archive.org). fetched_at is the SNAPSHOT date, so the
    corpus is honest about how old each page is. The archive URL and
    snapshot timestamp are kept in each page's .meta.json."""
    domain = strategy.domain
    log = _JsonLogAdapter(logger, {"run_id": run_id or str(uuid.uuid4())})
    paths = _cache_paths(cache_dir, domain)
    paths["domain_dir"].mkdir(parents=True, exist_ok=True)
    cached = _load_cached_manifest(paths, log)
    if cached is not None:
        log.info("manifest_cache_hit", extra={"domain": domain})
        return cached

    started_at = datetime.now(UTC)
    now_ts = (now or started_at).strftime("%Y%m%d%H%M%S")
    robots = _archive_robots(strategy, client, now_ts, paths, sleep, log)

    listed = list_archived_urls(strategy, client, sleep, log)
    candidates: set[str] = set()
    disallowed = 0
    for u in listed:
        n = normalise_url(u, strategy)
        if not n or n in candidates or not path_in_scope(n, strategy):
            continue
        if not robots.can_fetch(USER_AGENT, n):
            disallowed += 1
            continue
        candidates.add(n)
    ordered = sorted(candidates, key=_crawl_order)
    truncated = len(ordered) > max_pages
    ordered = ordered[:max_pages]
    log.info("archive_candidates_ready", extra={"domain": domain, "status": len(ordered)})

    records: list[PageRecord] = []
    consecutive_failures = 0
    tripped = False
    for url in ordered:
        record = _cached_record(url, domain, paths["pages"], log)
        if record is None:
            archive_url = f"{WAYBACK}/{now_ts}id_/{url}"  # redirects to the capture closest to now
            resp = _archive_get(client, archive_url, None, sleep, log, domain)
            sleep(strategy.delay_seconds)
            raw_bytes = b""
            snapshot_ts = ""
            if resp is None:
                record = PageRecord(url=HttpUrl(url), domain=domain, html="", status=-1)
            else:
                match = _SNAPSHOT_TS.search(str(resp.url))
                snapshot_ts = match.group(1) if match else ""
                ok = resp.status_code == 200
                ct = resp.headers.get("content-type", "") or ("text/html" if ok else "")
                is_text = _is_text_content(ct)
                raw_bytes = resp.content if ok and not is_text else b""
                fetched_at = (datetime.strptime(snapshot_ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
                              if snapshot_ts else datetime.now(UTC))
                record = PageRecord(url=HttpUrl(url), domain=domain, html=resp.text if ok and is_text else "",
                                    fetched_at=fetched_at, status=resp.status_code, content_type=ct)
            _store(record, raw_bytes, paths["pages"], {
                "source": "wayback", "snapshot_timestamp": snapshot_ts,
                "archive_url": str(resp.url) if resp is not None else archive_url,
            })
            log.info("page_fetched", extra={"domain": domain, "url": url, "status": record.status})
        records.append(record)

        consecutive_failures = 0 if record.status == 200 else consecutive_failures + 1
        if consecutive_failures >= strategy.max_consecutive_failures:
            tripped = True
            log.warning("circuit_breaker_tripped", extra={"domain": domain, "status": record.status})
            break

    _write_manifest(
        paths, domain=domain, started_at=started_at, records=records, disallowed=disallowed,
        truncated=truncated, tripped=tripped,
        source={"strategy": "wayback", "host": strategy.effective_host,
                "archive_from": strategy.archive_from, "urls_listed_by_archive": len(listed)},
    )
    log.info("domain_ingest_complete", extra={"domain": domain})
    return records


# ===========================================================================
# Plan — count what a run WOULD fetch, without fetching or caching anything
# ===========================================================================

class PlanReport(BaseModel):
    """Answers "how big is this source really?" before spending a long run.
    For eSafety this costs a handful of archive listing requests, not 500+
    page downloads."""

    domain: str
    strategy: str
    discovered: int = 0
    unique_after_normalising: int = 0
    in_scope: int = 0
    disallowed_by_robots: int = 0
    max_pages: int = 0
    in_scope_by_section: dict[str, int] = Field(default_factory=dict)
    out_of_scope_by_section: dict[str, int] = Field(default_factory=dict)
    note: str = ""

    @property
    def would_truncate(self) -> bool:
        return self.in_scope > self.max_pages


def _section(url: str) -> str:
    segs = [s for s in urlsplit(url).path.split("/") if s]
    if not segs:
        return "/"
    if len(segs[0]) == 2 and len(segs) > 1:  # language prefix, e.g. my.gov.au's /en/...
        return "/" + "/".join(segs[:2])
    return "/" + segs[0]


def plan_domain(
    strategy: SourceStrategy, client: httpx.Client, sleep: Sleep = time.sleep, now: datetime | None = None,
) -> PlanReport:
    log = _JsonLogAdapter(logger, {"run_id": str(uuid.uuid4())})
    report = PlanReport(domain=strategy.domain, strategy=strategy.strategy, max_pages=strategy.max_pages)
    if strategy.strategy == "wayback":
        now_ts = (now or datetime.now(UTC)).strftime("%Y%m%d%H%M%S")
        robots = _archive_robots(strategy, client, now_ts, None, sleep, log)
        raw = list_archived_urls(strategy, client, sleep, log)
    elif strategy.strategy == "live_scoped":
        robots_url = f"https://{strategy.effective_host}/robots.txt"
        resp = _live_get(client, robots_url)
        robots = _parse_robots(resp.text if resp is not None and resp.status_code == 200 else "", robots_url)
        starts = list(robots.site_maps() or []) or [f"https://{strategy.effective_host}/sitemap.xml"]
        raw = strategy.start_urls + _sitemap_urls(client, starts, None, log, strategy.domain)
        report.note = ("Counts sitemap + start URLs only. A real crawl also follows links, "
                       "so it can find more pages than this.")
    else:
        report.note = "Uses the original crawler; plan is only available for strategy domains."
        return report

    unique: set[str] = set()
    for u in raw:
        n = normalise_url(u, strategy)
        if n:
            unique.add(n)
    in_scope: Counter[str] = Counter()
    out_scope: Counter[str] = Counter()
    for n in unique:
        if not path_in_scope(n, strategy):
            out_scope[_section(n)] += 1
        elif not robots.can_fetch(USER_AGENT, n):
            report.disallowed_by_robots += 1
        else:
            in_scope[_section(n)] += 1
    report.discovered = len(raw)
    report.unique_after_normalising = len(unique)
    report.in_scope = sum(in_scope.values())
    report.in_scope_by_section = dict(in_scope.most_common())
    report.out_of_scope_by_section = dict(out_scope.most_common(15))
    return report


def format_plan(r: PlanReport) -> str:
    lines = [f"{r.domain}  (strategy: {r.strategy})"]
    if r.note:
        lines.append(f"  note: {r.note}")
    if r.strategy not in ("wayback", "live_scoped"):
        return "\n".join(lines)
    lines += [
        f"  URLs discovered:           {r.discovered}",
        f"  unique after normalising:  {r.unique_after_normalising}",
        f"  disallowed by robots.txt:  {r.disallowed_by_robots}",
        f"  IN SCOPE (would fetch):    {r.in_scope}   (max_pages = {r.max_pages})",
        "  -> " + (f"WOULD TRUNCATE: raise max_pages to at least {r.in_scope} or narrow include_paths"
                   if r.would_truncate else "fits under max_pages"),
        "  in scope, by section:",
        *[f"    {n:6}  {sec}" for sec, n in r.in_scope_by_section.items()],
        "  largest OUT-of-scope sections (check nothing important is here):",
        *[f"    {n:6}  {sec}" for sec, n in r.out_of_scope_by_section.items()],
    ]
    return "\n".join(lines)


def plan(
    domains: list[str] | None, config_path: Path, client: httpx.Client | None = None,
    strategies_path: Path = DEFAULT_STRATEGIES_PATH,
) -> list[PlanReport]:
    """Entry point for `python -m rag.main ingest --plan`. Writes nothing."""
    configure_json_logging()
    approved_names = {a.domain for a in load_approved_domains(config_path)}
    strategies = load_strategies(strategies_path)
    targets = domains or sorted(approved_names)
    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    reports: list[PlanReport] = []
    try:
        for domain in targets:
            if domain not in approved_names:
                reports.append(PlanReport(domain=domain, strategy="-", note="NOT in approved_domains.json"))
                continue
            st = strategies.get(domain) or SourceStrategy(domain=domain)
            reports.append(plan_domain(st, client))
    finally:
        if owns_client:
            client.close()
    return reports


# ===========================================================================
# Router — drop-in replacement for s01_ingest.ingest
# ===========================================================================

def ingest(
    domains: list[str] | None,
    config_path: Path,
    cache_dir: Path,
    max_pages: int = MAX_PAGES_PER_DOMAIN,
    client: httpx.Client | None = None,
    strategies_path: Path = DEFAULT_STRATEGIES_PATH,
) -> dict[str, list[PageRecord]]:
    """Same signature and return value as s01_ingest.ingest, so main.py
    only changes its import.

    --max-pages: domains without a strategy use it exactly as before.
    Strategy domains use their own `max_pages` from source_strategies.json
    unless --max-pages was explicitly set to something other than the
    default, in which case the CLI value wins.
    """
    configure_json_logging()
    run_id = str(uuid.uuid4())
    log = _JsonLogAdapter(logger, {"run_id": run_id})
    approved = load_approved_domains(config_path)
    approved_names = {a.domain for a in approved}
    strategies = load_strategies(strategies_path)
    targets = domains or [a.domain for a in approved]

    owns_client = client is None
    client = client or httpx.Client(follow_redirects=True)
    results: dict[str, list[PageRecord]] = {}
    try:
        for domain in targets:
            if domain not in approved_names:  # allowlist check before ANY network call
                log.error("domain_rejected", extra={"domain": domain})
                continue
            strategy = strategies.get(domain)
            cap = max_pages
            # "live" domains keep the original CLI behaviour exactly; only the
            # new strategies take their cap from source_strategies.json.
            if strategy is not None and strategy.strategy != "live" and max_pages == MAX_PAGES_PER_DOMAIN:
                cap = strategy.max_pages
            try:
                if strategy is None or strategy.strategy == "live":
                    results[domain] = s01_ingest.ingest_domain(
                        domain, approved, cache_dir, client=client, max_pages=cap, run_id=run_id
                    )
                elif strategy.strategy == "live_scoped":
                    results[domain] = ingest_live_scoped(strategy, cache_dir, client, cap, run_id=run_id)
                else:
                    results[domain] = ingest_wayback(strategy, cache_dir, client, cap, run_id=run_id)
            except Exception:  # noqa: BLE001 — one broken source must not abort the others
                log.exception("domain_ingest_crashed", extra={"domain": domain})
    finally:
        if owns_client:
            client.close()
    return results
