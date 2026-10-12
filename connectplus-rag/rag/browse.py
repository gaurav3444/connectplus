"""Screen 3a - Browse topics: category -> subcategory -> resource.

The two upper levels are a fixed taxonomy (rag/config/browse_topics.json),
written by people, because the design caps each level at seven items and a
senior needs the same menu every visit. Only the third level comes from the
index: each subcategory carries an English query, retrieve() runs it like
any other question, and the chunks it returns collapse into one Resource per
source page.

Nothing here fetches from the web at request time. The approved sites were
already crawled, cleaned, chunked and indexed by stages 01-04; browse reads
that index, so a resource can only ever be a page someone approved.

The same two trust rules as answering apply:

- A chunk below REFUSAL_THRESHOLD is not listed. An empty subcategory is
  shown as the designed empty state, never filled with weak matches.
- A chunk whose domain is no longer approved is not listed. Stage 04 never
  deletes rows, so the index can outlive a domain's approval - the same
  reason stage 06 re-checks domains on citations.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from rag.schemas import BrowseCategory, BrowseSubcategory, Resource, Retrieved

TOPICS_PATH = Path(__file__).parent / "config" / "browse_topics.json"
MAX_PER_LEVEL = 7        # design rule: never more than seven cards per level
SNIPPET_CHARS = 200
CHUNKS_PER_QUERY = 20    # enough chunks to still leave several distinct pages after grouping


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


def resources_from_chunks(
    chunks: Sequence[Retrieved],
    approved_domains: set[str],
    threshold: float,
    limit: int = MAX_PER_LEVEL,
) -> list[Resource]:
    """One Resource per page, best page first. `chunks` arrive best-first
    from retrieve(), so the first chunk seen for a page is its best one."""
    by_doc: dict[str, Resource] = {}
    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        if chunk.doc_id in by_doc or chunk.score < threshold or chunk.domain not in approved_domains:
            continue
        by_doc[chunk.doc_id] = Resource(
            doc_id=chunk.doc_id,
            url=str(chunk.url),
            domain=chunk.domain,
            title=chunk.title,
            lang=chunk.lang,
            heading_path=chunk.heading_path,
            snippet=chunk.text[:SNIPPET_CHARS].rstrip(),
            score=chunk.score,
        )
        if len(by_doc) == limit:
            break
    return list(by_doc.values())
