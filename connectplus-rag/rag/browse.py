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
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from rag.schemas import BrowseCategory, BrowsePage, BrowseSubcategory, Resource

TOPICS_PATH = Path(__file__).parent / "config" / "browse_topics.json"
MAX_PER_LEVEL = 7  # design rule: never more than seven cards per level

# One indexed page: {"doc_id", "url", "domain", "title"} - a row of
# `select distinct doc_id, url, domain, title from chunks`.
DocRow = Mapping[str, str | None]


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
    title = str((doc or {}).get("title") or "").split(" | ")[0].strip()
    if title and title != "None":
        return title
    return key.rsplit("/", 1)[-1].replace("-", " ").capitalize()


def resources_for(
    sub: BrowseSubcategory, docs: Iterable[DocRow], approved_domains: set[str]
) -> list[Resource]:
    """Groups indexed pages into this subcategory's resources, in the order
    its sources list them. Pages from unapproved domains are skipped: the
    index outlives a domain's approval (stage 04 never deletes rows)."""
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
        # ponytail: steps after the landing page are in URL order - the index does
        # not keep the site's own lesson order. Store order_idx per page at crawl
        # time if 'What is X?' must come before 'How to identify X'.
        ordered = ([landing] if landing else []) + [doc for key, doc in pages if key != group]
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
