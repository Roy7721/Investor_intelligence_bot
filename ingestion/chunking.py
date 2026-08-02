import re
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language


def read_markdown(markdown_file: str) -> str:
    """Read a markdown file's content as UTF-8 text."""
    return Path(markdown_file).read_text(encoding="utf-8")


def split_into_table_and_prose_blocks(content: str) -> tuple[list[str], list[str]]:
    """
    Split raw markdown into table blocks and prose blocks.

    A "block" is any chunk of text separated by a blank line (\\n\\n or more).
    A block is classified as a table if any of its lines start or end with '|'.
    <br> tags (leftover from PDF-to-markdown conversion) are stripped from
    every block, regardless of type.
    """
    blocks = re.split(r"\n{2,}", content)

    prose_blocks = []
    table_blocks = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        is_table = any(
            line.strip().startswith("|") or line.strip().endswith("|")
            for line in lines
        )

        block = re.sub("<br>", "", block)

        if is_table:
            table_blocks.append(block)
        else:
            prose_blocks.append(block)

    return table_blocks, prose_blocks


def chunk_markdown(
    markdown_file: str,
    source_company: str,
    filing_year: int,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[dict]:
    """
    Convert a markdown 10-K file into a list of chunk dicts, ready for embedding.

    Tables are kept atomic (one table = one chunk, never split).
    Prose is split with RecursiveCharacterTextSplitter into ~chunk_size pieces.

    Each chunk dict has: text, content_type ("table" | "prose"),
    source_company, filing_year.
    """
    content = read_markdown(markdown_file)
    table_blocks, prose_blocks = split_into_table_and_prose_blocks(content)

    prose_splitter = RecursiveCharacterTextSplitter.from_language(
        language=Language.MARKDOWN,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        #language = Language.MARKDOWN
    )

    chunks = []

    for block in table_blocks:
        chunks.append({
            "text": block,
            "content_type": "table",
            "source_company": source_company,
            "filing_year": filing_year,
        })

    for block in prose_blocks:
        sub_chunks = prose_splitter.split_text(block)
        for sc in sub_chunks:
            chunks.append({
                "text": sc,
                "content_type": "prose",
                "source_company": source_company,
                "filing_year": filing_year,
            })

    return chunks


if __name__ == "__main__":
    chunks = chunk_markdown(
        markdown_file="./data/markdown/2024_Apple.md",
        source_company="Apple",
        filing_year=2024,
    )

    table_count = sum(1 for c in chunks if c["content_type"] == "table")
    prose_count = sum(1 for c in chunks if c["content_type"] == "prose")

    print(f"Generated {len(chunks)} chunks total")
    print(f"  - {table_count} table chunks")
    print(f"  - {prose_count} prose chunks")

    for chunk in chunks[:3]:
        print("=" * 80)
        print(f"[{chunk['content_type']}] {chunk['source_company']} {chunk['filing_year']}")
        print(chunk["text"][:300])