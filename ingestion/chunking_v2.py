import re
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter


def read_markdown(markdown_file: str) -> str:
    """Read a markdown file's content as UTF-8 text."""
    return Path(markdown_file).read_text(encoding="utf-8")


def is_table_block(block: str) -> bool:
    """A block counts as a table if any of its lines start or end with '|'."""
    lines = block.split("\n")
    return any(
        line.strip().startswith("|") or line.strip().endswith("|")
        for line in lines
    )


def chunk_markdown(
    markdown_file: str,
    source_company: str,
    filing_year: int,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """
    Convert a markdown 10-K file into a list of chunk dicts, ready for embedding.

    Design decisions (from our debugging session):
    - Blocks are walked in document order (not split into two upfront groups),
      so a table can be paired with the prose block that came right before it.
    - LOOK-BEHIND ONLY: a table only grabs the block immediately preceding it,
      if that block is prose and hasn't already been used as another table's
      caption. We deliberately do NOT look ahead — testing showed look-ahead
      can misattach an unrelated table's intro sentence to the wrong table
      when two tables appear close together (e.g. Products table wrongly
      grabbing the Services table's intro).
    - Every chunk (table or prose) gets a synthetic header
      ("{company} {year} 10-K") prepended, so retrieval has literal
      company/year words to match against, even inside a bare table.
    - Tables are kept atomic (never split), even if that makes some chunks
      much larger than chunk_size.
    """
    content = read_markdown(markdown_file)
    raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]
    raw_blocks = [re.sub("<br>", "", b) for b in raw_blocks]

    prose_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    header = f"{source_company} {filing_year} 10-K\n"

    chunks = []
    consumed_indices = set()  # prose blocks already used as a table's caption

    for i, block in enumerate(raw_blocks):
        if i in consumed_indices:
            continue  # already attached to an earlier table as its caption

        if is_table_block(block):
            caption_before = None

            if i - 1 >= 0 and (i - 1) not in consumed_indices:
                prev_block = raw_blocks[i - 1]
                if not is_table_block(prev_block):
                    caption_before = prev_block
                    consumed_indices.add(i - 1)

            parts = [header]
            if caption_before:
                parts.append(caption_before)
            parts.append(block)
            text = "\n".join(parts)

            chunks.append({
                "text": text,
                "content_type": "table",
                "source_company": source_company,
                "filing_year": filing_year,
            })

        else:
            for sub_chunk in prose_splitter.split_text(block):
                chunks.append({
                    "text": f"{header}{sub_chunk}",
                    "content_type": "prose",
                    "source_company": source_company,
                    "filing_year": filing_year,
                })

    return chunks


if __name__ == "__main__":
    chunks = chunk_markdown(
        markdown_file="./apple_full.md",
        source_company="Apple",
        filing_year=2024,
    )

    table_count = sum(1 for c in chunks if c["content_type"] == "table")
    prose_count = sum(1 for c in chunks if c["content_type"] == "prose")

    print(f"Generated {len(chunks)} chunks total")
    print(f"  - {table_count} table chunks")
    print(f"  - {prose_count} prose chunks")

    # sanity check: find a table chunk and confirm it carries caption + header
    for chunk in chunks:
        if chunk["content_type"] == "table":
            print("=" * 80)
            print("SAMPLE TABLE CHUNK (should start with header, then caption, then table):")
            print(chunk["text"][:500])
            break
