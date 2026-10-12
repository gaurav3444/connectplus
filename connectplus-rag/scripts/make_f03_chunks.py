"""Regenerate rag/fixtures/f03_chunks.json from f01_pages.json.

Runs the real stage 02 and stage 03 (BGE-m3's own tokenizer) over the six
committed fixture pages, so the handoff chunks are what the pipeline
actually produces, not hand-written approximations. Re-run after any change
to extraction or chunking:

    python scripts/make_f03_chunks.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rag.s02_extract import extract_pages, load_extraction_inputs_from_fixture  # noqa: E402
from rag.s03_chunk import chunk_docs  # noqa: E402

FIXTURES = REPO_ROOT / "rag" / "fixtures"

docs, _ = extract_pages(load_extraction_inputs_from_fixture(FIXTURES / "f01_pages.json", FIXTURES))
chunks = chunk_docs(docs)
out = FIXTURES / "f03_chunks.json"
out.write_text(
    json.dumps([c.model_dump(mode="json") for c in chunks], ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"{len(chunks)} chunks from {len(docs)} docs -> {out.relative_to(REPO_ROOT)}")
