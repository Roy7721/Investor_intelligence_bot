"""
Audit cached chunks for headings pymupdf4llm failed to mark with '#'.

For each undetected heading it reports the blast radius: how many
following chunks carry a heading that is now stale, i.e. wrong.

Run:  python heading_audit.py <cache_dir>
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

UNDERLINED = re.compile(r"^<u>(.{3,90}?)</u>$")


def is_undetected_heading(line: str) -> bool:
    """A heading-shaped line that pymupdf4llm left unmarked."""
    s = line.strip()
    m = UNDERLINED.fullmatch(s)
    if not m:
        return False
    inner = m.group(1)
    return bool(
        re.search(r"[A-Za-z]{3,}", inner)
        and not inner.rstrip().endswith((".", ",", ";", ":"))
    )


def split_heading_context(text: str) -> tuple[str, list[str]]:
    """Separate the carried-forward heading lines from the chunk body."""
    lines = text.split("\n")
    heading_lines, i = [], 0
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        heading_lines.append(lines[i].strip())
        i += 1
    return " / ".join(heading_lines), lines[i:]


def audit(cache_file: Path) -> None:
    chunks = json.loads(cache_file.read_text(encoding="utf-8"))
    print(f"\n{'=' * 70}\n{cache_file.name}  —  {len(chunks)} chunks\n{'=' * 70}")

    contexts = [split_heading_context(c["text"])[0] for c in chunks]

    culprits = []
    for i, chunk in enumerate(chunks):
        _, body = split_heading_context(chunk["text"])
        for line in body:
            if is_undetected_heading(line):
                culprits.append((i, line.strip(), contexts[i]))

    if not culprits:
        print("No undetected headings found.")
        return

    total_affected = 0
    by_context = defaultdict(int)

    for idx, heading, wrong_context in culprits:
        # Everything after this point carrying the stale heading is mislabeled,
        # until the carried context changes.
        affected = 0
        for j in range(idx + 1, len(chunks)):
            if contexts[j] != wrong_context:
                break
            affected += 1

        tables = sum(
            1
            for j in range(idx, idx + affected + 1)
            if chunks[j].get("content_type") == "table"
        )
        total_affected += affected + 1
        by_context[wrong_context] += affected + 1

        print(f"\n  chunk {idx}: {heading}")
        print(f"    wrongly labeled as: {wrong_context or '(no heading)'}")
        print(f"    chunks affected: {affected + 1}  (tables: {tables})")

    print(f"\n  {'-' * 66}")
    print(f"  undetected headings : {len(culprits)}")
    print(f"  chunks mislabeled   : {total_affected} / {len(chunks)} "
          f"({100 * total_affected / len(chunks):.1f}%)")
    print(f"  distinct wrong labels: {len(by_context)}")


def main() -> None:
    cache_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/cache")
    files = sorted(cache_dir.glob("*.json"))
    if not files:
        print(f"No cache files found in {cache_dir}")
        return
    for f in files:
        if f.name.endswith(".partial.json"):
            continue
        audit(f)


if __name__ == "__main__":
    main()
