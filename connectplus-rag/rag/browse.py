"""Screen 3a - Browse topics: category -> subcategory -> resource.

Built from what is already in the index, nothing else. The approved sites
organise their own pages into sections, and that structure survives in the
URLs stages 01-04 stored - Be Connected's
/topic-library/<topic>/<course>/<lesson> is literally topic -> course ->
steps. So browse needs no search, no embeddings and no models: it groups the
indexed pages by URL path.

rag/config/browse_topics.json is the only hand-written part. It names the
design's seven categories (at most seven subcategories each) and, for each
subcategory, which site sections belong in it - a "source" is a domain plus
path, as stored in the chunks table:

    "my.gov.au/en/services/ageing/*"   every section below this path is one resource
    "scamwatch.gov.au/report-a-scam"   this page/section is one resource

A resource is one section of a trusted site: its landing page plus every
page under it, which are the steps screen 3c walks through. A page that is
not in the index - because its domain or section was never approved, or it
was never crawled - cannot appear, and a source that matches nothing simply
yields no resource (`python -m rag.main browse` reports those).

Steps follow the site's own order. The index keeps page text, not the
course menu, so the order comes from the section's landing page HTML: each
page sits where its title first appears there (Be Connected lists its
lessons as "1 What is a text or SMS scam? 2 How to identify...").
Landing pages come from stage 01's cache; `browse --build` fetches the
missing ones once.
"""

from __future__ import annotations

import html
import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from rag.schemas import BrowseCategory, BrowsePage, BrowseSubcategory, Resource

TOPICS_PATH = Path(__file__).parent / "config" / "browse_topics.json"
MAX_PER_LEVEL = 7  # design rule: never more than seven cards per level
PAGE_CACHE_DIR = Path(".cache/html")  # stage 01's cache, as the CLI lays it out

# One indexed page: {"doc_id", "url", "domain", "title"} - a row of
# `select distinct doc_id, url, domain, title from chunks`.
DocRow = Mapping[str, str | None]

# (url, domain) -> that page's raw HTML, or None when it is not available.
HtmlFunction = Callable[[str, str], str | None]

_TAG_RE = re.compile(r"<[^>]+>")
# Script and style bodies are not what a visitor sees. Real case: Be Connected's
# JSON-LD course list orders a topic's courses differently from the page itself.
_HIDDEN_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


@lru_cache(maxsize=1)
def load_topics(path: Path = TOPICS_PATH) -> tuple[BrowseCategory, ...]:
    return tuple(
        BrowseCategory.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8"))
    )


def find_subcategory(category_id: str, subcategory_id: str) -> BrowseSubcategory:
    """KeyError on an unknown id - the caller turns that into a 404."""
    for category in load_topics():
        if category.id == category_id:
            for sub in category.subcategories:
                if sub.id == subcategory_id:
                    return sub
    raise KeyError(f"unknown browse topic {category_id}/{subcategory_id}")


def page_key(doc: DocRow) -> str:
    """'domain/path' with no scheme, query or trailing slash - the form
    sources are written in. Uses the stored domain, not the URL's host, so
    'www.esafety.gov.au' and 'esafety.gov.au' are the same key."""
    return f"{doc['domain']}{urlsplit(str(doc['url'])).path.rstrip('/')}"


def _title(doc: DocRow | None, key: str) -> str:
    """Page title without its ' | Site name' suffix; the URL slug when the
    page has none (real case: several my.gov.au pages are stored untitled)."""
    # Be Connected stores some lessons as "What do apps do? - lesson".
    title = str((doc or {}).get("title") or "").split(" | ")[0].strip().removesuffix(" - lesson")
    if title and title != "None":
        return title
    return key.rsplit("/", 1)[-1].replace("-", " ").capitalize()


def _words(text: str) -> str:
    """Casefolded words only, single-spaced. Punctuation goes because stored
    titles and the landing page's list disagree on it (real: 'What is email
    used for' vs '1 What is email used for?', 'you’re' vs 'you&rsquo;re')."""
    return " ".join(re.sub(r"[^\w\s]", " ", html.unescape(text).casefold()).split())


def site_order(landing_html: str, docs: list[DocRow]) -> list[DocRow]:
    """`docs` in the order the landing page lists them.

    A numbered entry wins ("2 How to identify a text or SMS scam" - Be
    Connected's activity list): titles also turn up earlier in intros and
    transcripts, so first appearance alone put a course's last lesson first
    on real data. Unnumbered titles go by first appearance (myGov's link
    lists); titles not on the page keep URL order, last.
    """
    text = _words(_TAG_RE.sub(" ", _HIDDEN_RE.sub(" ", landing_html)))

    def position(doc: DocRow) -> tuple[int, int]:
        words = _words(_title(doc, page_key(doc))).split()
        title = re.escape(" ".join(words))
        # Full title, then its first four words: list wording drifts from the
        # stored title (real: 'A new kind of control: voice assistants').
        for candidate in (title, re.escape(" ".join(words[:4])) if len(words) > 4 else None):
            numbered = candidate and re.search(rf"(?:^|\s)(\d{{1,2}}) {candidate}(?=\s|$)", text)
            if numbered:
                return 0, int(numbered.group(1))
        found = re.search(title, text)
        return (1, found.start()) if found else (2, 0)

    return sorted(docs, key=position)  # stable: ties keep URL order


