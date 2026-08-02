import re
from collections import Counter
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from confiq.confiq import LLM_MODEL
import time

def read_markdown(markdown_file: str) -> str:
    """Read a markdown file's content as UTF-8 text."""
    return Path(markdown_file).read_text(encoding="utf-8")


def remove_repeating_boilerplate(raw_blocks: list[str], min_repeats: int = 5) -> list[str]:
    """
    Detects and removes blocks that repeat near-identically many times across
    the document (page footers, running headers, copyright lines, standard
    "see notes" boilerplate). Real content doesn't repeat like this.

    Works by normalizing digits away (so "...page 1", "...page 2" count as
    the same underlying pattern), counting occurrences of each normalized
    pattern, and dropping any ORIGINAL block whose pattern repeats at least
    min_repeats times. The original (non-normalized) block is what's kept,
    so real numbers are never altered — normalization is only ever used for
    counting.
    """
    normalized = [re.sub(r"\d+", "#", b) for b in raw_blocks]
    counts = Counter(normalized)

    cleaned_blocks = []
    for block, norm in zip(raw_blocks, normalized):
        if counts[norm] >= min_repeats:
            continue  # this pattern repeats too often — treat as boilerplate
        cleaned_blocks.append(block)

    return cleaned_blocks


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
    min_repeats: int = 5,
) -> list[dict]:
    """
    Convert a markdown 10-K file into a list of chunk dicts, ready for embedding.

    v3 changes vs v2:
    - Repeating boilerplate blocks (page footers, running headers, copyright
      lines, standard notes) are detected and removed BEFORE chunking, so
      they never get embedded or take up a retrieval slot. This was needed
      because the synthetic header fix (below) accidentally made short,
      repeated footer text ("Apple Inc. | 2024 Form 10-K | <page>") rank
      unusually well against questions containing the company name and year
      — it said "Apple 2024" more densely than real content did, crowding
      out the actual financial tables from top-K retrieval results.

    Carried over from v2:
    - Blocks are walked in document order, tables paired with the prose
      block immediately preceding them (look-behind only — look-ahead was
      tried and dropped after it was found to misattach a table's caption
      to the wrong neighboring table).
    - Every chunk (table or prose) gets a synthetic header
      ("{company} {year} 10-K") prepended, so retrieval has literal
      company/year words to match against, even inside a bare table.
    - Tables are kept atomic (never split), even if that makes some chunks
      much larger than chunk_size.
    """
    content = read_markdown(markdown_file)
    raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]
    raw_blocks = [re.sub("<br>", "", b) for b in raw_blocks]
    raw_blocks = remove_repeating_boilerplate(raw_blocks, min_repeats=min_repeats)

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


TABLE_TO_TEXT_SYSTEM_PROMPT = """You convert financial tables into clear, natural-language sentences.
Rewrite every row of the given table as one or more complete sentences, preserving every number and label exactly.
Do not summarize, round, or omit any figures. Do not add commentary or analysis.
"""
import time
from openai import RateLimitError

def table_to_text(table_chunk_text: str, max_retries: int = 3) -> str:
    for attempt in range(max_retries):
        try:
            messages = [
                {"role": "system", "content": TABLE_TO_TEXT_SYSTEM_PROMPT},
                {"role": "user", "content": table_chunk_text},
            ]
            response = LLM_MODEL.invoke(messages)
            result = response.content.strip() if response.content else ""
            return result if result else table_chunk_text  # fallback if empty

        except RateLimitError:
            wait_time = 5 * (attempt + 1)  # 5s, 10s, 15s — growing backoff
            print(f"Rate limited, waiting {wait_time}s before retry...")
            time.sleep(wait_time)

    print("Max retries hit — falling back to raw table text.")
    return table_chunk_text
    messages = [
        {"role": "system", "content": TABLE_TO_TEXT_SYSTEM_PROMPT},
        {"role": "user", "content": table_chunk_text},
    ]
    response = LLM_MODEL.invoke(messages)
    result = response.content.strip() if response.content else ""

    if not result:
        return table_chunk_text  # fallback: keep raw table rather than storing nothing

    return result

def convert_table_chunks(chunks: list[dict]) -> list[dict]:
    """Replaces every table chunk's text with an LLM-converted natural-language version."""
    for chunk in chunks:
        if chunk["content_type"] == "table":
            chunk["text"] = table_to_text(chunk["text"])
            time.sleep(2.5) 
    return chunks

if __name__ == "__main__":
    content = read_markdown("./data/markdown/2024_Tesla.md")
    raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]
    raw_blocks = [re.sub("<br>", "", b) for b in raw_blocks]
    raw_blocks = remove_repeating_boilerplate(raw_blocks, min_repeats=5)

    for i, block in enumerate(raw_blocks):
        if "consolidated financial statement details" in block:
            print(f"Found at index {i}")
            print(f"THIS BLOCK: {block[:150]}")
            print(f"NEXT BLOCK (index {i+1}): {raw_blocks[i+1][:150]}")
            print(f"Is next block a table? {is_table_block(raw_blocks[i+1])}")

    
