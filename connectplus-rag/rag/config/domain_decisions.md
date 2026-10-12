# Domain decisions

Kept out of `approved_domains.json`'s own schema (which just lists current
state) so a future teammate can see *why* a domain isn't there, not just
that it isn't.

## esafety.gov.au — dropped, 2026-09-01

Approved initially alongside `beconnected.esafety.gov.au` (its own
subdomain, unaffected) and `scamwatch.gov.au`. Real crawl attempt showed:
`robots.txt` and `sitemap.xml` fetched fine, but every single content page
timed out — consistent with bot-management blocking automated clients
(our crawler identifies honestly via User-Agent, so this reads as a
deliberate block, not a bug on our end; see stage 01 circuit breaker,
which exists specifically because of this run).

Decision: drop it rather than attempt to evade the block (spoofing a
browser identity to get past bot-detection isn't something this project
does). If eSafety's guide content becomes worth pursuing later, the right
path is asking the client whether an API or data-sharing arrangement
exists — not a cleverer crawler.

## my.gov.au — added, 2026-09-30

Server-rendered (Adobe AEM), so a normal honest live crawl works: same
User-Agent, robots.txt and crawl-delay handling as every other domain.
Two differences, configured in `rag/config/source_strategies.json`
(strategy `live_scoped`, code in `rag/s01_sources.py`):
- URL normalisation: the same page is linked as `/en/x`,
  `/content/mygov/en/x.html` and with `:443`. These collapse to one URL
  before fetching, so duplicates never cost a request or a max_pages slot.
- Scope: only `/en/about` (help pages), `/en/services/ageing` and
  `/en/languages`. The rest of the host is general government-services
  browsing plus the sign-in app. A page that redirects out of scope (e.g.
  into sign-in) is dropped.

Licence: CC BY 3.0 AU, attribute to Services Australia, © Commonwealth of
Australia.

## esafety.gov.au — re-added, 2026-09-30

The live site still blocks automated clients, and the 2026-09-01 decision
stands: we don't try to get past that. What changed is the source: stage 01
now reads the Internet Archive's public copies of eSafety pages through its
documented APIs (Wayback Machine CDX listing + raw `id_` snapshots),
strategy `wayback` in `rag/config/source_strategies.json`. No request for
page content goes to esafety.gov.au itself (only robots.txt, which we still
honour).

- Stored URLs are the original esafety.gov.au URLs, so citations point at
  eSafety, not archive.org.
- `fetched_at` is the archive snapshot date, so answers can say how
  current the content is. Only captures since `archive_from` are used.
- The eSafety Guide is excluded: it's outside eSafety's CC BY 4.0 licence.

Still worth doing: ask eSafety (enquiries@esafety.gov.au) or the client
whether our crawler can be allowlisted. If yes, change the strategy to
`"live"` and delete `.cache/html/esafety.gov.au` to re-crawl fresh.