def cached_page_html(cache_dir: Path, fetch_missing: bool = False) -> HtmlFunction:
    """Reads pages from stage 01's cache (`<cache_dir>/<domain>/pages/`).

    With fetch_missing, a page not in the cache is fetched once through stage
    01's own fetcher - same User-Agent, cached for next time, a politeness
    delay after each real request - and only for domains crawled live. A
    'wayback' domain (eSafety blocks automated clients) is never fetched live.
    """
    import httpx

    from rag.s01_ingest import DEFAULT_DELAY_SECONDS, _fetch_page, _JsonLogAdapter, _url_hash, logger
    from rag.s01_sources import load_strategies

    log = _JsonLogAdapter(logger, {"run_id": "browse"})
    archived = {d for d, s in load_strategies().items() if s.strategy == "wayback"}
    client = httpx.Client(follow_redirects=True)

    def read(url: str, domain: str) -> str | None:
        pages_dir = cache_dir / domain / "pages"
        cached = (pages_dir / f"{_url_hash(url)}.meta.json").exists()
        if not cached and (not fetch_missing or domain in archived):
            return None
        record, cache_hit = _fetch_page(url, domain, client, pages_dir, log)
        if not cache_hit:
            time.sleep(DEFAULT_DELAY_SECONDS)
        return record.html if record.status == 200 else None

    return read


def _in_site_order(
    parent_key: str,
    parent: DocRow | None,
    below: list[tuple[str, DocRow]],
    page_html: HtmlFunction | None,
) -> list[DocRow]:
    """Every page below `parent_key`, depth first: each child in the order the
    parent's own page lists it, then that child's pages in the order ITS page
    lists them - so a whole topic reads course 1, its lessons, course 2, ...
    Children with no indexed page of their own keep URL order, last."""
    branches: dict[str, list[tuple[str, DocRow]]] = {}
    for key, doc in below:
        branches.setdefault(key[len(parent_key) + 1 :].split("/")[0], []).append((key, doc))
    heads = {
        seg: next((doc for key, doc in items if key == f"{parent_key}/{seg}"), None)
        for seg, items in branches.items()
    }
    listed = [head for head in heads.values() if head is not None]
    parent_html = None
    if parent and page_html and len(listed) > 1:
        parent_html = page_html(str(parent["url"]), str(parent["domain"]))
    if parent_html:
        listed = site_order(parent_html, listed)
    order = [page_key(head).rsplit("/", 1)[-1] for head in listed]
    order += [seg for seg, head in heads.items() if head is None]

    pages: list[DocRow] = []
    for seg in order:
        child_key = f"{parent_key}/{seg}"
        head = heads[seg]
        rest = [(key, doc) for key, doc in branches[seg] if key != child_key]
        pages += ([head] if head else []) + _in_site_order(child_key, head, rest, page_html)
    return pages


def resources_for(
    sub: BrowseSubcategory,
    docs: Iterable[DocRow],
    approved_domains: set[str],
    page_html: HtmlFunction | None = None,
) -> list[Resource]:
    """Groups indexed pages into this subcategory's resources, in the order
    its sources list them. Pages from unapproved domains are skipped: the
    index outlives a domain's approval (stage 04 never deletes rows).

    `page_html` supplies landing pages for site_order(); without it, or when
    a landing page is unavailable, steps stay in URL order."""
    keyed = sorted(
        ((page_key(d), d) for d in docs if d["domain"] in approved_domains), key=lambda pair: pair[0]
    )
    groups: dict[str, list[tuple[str, DocRow]]] = {}
    for source in sub.sources:
        children = source.endswith("/*")
        prefix = source.removesuffix("/*")
        for key, doc in keyed:
            if key.startswith(prefix + "/"):
                group = prefix + "/" + key[len(prefix) + 1 :].split("/")[0] if children else prefix
            elif key == prefix and not children:
                group = prefix
            else:
                continue  # unrelated page, or the landing page of a section whose children are listed
            groups.setdefault(group, []).append((key, doc))

    resources = []
    for group, pages in groups.items():
        landing = next((doc for key, doc in pages if key == group), None)
        below = [(key, doc) for key, doc in pages if key != group]
        ordered = ([landing] if landing else []) + _in_site_order(group, landing, below, page_html)
        resources.append(
            Resource(
                id=group,
                url=str(ordered[0]["url"]),
                domain=str(ordered[0]["domain"]),
                title=_title(landing, group),
                pages=[
                    BrowsePage(doc_id=str(d["doc_id"]), url=str(d["url"]), title=_title(d, page_key(d)))
                    for d in ordered
                ],
            )
        )
    return resources
