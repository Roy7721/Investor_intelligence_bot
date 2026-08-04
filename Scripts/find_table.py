"""
Find a table in the cached chunks and look at what surrounds it.

Answers three questions:
  1. Is the table in the cache at all?
  2. What does its text look like after LLM conversion?
  3. What chunks sit immediately before and after it?

Run:  python find_table.py data/cache/Microsoft_2024_364c4de7f674688d_v6.json intangible
"""

import json
import sys
from pathlib import Path


def preview(chunk: dict, width: int = 180) -> str:
    text = " ".join(chunk["text"].split())
    return text[:width]


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: python find_table.py <cache_file.json> <keyword>")
        return

    cache_file = Path(sys.argv[1])
    keyword = sys.argv[2].lower()

    chunks = json.loads(cache_file.read_text(encoding="utf-8"))
    print(f"{cache_file.name} — {len(chunks)} chunks\n")

    hits = [
        i for i, c in enumerate(chunks)
        if keyword in c["text"].lower()
    ]

    tables = [i for i in hits if chunks[i]["content_type"] == "table"]
    prose = [i for i in hits if chunks[i]["content_type"] != "table"]

    print(f"Chunks containing '{keyword}': {len(hits)}")
    print(f"   tables : {len(tables)}")
    print(f"   prose  : {len(prose)}\n")

    if not tables:
        print("NO TABLE CHUNK CONTAINS THIS WORD.")
        print("The table is either missing, or its converted text")
        print("does not use this word.\n")

    print("=" * 72)
    print("TABLE CHUNKS CONTAINING THE KEYWORD")
    print("=" * 72)
    for i in tables:
        c = chunks[i]
        print(f"\n[{i}] status={c.get('conversion_status')}")
        print(f"    {preview(c)}")

    print("\n" + "=" * 72)
    print("NEIGHBOURS OF EACH PROSE HIT")
    print("(shows what sits around the captions, in document order)")
    print("=" * 72)
    for i in prose:
        print(f"\n--- around chunk {i} ---")
        for j in range(max(0, i - 2), min(len(chunks), i + 3)):
            c = chunks[j]
            mark = ">>" if j == i else "  "
            print(f"{mark} [{j}] ({c['content_type']:5}) {preview(c, 120)}")


if __name__ == "__main__":
    main()
