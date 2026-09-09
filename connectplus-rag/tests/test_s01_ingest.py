"""Tests for stage 01. Every test uses httpx.MockTransport - none of these
touch the real network, which also means they run the same whether or not
the sandbox they're executed in can reach beconnected.esafety.gov.au etc.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from rag.s01_ingest import (
    DomainNotApprovedError,
    ingest_domain,
)
from rag.schemas import ApprovedDomain

APPROVED = [
    ApprovedDomain(domain="example-approved.test", added_by="test", approved_at="2026-01-01"),
]

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example-approved.test/page-1</loc></url>
  <url><loc>https://example-approved.test/page-2</loc></url>
</urlset>"""

ROBOTS_TXT = "User-agent: *\nAllow: /\nSitemap: https://example-approved.test/sitemap.xml\n"

ROBOTS_TXT_DISALLOW_PAGE_2 = (
    "User-agent: *\nDisallow: /page-2\nSitemap: https://example-approved.test/sitemap.xml\n"
)


def _make_client(responses: dict[str, tuple[int, str]]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in responses:
            status, body = responses[url]
            return httpx.Response(status, text=body)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_rejects_non_allowlisted_domain_with_zero_network_calls(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="should never be called")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    with pytest.raises(DomainNotApprovedError):
        ingest_domain("not-approved.test", APPROVED, tmp_path, client=client)

    assert calls == []


def test_discovers_and_fetches_via_sitemap(tmp_path: Path) -> None:
    responses = {
        "https://example-approved.test/robots.txt": (200, ROBOTS_TXT),
        "https://example-approved.test/sitemap.xml": (200, SITEMAP_XML),
        "https://example-approved.test/page-1": (200, "<html>Page 1</html>"),
        "https://example-approved.test/page-2": (200, "<html>Page 2</html>"),
    }
    client = _make_client(responses)

    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    assert len(records) == 2
    urls = {str(r.url) for r in records}
    assert urls == {"https://example-approved.test/page-1", "https://example-approved.test/page-2"}
    assert all(r.status == 200 for r in records)
    assert all(r.domain == "example-approved.test" for r in records)


def test_respects_robots_disallow(tmp_path: Path) -> None:
    responses = {
        "https://example-approved.test/robots.txt": (200, ROBOTS_TXT_DISALLOW_PAGE_2),
        "https://example-approved.test/sitemap.xml": (200, SITEMAP_XML),
        "https://example-approved.test/page-1": (200, "<html>Page 1</html>"),
    }
    client = _make_client(responses)

    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    urls = {str(r.url) for r in records}
    assert urls == {"https://example-approved.test/page-1"}


def test_second_run_makes_zero_network_calls(tmp_path: Path) -> None:
    responses = {
        "https://example-approved.test/robots.txt": (200, ROBOTS_TXT),
        "https://example-approved.test/sitemap.xml": (200, SITEMAP_XML),
        "https://example-approved.test/page-1": (200, "<html>Page 1</html>"),
        "https://example-approved.test/page-2": (200, "<html>Page 2</html>"),
    }
    client = _make_client(responses)
    first = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)
    assert len(first) == 2

    calls: list[str] = []

    def blocking_handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(500, text="should never be reached on a cached re-run")

    second_client = httpx.Client(transport=httpx.MockTransport(blocking_handler))
    second = ingest_domain("example-approved.test", APPROVED, tmp_path, client=second_client)

    assert calls == []
    assert len(second) == 2
    assert {str(r.url) for r in second} == {str(r.url) for r in first}


