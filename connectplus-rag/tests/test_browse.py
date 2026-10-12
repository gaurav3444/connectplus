"""Screen 3a (Browse topics): the taxonomy file, and grouping indexed pages
into resources. Page rows use the real f03 URLs plus the real Be Connected
course layout (topic -> course -> lesson) seen in the live index."""

from __future__ import annotations

import pytest

import rag.api
from rag import browse, browse_topics
from rag.browse import MAX_PER_LEVEL, find_subcategory, page_key, resources_for
from rag.s06_verify import load_approved_domains
from rag.schemas import BrowseSubcategory

APPROVED = load_approved_domains()
TOPIC = "https://beconnected.esafety.gov.au/topic-library/identifying-and-avoiding-scams"


def _page(url: str, title: str | None, domain: str = "beconnected.esafety.gov.au") -> dict[str, str | None]:
    return {"doc_id": f"doc-{abs(hash(url))}", "url": url, "domain": domain, "title": title}


PAGES = [
    _page(TOPIC, "Identifying and avoiding scams"),
    _page(f"{TOPIC}/text-or-sms-scams", "Text or SMS scams"),
    _page(f"{TOPIC}/text-or-sms-scams/what-is-a-text-or-sms-scam", "What is a text or SMS scam?"),
    _page(f"{TOPIC}/text-or-sms-scams/how-to-identify-a-text-or-sms-scam",
          "How to identify a text or SMS scam"),
    _page(f"{TOPIC}/romance-scams/what-is-a-romance-scam", "What is a romance scam?"),
    _page("https://scamwatch.gov.au/types-of-scams/text-or-sms-scams/", "Text or SMS scams | Scamwatch",
          "scamwatch.gov.au"),
    _page("https://www.esafety.gov.au/seniors/online-scams", "Online scams | eSafety Commissioner",
          "esafety.gov.au"),
    _page("https://my.gov.au/en/services/ageing/retirement", None, "my.gov.au"),
    _page("https://evil.example.com/types-of-scams/text-or-sms-scams", "Fake", "evil.example.com"),
]


def _sub(*sources: str) -> BrowseSubcategory:
    return BrowseSubcategory(id="t", title="T", sources=list(sources))


def test_taxonomy_respects_the_seven_per_level_rule_and_ids_are_unique() -> None:
    categories = browse_topics()

    assert 0 < len(categories) <= MAX_PER_LEVEL
    assert len({c.id for c in categories}) == len(categories)
    for category in categories:
        assert 0 < len(category.subcategories) <= MAX_PER_LEVEL, category.id
        assert len({s.id for s in category.subcategories}) == len(category.subcategories), category.id


def test_every_source_is_on_an_approved_domain() -> None:
    for category in browse_topics():
        for sub in category.subcategories:
            for source in sub.sources:
                assert source.split("/")[0] in APPROVED, source


def test_unknown_subcategory_is_a_key_error() -> None:
    assert find_subcategory("staying-safe", "passwords").title == "Passwords & passkeys"
    with pytest.raises(KeyError):
        find_subcategory("staying-safe", "no-such-thing")


def test_page_key_uses_the_stored_domain_and_drops_scheme_query_and_slash() -> None:
    row = _page("https://www.esafety.gov.au/seniors/online-scams/?x=1", None, "esafety.gov.au")

    assert page_key(row) == "esafety.gov.au/seniors/online-scams"


def test_a_section_is_one_resource_with_its_landing_page_first() -> None:
    [course] = resources_for(_sub(f"{TOPIC[8:]}/text-or-sms-scams"), PAGES, APPROVED)

    assert course.title == "Text or SMS scams"
    assert course.url == f"{TOPIC}/text-or-sms-scams"
    assert [p.title for p in course.pages] == [
        "Text or SMS scams", "How to identify a text or SMS scam", "What is a text or SMS scam?",
    ]


def test_star_makes_each_child_section_a_resource_and_skips_the_parent_landing_page() -> None:
    resources = resources_for(_sub(f"{TOPIC[8:]}/*"), PAGES, APPROVED)

    assert [r.title for r in resources] == ["Romance scams", "Text or SMS scams"]
    # No landing page was crawled for romance-scams: title from the slug, url from its first page.
    assert resources[0].url.endswith("/what-is-a-romance-scam")
    assert len(resources[1].pages) == 3


def test_resources_follow_source_order_and_site_suffixes_are_dropped() -> None:
    resources = resources_for(
        _sub("esafety.gov.au/seniors/online-scams", "scamwatch.gov.au/types-of-scams/text-or-sms-scams"),
        PAGES, APPROVED,
    )

    assert [(r.domain, r.title) for r in resources] == [
        ("esafety.gov.au", "Online scams"), ("scamwatch.gov.au", "Text or SMS scams"),
    ]


def test_untitled_pages_fall_back_to_the_url_slug() -> None:
    [resource] = resources_for(_sub("my.gov.au/en/services/ageing/*"), PAGES, APPROVED)

    assert resource.title == "Retirement"


def test_unapproved_domains_and_unmatched_sources_yield_nothing() -> None:
    assert resources_for(_sub("evil.example.com/types-of-scams/text-or-sms-scams"), PAGES, APPROVED) == []
    assert resources_for(_sub("scamwatch.gov.au/no-such-section"), PAGES, APPROVED) == []
    # A prefix must end on a path boundary: 'text-or-sms' is not 'text-or-sms-scams'.
    assert resources_for(_sub(f"{TOPIC[8:]}/text-or-sms"), PAGES, APPROVED) == []


def test_browse_reads_the_indexed_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rag.api, "_indexed_pages", lambda: tuple(PAGES))

    resources = browse("staying-safe", "scam-texts-calls")

    assert [r.id for r in resources] == [
        "beconnected.esafety.gov.au/topic-library/identifying-and-avoiding-scams/text-or-sms-scams",
        "scamwatch.gov.au/types-of-scams/text-or-sms-scams",
    ]
