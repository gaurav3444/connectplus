"""Tests for rag/s01_sources.py: myGov scoped crawl, eSafety archive fetch,
router. All use httpx.MockTransport: no real network, no real sleeping."""

from __future__ import annotations

import json
from datetime import UTC
from pathlib import Path

import httpx

from rag.s01_ingest import _url_hash as url_key
from rag.s01_ingest import load_pages_from_manifest
from rag.s01_sources import (
    SourceStrategy,
    format_plan,
    ingest,
    ingest_live_scoped,
    ingest_wayback,
    load_strategies,
    normalise_url,
    path_in_scope,
    plan,
    plan_domain,
)

NO_SLEEP = lambda _s: None  # noqa: E731

MYGOV = SourceStrategy(
    domain="my.gov.au", strategy="live_scoped", url_normaliser="aem_mygov",
    start_urls=["https://my.gov.au/en/about/help"],
    include_paths=["/en/about"], exclude_paths=["/LoginServices", "/en/about/secret"],
    delay_seconds=0,
)
ESAFETY = SourceStrategy(
    domain="esafety.gov.au", strategy="wayback", host="www.esafety.gov.au",
    archive_from="20250101", exclude_paths=["/key-topics/esafety-guide"], delay_seconds=0,
)


def _html(*links: str, body: str = "Real content") -> str:
    anchors = "".join(f'<a href="{h}">x</a>' for h in links)
    return f"<html><body><main><p>{body}</p>{anchors}</main></body></html>"


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# --------------------------------------------------------------------------- URL rules

def test_mygov_url_forms_collapse_to_one() -> None:
    forms = [
        "https://my.gov.au/en/about/help",
        "https://my.gov.au/content/mygov/en/about/help.html",
        "https://my.gov.au:443/content/mygov/en/about/help.html",
        "http://my.gov.au/en/about/help/?utm_source=x#top",
    ]
    assert {normalise_url(f, MYGOV) for f in forms} == {"https://my.gov.au/en/about/help"}


def test_off_host_and_non_http_are_rejected() -> None:
    assert normalise_url("https://www.servicesaustralia.gov.au/x", MYGOV) is None
    assert normalise_url("mailto:help@my.gov.au", MYGOV) is None


def test_scope_is_segment_aware_and_exclude_wins() -> None:
    assert path_in_scope("https://my.gov.au/en/about", MYGOV)
    assert path_in_scope("https://my.gov.au/en/about/help/contact", MYGOV)
    assert not path_in_scope("https://my.gov.au/en/aboutface", MYGOV)
    assert not path_in_scope("https://my.gov.au/en/about/secret/page", MYGOV)
    assert not path_in_scope("https://my.gov.au/en/services/work", MYGOV)


# --------------------------------------------------------------------------- myGov crawl

