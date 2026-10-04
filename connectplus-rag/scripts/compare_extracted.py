"""Compare an old and a new stage 02 output file for one domain.

    python scripts/compare_extracted.py .cache/extracted_before/scamwatch.gov.au.json \
                                        .cache/extracted/scamwatch.gov.au.json

Tells you whether re-running `chunk` + `index` for that domain is needed:
if nothing changed, it isn't.
"""

from __future__ import annotations

import json
import sys

old = {d["url"]: d for d in json.load(open(sys.argv[1], encoding="utf-8"))}
new = {d["url"]: d for d in json.load(open(sys.argv[2], encoding="utf-8"))}

title_changed = [u for u in old.keys() & new.keys() if old[u]["title"] != new[u]["title"]]
text_changed = [u for u in old.keys() & new.keys()
                if old[u]["text"] != new[u]["text"] or old[u]["content_xml"] != new[u]["content_xml"]]

print(f"docs: {len(old)} before -> {len(new)} after")
print(f"titles changed:  {len(title_changed)}")
print(f"content changed: {len(text_changed)}")
for u in (title_changed + text_changed)[:5]:
    print(f"  e.g. {u}")
print("-> NO CHANGE: no need to re-chunk/re-index this domain" if not (title_changed or text_changed
      or old.keys() != new.keys()) else "-> CHANGED: re-run chunk + index for this domain")
