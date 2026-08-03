"""
Repair raw_fallback tables.

Re-runs table-to-text conversion ONLY on chunks marked raw_fallback,
updates the cache in place, and re-embeds the whole filing.

Usage (from project root):
    python .\\Scripts\\repair_tables.py Apple_2024_b9dc49ea295eea1d_v5.json

Re-embedding the whole filing is safe: embed_and_store deletes this
company+year before inserting, so no duplicates or orphans.
"""

import json
import sys
from pathlib import Path

# Make project root importable when this file is run directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ingestion.chunking_v4 import table_to_text
from vector_store.vector_store import embed_and_store


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python .\\Scripts\\repair_tables.py <cache-filename.json>")

    cache_file = ROOT / "data" / "cache" / sys.argv[1]
    if not cache_file.exists():
        raise SystemExit(f"Cache file not found: {cache_file}")

    chunks = json.loads(cache_file.read_text(encoding="utf-8"))

    targets = [
        i for i, c in enumerate(chunks)
        if c.get("conversion_status") == "raw_fallback"
    ]

    if not targets:
        print("No raw_fallback chunks — nothing to repair.")
        return

    print(f"Repairing {len(targets)} chunk(s): {targets}")

    repaired = 0
    for n, i in enumerate(targets, 1):
        text, status = table_to_text(chunks[i]["text"])
        chunks[i]["text"] = text
        chunks[i]["conversion_status"] = status
        print(f"  {n}/{len(targets)} (chunk {i}): {status}")
        if status == "converted":
            repaired += 1

    cache_file.write_text(json.dumps(chunks), encoding="utf-8")
    print(f"Cache updated: {repaired}/{len(targets)} repaired.")

    embed_and_store(chunks=chunks, name="investor_intelligence")


if __name__ == "__main__":
    main()
