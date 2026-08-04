"""
Find lines pymupdf4llm marked as headings ('#') that are actually
units captions belonging to the table below them.

Prints every match so you can eyeball it before adopting a demotion rule.
A single real section heading in this list means DO NOT adopt.

Run:  python units_caption_audit.py data/markdown
"""

import re
import sys
from pathlib import Path

UNIT_WORDS = re.compile(
    r"in\s+(millions|thousands|billions)|except\s+|per\s+share|shares\s+in\s+",
    re.IGNORECASE,
)


def strip_wrappers(text: str) -> str:
    """Remove markdown decoration to see the bare text."""
    s = text.strip()
    s = re.sub(r"^#{1,6}\s*", "", s)      # remove ###
    s = s.replace("<u>", "").replace("</u>", "")   # remove underline tags
    return s.strip().strip("*_").strip()  # remove * and _ from both ends


def looks_like_units_caption(bare: str) -> bool:
    """Fully parenthesized and mentioning units."""
    return (
        bare.startswith("(")
        and bare.endswith(")")
        and bool(UNIT_WORDS.search(bare))
    )


def audit(md_file: Path) -> int:
    lines = md_file.read_text(encoding="utf-8").split("\n")
    hits = 0

    print(f"\n{'=' * 70}\n{md_file.name}\n{'=' * 70}")

    for i, line in enumerate(lines):
        if not line.lstrip().startswith("#"):
            continue
        bare = strip_wrappers(line)
        if looks_like_units_caption(bare):
            hits += 1
            nxt = next(
                (l.strip() for l in lines[i + 1: i + 6] if l.strip()), ""
            )
            print(f"\n  line {i}: {line.strip()}")
            print(f"    bare    : {bare}")
            print(f"    follows : {nxt[:70]}")
            print(f"    is table below? {'YES' if nxt.startswith('|') else 'no'}")

    total_headings = sum(1 for l in lines if l.lstrip().startswith("#"))
    print(f"\n  headings total : {total_headings}")
    print(f"  caught by rule : {hits}")
    return hits


def main() -> None:
    md_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/markdown")
    files = sorted(md_dir.glob("*.md"))
    if not files:
        print(f"No markdown files found in {md_dir}")
        return
    grand = sum(audit(f) for f in files)
    print(f"\n{'=' * 70}\nTOTAL caught across all filings: {grand}")
    print("Inspect every one. Any real section heading in the list = do not adopt.")


if __name__ == "__main__":
    main()