def test_network_failure_is_recorded_not_raised(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example-approved.test/robots.txt":
            return httpx.Response(200, text=ROBOTS_TXT)
        if url == "https://example-approved.test/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_XML)
        if url == "https://example-approved.test/page-1":
            raise httpx.ConnectTimeout("simulated timeout", request=request)
        return httpx.Response(200, text="<html>Page 2</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    by_url = {str(r.url): r for r in records}
    assert by_url["https://example-approved.test/page-1"].status == -1
    assert by_url["https://example-approved.test/page-1"].html == ""
    assert by_url["https://example-approved.test/page-2"].status == 200


def test_falls_back_to_link_crawl_when_sitemap_is_empty(tmp_path: Path) -> None:
    homepage_html = """
    <html><body>
      <a href="/about">About</a>
      <a href="https://external-site.test/nope">External, must be ignored</a>
      <a href="/about">About again, must dedupe</a>
    </body></html>
    """
    empty_sitemap = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        mapping = {
            "https://example-approved.test/robots.txt": (200, ROBOTS_TXT),
            "https://example-approved.test/sitemap.xml": (200, empty_sitemap),
            "https://example-approved.test/": (200, homepage_html),
            "https://example-approved.test/about": (200, "<html>About page</html>"),
        }
        if url in mapping:
            status, body = mapping[url]
            # Real servers declare content-type; a bare httpx.Response(text=...)
            # defaults to text/plain, which would fail our html-content-type
            # gate for a reason that has nothing to do with the code under test.
            return httpx.Response(status, text=body, headers={"content-type": "text/html; charset=utf-8"})
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    urls = {str(r.url) for r in records}
    assert "https://example-approved.test/" in urls
    assert "https://example-approved.test/about" in urls
    assert "https://external-site.test/nope" not in urls
    assert len(records) == 2  # homepage + /about, deduped despite two links to /about


def test_malformed_content_does_not_crash_the_run(tmp_path: Path) -> None:
    """Regression test for a real failure: a domain that returns garbled,
    non-HTML bytes (observed in practice from what looked like a bot-check
    response) used to crash the entire ingest run with an unhandled
    AssertionError from html.parser. It must now be logged and skipped -
    stage 01's job is to record what happened per page, not to assume
    every response is well-formed HTML.
    """
    empty_sitemap = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>"""
    garbled_body = "<![\x0c\x00o8nD\x17/\x1d+\x05d"  # shape of the real crash payload

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example-approved.test/robots.txt":
            return httpx.Response(200, text=ROBOTS_TXT)
        if url == "https://example-approved.test/sitemap.xml":
            return httpx.Response(200, text=empty_sitemap)
        if url == "https://example-approved.test/":
            return httpx.Response(200, text=garbled_body, headers={"content-type": "text/html"})
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))

    # The whole point of this test: it must return, not raise.
    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    assert len(records) == 1
    assert records[0].status == 200
    assert records[0].html == garbled_body  # still recorded - we just don't crash extracting links from it


def test_circuit_breaker_stops_after_consecutive_failures(tmp_path: Path) -> None:
    """Regression test for a real failure: esafety.gov.au returned a valid
    sitemap with 500+ URLs, then every single page fetch timed out. Without
    a circuit breaker, that means ~500 sequential 15-second timeouts -
    over two hours - before the run finishes. It should give up on a
    domain that looks fully blocked long before that.
    """
    sitemap_with_many_urls = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    """ + "\n".join(
        f"<url><loc>https://example-approved.test/page-{i}</loc></url>" for i in range(20)
    ) + "</urlset>"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example-approved.test/robots.txt":
            return httpx.Response(200, text=ROBOTS_TXT)
        if url == "https://example-approved.test/sitemap.xml":
            return httpx.Response(200, text=sitemap_with_many_urls)
        raise httpx.ConnectTimeout("simulated total block", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    from rag.s01_ingest import CONSECUTIVE_FAILURE_LIMIT
    assert len(records) == CONSECUTIVE_FAILURE_LIMIT  # stopped, not all 20 attempted
    assert all(r.status == -1 for r in records)

    manifest = json.loads((tmp_path / "example-approved.test" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["summary"]["circuit_breaker_tripped"] is True


def test_ingest_orchestrator_passes_max_pages_through(tmp_path: Path) -> None:
    """The --max-pages CLI flag is only useful if it actually reaches
    ingest_domain. This caught a real gap: Be Connected's real sitemap has
    1094 URLs and the default cap of 500 silently dropped 594 of them."""
    from rag.s01_ingest import ingest

    config_path = tmp_path / "approved_domains.json"
    config_path.write_text(json.dumps([a.model_dump() for a in APPROVED]), encoding="utf-8")

    sitemap_with_many_urls = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    """ + "\n".join(
        f"<url><loc>https://example-approved.test/page-{i}</loc></url>" for i in range(10)
    ) + "</urlset>"

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example-approved.test/robots.txt":
            return httpx.Response(200, text=ROBOTS_TXT)
        if url == "https://example-approved.test/sitemap.xml":
            return httpx.Response(200, text=sitemap_with_many_urls)
        return httpx.Response(200, text=f"<html>{url}</html>", headers={"content-type": "text/html"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = ingest(None, config_path, tmp_path, max_pages=3, client=client)

    assert len(results["example-approved.test"]) == 3


def test_manifest_does_not_duplicate_html_content(tmp_path: Path) -> None:
    """Regression test for a real failure: manifest.json used to embed the
    full HTML of every page a second time (on top of pages/<hash>.html),
    which made it balloon to the size of the whole corpus - big enough that
    a text editor refused to open it with an 'invalid string length' error
    on a real ~500-page Scamwatch crawl. The manifest must stay a small
    index; HTML lives only in pages/.
    """
    big_html = "<html>" + ("x" * 50_000) + "</html>"
    responses = {
        "https://example-approved.test/robots.txt": (200, ROBOTS_TXT),
        "https://example-approved.test/sitemap.xml": (200, SITEMAP_XML),
        "https://example-approved.test/page-1": (200, big_html),
        "https://example-approved.test/page-2": (200, big_html),
    }
    client = _make_client(responses)
    ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    manifest_path = tmp_path / "example-approved.test" / "manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")

    assert "html" not in json.loads(manifest_text)["pages"][0]
    # The manifest should be tiny even though the two real pages are ~50KB each -
    # if HTML ever leaks back into it, this is the assertion that catches it.
    assert len(manifest_text) < 5_000


def test_second_run_rehydrates_full_html_from_disk_cache(tmp_path: Path) -> None:
    """The manifest no longer carries HTML, so a cached re-run must pull it
    back from pages/<hash>.html - not just return empty bodies."""
    responses = {
        "https://example-approved.test/robots.txt": (200, ROBOTS_TXT),
        "https://example-approved.test/sitemap.xml": (200, SITEMAP_XML),
        "https://example-approved.test/page-1": (200, "<html>Page 1</html>"),
        "https://example-approved.test/page-2": (200, "<html>Page 2</html>"),
    }
    client = _make_client(responses)
    first = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    second_client = httpx.Client(transport=httpx.MockTransport(
        lambda r: (_ for _ in ()).throw(AssertionError("must not hit the network"))
    ))
    second = ingest_domain("example-approved.test", APPROVED, tmp_path, client=second_client)

    first_by_url = {str(r.url): r.html for r in first}
    second_by_url = {str(r.url): r.html for r in second}
    assert first_by_url == second_by_url
    assert all(html for html in second_by_url.values())  # not silently empty


def test_binary_content_is_not_corrupted_by_text_decoding(tmp_path: Path) -> None:
    """Regression test for a real, confirmed bug: httpx's .text decodes
    bytes assuming text, which silently corrupts binary content. Scamwatch
    alone links 44 PDFs; this must cache the exact original bytes, not a
    lossy text re-encoding of them.
    """
    real_pdf_bytes = b"%PDF-1.4\n\x00\x01\x02\xfe\xff\x89\x90 some binary garbage \xc3\x28\x91"
    sitemap_with_pdf = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example-approved.test/document.pdf</loc></url>
    </urlset>"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == "https://example-approved.test/robots.txt":
            return httpx.Response(200, text=ROBOTS_TXT)
        if url == "https://example-approved.test/sitemap.xml":
            return httpx.Response(200, text=sitemap_with_pdf)
        if url == "https://example-approved.test/document.pdf":
            return httpx.Response(200, content=real_pdf_bytes, headers={"content-type": "application/pdf"})
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    records = ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    assert len(records) == 1
    pdf_record = records[0]
    assert pdf_record.status == 200
    assert pdf_record.content_type == "application/pdf"
    assert pdf_record.html == ""  # never force binary content into the text field

    # The actual bytes must be recoverable, byte-for-byte, from the .bin cache.
    from rag.s01_ingest import _url_hash
    key = _url_hash("https://example-approved.test/document.pdf")
    bin_path = tmp_path / "example-approved.test" / "pages" / f"{key}.bin"
    assert bin_path.read_bytes() == real_pdf_bytes


def test_manifest_is_valid_json_and_matches_schema(tmp_path: Path) -> None:
    responses = {
        "https://example-approved.test/robots.txt": (200, ROBOTS_TXT),
        "https://example-approved.test/sitemap.xml": (200, SITEMAP_XML),
        "https://example-approved.test/page-1": (200, "<html>Page 1</html>"),
        "https://example-approved.test/page-2": (200, "<html>Page 2</html>"),
    }
    client = _make_client(responses)
    ingest_domain("example-approved.test", APPROVED, tmp_path, client=client)

    manifest_path = tmp_path / "example-approved.test" / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["summary"]["domain"] == "example-approved.test"
    assert manifest["summary"]["pages_fetched"] == 2
    assert manifest["summary"]["pages_failed"] == 0
    assert len(manifest["pages"]) == 2
