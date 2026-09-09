# Domain decisions

Kept out of `approved_domains.json`'s own schema (which just lists current
state) so a future teammate can see *why* a domain isn't there, not just
that it isn't.

## esafety.gov.au - dropped, 2026-09-01

Approved initially alongside `beconnected.esafety.gov.au` (its own
subdomain, unaffected) and `scamwatch.gov.au`. Real crawl attempt showed:
`robots.txt` and `sitemap.xml` fetched fine, but every single content page
timed out - consistent with bot-management blocking automated clients
(our crawler identifies honestly via User-Agent, so this reads as a
deliberate block, not a bug on our end; see stage 01 circuit breaker,
which exists specifically because of this run).

Decision: drop it rather than attempt to evade the block (spoofing a
browser identity to get past bot-detection isn't something this project
does). If eSafety's guide content becomes worth pursuing later, the right
path is asking the client whether an API or data-sharing arrangement
exists - not a cleverer crawler.