def _mygov_handler(calls: list[str]):  # type: ignore[no-untyped-def]
    sitemap = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://my.gov.au/content/mygov/en/about/help.html</loc></url>
      <url><loc>https://my.gov.au/en/services/work</loc></url>
      <url><loc>https://my.gov.au/en/about/sign-in-redirect</loc></url>
    </urlset>"""
    pages = {
        "/robots.txt": (200, "User-agent: *\nDisallow: /en/about/blocked\nSitemap: https://my.gov.au/sitemap.xml\n"),
        "/sitemap.xml": (200, sitemap),
        "/en/about/help": (200, _html("/content/mygov/en/about/help/contact.html", "/LoginServices/login",
                                      "https://youtube.com/x", "/en/about/blocked", "/en/services/work")),
        "/en/about/help/contact": (200, _html(body="Call 132 307")),
        "/LoginServices/start": (200, "<html>sign in</html>"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/en/about/sign-in-redirect":
            return httpx.Response(302, headers={"location": "https://my.gov.au/LoginServices/start"})
        status, body = pages.get(request.url.path, (404, "nope"))
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})
    return handler


def test_mygov_scoped_crawl_fetches_each_page_once_and_stays_in_scope(tmp_path: Path) -> None:
    calls: list[str] = []
    records = ingest_live_scoped(MYGOV, tmp_path, _client(_mygov_handler(calls)), 500, sleep=NO_SLEEP)

    urls = sorted(str(r.url) for r in records)
    assert urls == ["https://my.gov.au/en/about/help", "https://my.gov.au/en/about/help/contact"]
    fetched_paths = [httpx.URL(c).path for c in calls]
    assert fetched_paths.count("/en/about/help") == 1          # 3 spellings, 1 fetch
    assert "/en/services/work" not in fetched_paths             # out of include_paths
    assert "/en/about/blocked" not in fetched_paths             # robots.txt
    assert "/LoginServices/login" not in fetched_paths          # excluded

    manifest = json.loads((tmp_path / "my.gov.au" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["pages_fetched"] == 2
    assert manifest["summary"]["pages_disallowed_by_robots"] == 1
    assert (tmp_path / "my.gov.au" / "pages" / f"{url_key('https://my.gov.au/en/about/help')}.html").exists()


def test_mygov_second_run_makes_zero_network_calls(tmp_path: Path) -> None:
    ingest_live_scoped(MYGOV, tmp_path, _client(_mygov_handler([])), 500, sleep=NO_SLEEP)
    calls: list[str] = []
    again = ingest_live_scoped(MYGOV, tmp_path, _client(_mygov_handler(calls)), 500, sleep=NO_SLEEP)
    assert calls == []
    assert len(again) == 2


# --------------------------------------------------------------------------- eSafety archive

def _wayback_handler(calls: list[str], fail_first_page_times: int = 0):  # type: ignore[no-untyped-def]
    state = {"fails": fail_first_page_times}

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if request.url.host == "www.esafety.gov.au":           # live site: blocked, as in real life
            raise httpx.ConnectTimeout("blocked", request=request)
        if request.url.path == "/cdx/search/cdx":
            if "resumeKey" not in request.url.params:
                return httpx.Response(200, json=[
                    ["original"],
                    ["https://www.esafety.gov.au/seniors"],
                    ["http://www.esafety.gov.au/seniors/?page=2"],          # dup after normalising
                    ["https://www.esafety.gov.au/key-topics/esafety-guide/app"],  # licence exclusion
                    [], ["RESUME1"],
                ])
            return httpx.Response(200, json=[
                ["original"],
                ["https://www.esafety.gov.au/seniors/online-scams"],
                ["https://www.esafety.gov.au/admin/x"],                    # robots-disallowed
            ])
        if "/robots.txt" in url:
            return httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")
        if "id_/https://www.esafety.gov.au/seniors/online-scams" in url:
            if state["fails"] > 0:
                state["fails"] -= 1
                return httpx.Response(429, headers={"retry-after": "1"})
        m = request.url.path.split("id_/", 1)
        if len(m) == 2 and request.url.path.startswith("/web/20260930"):
            # Wayback redirects "now" to the closest real capture
            return httpx.Response(302, headers={"location": f"https://web.archive.org/web/20260815093000id_/{m[1]}"})
        if request.url.path.startswith("/web/20260815093000id_/"):
            return httpx.Response(200, text=_html(body="eSafety seniors guidance"),
                                  headers={"content-type": "text/html"})
        return httpx.Response(404)
    return handler


def _run_wayback(tmp_path: Path, calls: list[str], **kw) -> list:  # type: ignore[no-untyped-def,type-arg]
    from datetime import datetime
    return ingest_wayback(ESAFETY, tmp_path, _client(_wayback_handler(calls, **kw)), 500, sleep=NO_SLEEP,
                          now=datetime(2026, 9, 30, tzinfo=UTC))


def test_wayback_keeps_original_urls_and_snapshot_dates(tmp_path: Path) -> None:
    calls: list[str] = []
    records = _run_wayback(tmp_path, calls)

    assert sorted(str(r.url) for r in records) == [
        "https://www.esafety.gov.au/seniors",
        "https://www.esafety.gov.au/seniors/online-scams",
    ]
    assert all(r.domain == "esafety.gov.au" and r.status == 200 for r in records)
    assert all(r.fetched_at.isoformat().startswith("2026-08-15T09:30") for r in records)

    meta = json.loads((tmp_path / "esafety.gov.au" / "pages" /
                       f"{url_key('https://www.esafety.gov.au/seniors')}.meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "wayback" and meta["snapshot_timestamp"] == "20260815093000"
    assert "web.archive.org" in meta["archive_url"]

    manifest = json.loads((tmp_path / "esafety.gov.au" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["pages_disallowed_by_robots"] == 1
    assert manifest["source"]["urls_listed_by_archive"] == 5
    # No page content is ever requested from the live eSafety site
    assert not any("www.esafety.gov.au/seniors" in c and "archive.org" not in c for c in calls)


def test_wayback_excludes_esafety_guide(tmp_path: Path) -> None:
    records = _run_wayback(tmp_path, [])
    assert not any("esafety-guide" in str(r.url) for r in records)


def test_wayback_backs_off_on_429_then_succeeds(tmp_path: Path) -> None:
    records = _run_wayback(tmp_path, [], fail_first_page_times=2)
    by_url = {str(r.url): r for r in records}
    assert by_url["https://www.esafety.gov.au/seniors/online-scams"].status == 200


def test_wayback_second_run_makes_zero_network_calls(tmp_path: Path) -> None:
    _run_wayback(tmp_path, [])
    calls: list[str] = []
    again = _run_wayback(tmp_path, calls)
    assert calls == [] and len(again) == 2


def test_circuit_breaker_stops_a_dead_source(tmp_path: Path) -> None:
    urls = [[f"https://www.esafety.gov.au/p{i}"] for i in range(40)]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/cdx/search/cdx":
            return httpx.Response(200, json=[["original"], *urls])
        if request.url.host == "www.esafety.gov.au":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(404)

    st = ESAFETY.model_copy(update={"max_consecutive_failures": 5})
    records = ingest_wayback(st, tmp_path, _client(handler), 500, sleep=NO_SLEEP)
    assert len(records) == 5
    manifest = json.loads((tmp_path / "esafety.gov.au" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["circuit_breaker_tripped"] is True


# --------------------------------------------------------------------------- router

def _write_configs(tmp_path: Path) -> tuple[Path, Path]:
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps([
        {"domain": d, "added_by": "t", "approved_at": "2026-01-01"}
        for d in ["scamwatch.gov.au", "my.gov.au"]
    ]), encoding="utf-8")
    strategies = tmp_path / "strategies.json"
    strategies.write_text(json.dumps([MYGOV.model_dump()]), encoding="utf-8")
    return approved, strategies


def test_router_rejects_unapproved_domain_with_zero_network_calls(tmp_path: Path) -> None:
    approved, strategies = _write_configs(tmp_path)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200)

    out = ingest(["evil.example"], approved, tmp_path / "c", client=_client(handler),
                 strategies_path=strategies)
    assert out == {} and calls == []


def test_router_sends_unconfigured_domains_to_original_crawler(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import rag.s01_ingest as original
    seen: list[tuple[str, int]] = []
    monkeypatch.setattr(original, "ingest_domain",
                        lambda domain, *a, **k: seen.append((domain, k["max_pages"])) or [])
    approved, strategies = _write_configs(tmp_path)
    dead = _client(lambda r: httpx.Response(404))
    ingest(["scamwatch.gov.au"], approved, tmp_path / "c", client=dead, strategies_path=strategies)
    assert seen == [("scamwatch.gov.au", 500)]


def test_router_sends_mygov_to_scoped_crawler(tmp_path: Path) -> None:
    approved, strategies = _write_configs(tmp_path)
    out = ingest(["my.gov.au"], approved, tmp_path / "c", client=_client(_mygov_handler([])),
                 strategies_path=strategies)
    assert len(out["my.gov.au"]) == 2


# --------------------------------------------------------------------------- stage 02 hand-off

def test_stage02_loader_gets_real_html_back_for_both_new_sources(tmp_path: Path) -> None:
    """Regression guard for the bug that nearly shipped: s01_ingest's
    manifest omits HTML and load_pages_from_manifest only rehydrates it
    when content_type is text. If these fetchers didn't record
    content_type, stage 02 would silently see every page as empty."""
    ingest_live_scoped(MYGOV, tmp_path, _client(_mygov_handler([])), 500, sleep=NO_SLEEP)
    _run_wayback(tmp_path, [])
    for domain in ("my.gov.au", "esafety.gov.au"):
        pages = load_pages_from_manifest(domain, tmp_path)
        assert pages and all(p.status == 200 for p in pages)
        assert all("<main>" in p.html for p in pages), domain
        manifest = json.loads((tmp_path / domain / "manifest.json").read_text(encoding="utf-8"))
        assert all("html" not in p for p in manifest["pages"])  # same small-index rule as s01_ingest


def test_cli_max_pages_override_wins_over_strategy_cap(tmp_path: Path) -> None:
    approved, strategies = _write_configs(tmp_path)
    out = ingest(["my.gov.au"], approved, tmp_path / "c", max_pages=1,
                 client=_client(_mygov_handler([])), strategies_path=strategies)
    assert len(out["my.gov.au"]) == 1


# --------------------------------------------------------------------------- plan

def test_wayback_plan_counts_by_section_and_writes_nothing(tmp_path: Path) -> None:
    listing = [["original"]] + [[f"https://www.esafety.gov.au/seniors/p{i}"] for i in range(3)] + [
        ["https://www.esafety.gov.au/akam/13/pixel_1"], ["https://www.esafety.gov.au/akam/13/pixel_2"],
        ["https://www.esafety.gov.au/research/report"], ["https://www.esafety.gov.au/admin/x"],
        ["http://www.esafety.gov.au/seniors/p0/?utm=1"],                    # dup after normalising
    ]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/cdx/search/cdx":
            return httpx.Response(200, json=listing)
        if request.url.path.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /admin\n")
        raise AssertionError(f"plan must not download pages: {request.url}")

    st = ESAFETY.model_copy(update={"include_paths": ["/seniors", "/admin"], "exclude_paths": ["/akam"],
                                    "max_pages": 2})
    report = plan_domain(st, _client(handler), sleep=NO_SLEEP)

    assert report.discovered == 8 and report.unique_after_normalising == 7
    assert report.in_scope == 3 and report.in_scope_by_section == {"/seniors": 3}
    assert report.disallowed_by_robots == 1
    assert report.out_of_scope_by_section == {"/akam": 2, "/research": 1}
    assert report.would_truncate                                  # 3 in scope > max_pages 2
    assert "WOULD TRUNCATE" in format_plan(report)
    assert not any(tmp_path.iterdir())


def test_plan_reports_unapproved_and_unconfigured_domains(tmp_path: Path) -> None:
    approved, strategies = _write_configs(tmp_path)
    dead = _client(lambda r: httpx.Response(404))
    reports = plan(["evil.example", "scamwatch.gov.au"], approved, client=dead, strategies_path=strategies)
    assert "NOT in approved" in reports[0].note
    assert "original crawler" in reports[1].note


def test_shipped_esafety_config_blocks_tracking_pixels_and_keeps_seniors() -> None:
    st = load_strategies()["esafety.gov.au"]
    assert not path_in_scope("https://www.esafety.gov.au/akam/13/pixel_108cebb2", st)
    assert not path_in_scope("https://www.esafety.gov.au/key-topics/esafety-guide/some-app", st)
    assert not path_in_scope("https://www.esafety.gov.au/research/report", st)
    assert path_in_scope("https://www.esafety.gov.au/seniors/online-scams", st)
    assert path_in_scope("https://www.esafety.gov.au/media/two-factor-authentication", st)


# --------------------------------------------------------------------------- extract-time URL exclusion

def test_scamwatch_filter_pages_are_excluded_at_extract_time() -> None:
    from rag.s01_sources import filter_pages_for_extraction
    from rag.schemas import PageRecord

    def page(u: str) -> PageRecord:
        return PageRecord(url=u, domain="scamwatch.gov.au", html="<p>x</p>", status=200,
                          content_type="text/html")

    pages = [
        page("https://scamwatch.gov.au/about-us/news-and-alerts/browse-news-and-alerts?f%5B0%5D=scam_category%3A7"),
        page("https://scamwatch.gov.au/about-us/news-and-alerts/browse-news-and-alerts?f[0]=a&f[1]=b&page=2"),
        page("https://scamwatch.gov.au/about-us/news-and-alerts/australian-taxation-office-ato-and-mygov-impersonation-scams"),
    ]
    kept, excluded = filter_pages_for_extraction("scamwatch.gov.au", pages)
    assert excluded == 2 and [str(p.url) for p in kept] == [str(pages[2].url)]
    assert filter_pages_for_extraction("my.gov.au", pages) == (pages, 0)  # no patterns configured


def test_live_strategy_domains_keep_the_cli_max_pages(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import rag.s01_ingest as original
    seen: list[int] = []
    monkeypatch.setattr(original, "ingest_domain", lambda d, *a, **k: seen.append(k["max_pages"]) or [])
    approved = tmp_path / "approved.json"
    approved_rows = [{"domain": "scamwatch.gov.au", "added_by": "t", "approved_at": "x"}]
    approved.write_text(json.dumps(approved_rows), encoding="utf-8")
    strategies = tmp_path / "s.json"
    strategy_rows = [{"domain": "scamwatch.gov.au", "strategy": "live", "max_pages": 7}]
    strategies.write_text(json.dumps(strategy_rows), encoding="utf-8")
    dead = _client(lambda r: httpx.Response(404))
    run = {"client": dead, "strategies_path": strategies}
    ingest(["scamwatch.gov.au"], approved, tmp_path / "c", **run)
    ingest(["scamwatch.gov.au"], approved, tmp_path / "c", max_pages=1500, **run)
    assert seen == [500, 1500]


def test_be_connected_temp_placeholder_lesson_is_excluded_at_extract_time() -> None:
    from rag.s01_sources import filter_pages_for_extraction
    from rag.schemas import PageRecord

    course = "https://beconnected.esafety.gov.au/topic-library/wi-fi-and-mobile-networks/home-networks"
    pages = [
        PageRecord(url=f"{course}/{slug}", domain="beconnected.esafety.gov.au", html="<p>x</p>", status=200,
                   content_type="text/html")
        for slug in ("temp-lesson-what-is-the-nbn", "what-is-the-nbn")
    ]
    kept, excluded = filter_pages_for_extraction("beconnected.esafety.gov.au", pages)
    assert excluded == 1 and [str(p.url) for p in kept] == [f"{course}/what-is-the-nbn"]
