import re
from collections import Counter
from pathlib import Path


def find_repeating_blocks(raw_blocks: list[str], min_repeats: int = 5) -> dict:
    """Dry-run: shows what WOULD be flagged as boilerplate, without removing anything."""
    normalized = [re.sub(r"\d+", "#", b) for b in raw_blocks]
    counts = Counter(normalized)

    flagged = {}
    for block, norm in zip(raw_blocks, normalized):
        if counts[norm] >= min_repeats:
            flagged.setdefault(norm, []).append(block)

    return flagged


if __name__ == "__main__":
    content = Path("./apple_full.md").read_text(encoding="utf-8")
    raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]

    flagged = find_repeating_blocks(raw_blocks)

    print(f"Total blocks: {len(raw_blocks)}")
    print(f"Distinct repeating patterns found: {len(flagged)}")
    print("=" * 80)

    for norm_pattern, examples in flagged.items():
        print(f"Repeats {len(examples)} times. Example: {examples[0][:120]}")
        print("-" * 80)