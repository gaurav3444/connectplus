"""Screen 3a (Browse topics): the taxonomy file, and grouping indexed pages
into resources. Page rows use the real f03 URLs plus the real Be Connected
course layout (topic -> course -> lesson) seen in the live index."""

from __future__ import annotations

from pathlib import Path

import pytest

import rag.api
from rag import browse, browse_topics
from rag.browse import MAX_PER_LEVEL, cached_page_html, find_subcategory, page_key, resources_for, site_order
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


COURSE_HTML = """
<nav><a href="/topic-library/identifying-and-avoiding-scams">Identifying and avoiding scams</a></nav>
<h2>Activities</h2>
<li>1 What is a text or SMS scam? <a href="/mod/lesson/view.php?id=8478">Start now</a></li>
<li>2 How to identify a text or SMS scam <a href="/mod/lesson/view.php?id=8479">Start now</a></li>
"""


def test_steps_follow_the_order_the_landing_page_lists_them() -> None:
    def page_html(url: str, _domain: str) -> str | None:
        return COURSE_HTML if url == f"{TOPIC}/text-or-sms-scams" else None

    [course] = resources_for(_sub(f"{TOPIC[8:]}/text-or-sms-scams"), PAGES, APPROVED, page_html)

    assert [p.title for p in course.pages] == [
        "Text or SMS scams", "What is a text or SMS scam?", "How to identify a text or SMS scam",
    ]


def test_titles_match_through_entities_and_curly_quotes_and_unlisted_pages_go_last() -> None:
    pages = [
        _page("https://x.gov.au/a/z-listed-second", "What to do if you’re a victim"),
        _page("https://x.gov.au/a/m-not-listed", "Something the menu never mentions"),
        _page("https://x.gov.au/a/b-listed-first", "Protecting yourself"),
    ]
    landing = "<li>1 Protecting  yourself</li><li>2 What to do if you&rsquo;re a victim</li>"

    ordered = site_order(landing, pages)

    assert [str(p["url"]).rsplit("/", 1)[-1] for p in ordered] == [
        "b-listed-first", "z-listed-second", "m-not-listed",
    ]


def test_cache_only_reader_never_touches_the_network(tmp_path: Path) -> None:
    read = cached_page_html(tmp_path)

    assert read("https://beconnected.esafety.gov.au/topic-library/x", "beconnected.esafety.gov.au") is None


def test_a_numbered_entry_beats_an_earlier_mention_in_the_intro() -> None:
    pages = [
        _page("https://x.gov.au/a/other-things", "Other things a password manager can do"),
        _page("https://x.gov.au/a/importance", "The importance of strong and secure passwords"),
    ]
    landing = (
        "<p>You'll find out what other things a password manager can do.</p>"
        "<li>1 The importance of strong and secure passwords 7 min</li>"
        "<li>2 Other things a password manager can do 5 min</li>"
    )

    assert [p["title"] for p in site_order(landing, pages)] == [
        "The importance of strong and secure passwords", "Other things a password manager can do",
    ]


def test_titles_match_the_list_despite_punctuation_and_a_lesson_suffix() -> None:
    pages = [
        _page("https://x.gov.au/a/safely", "Safely downloading apps - lesson"),
        _page("https://x.gov.au/a/what", "What do apps do - lesson"),
    ]
    landing = "<li>1 What do apps do? 5 min</li><li>2 Safely downloading apps 6 min</li>"

    assert [p["title"] for p in site_order(landing, pages)] == [
        "What do apps do - lesson", "Safely downloading apps - lesson",
    ]
    [resource] = resources_for(_sub(f"{TOPIC[8:]}/text-or-sms-scams"), [
        _page(f"{TOPIC}/text-or-sms-scams", "Text or SMS scams"),
        _page(f"{TOPIC}/text-or-sms-scams/what-do-apps-do", "What do apps do? - lesson"),
    ], APPROVED)
    assert resource.pages[1].title == "What do apps do?"  # the suffix never reaches the screen


def test_a_numbered_entry_worded_slightly_differently_still_matches_on_its_first_words() -> None:
    pages = [
        _page("https://x.gov.au/a/how", "How a voice assistant works"),
        _page("https://x.gov.au/a/new", "A new kind of control: voice assistants"),
    ]
    landing = (
        "<li>1 A new kind of control: voice assistant 4 min</li><li>2 How a voice assistant works 5 min</li>"
    )

    assert [p["title"] for p in site_order(landing, pages)] == [
        "A new kind of control: voice assistants", "How a voice assistant works",
    ]
