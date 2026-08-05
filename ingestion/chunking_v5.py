from pathlib import Path
import re
from config.config import MIN_BODY_CHARS
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

def read_markdown(markdown_path : str):
    return Path(markdown_path).read_text(encoding='utf-8')


def is_table_block(block:str) -> bool:
    return any(line.strip().startswith("|") or line.strip().endswith("|")
               for line in block.split('\n'))


HEADING_RE = re.compile(r"^(#{1,6})\s+\S")


def heading_level(block: str) -> int | None:
    """Markdown heading level 1-6, or None if this block isn't a heading."""
    stripped = block.strip()
    if "\n" in stripped:
        return None
    match = HEADING_RE.match(stripped)
    return len(match.group(1)) if match else None



def is_degenerate(block: str) -> bool:
    """Blocks with essentially no content"""
    body = re.sub(r"[#*_<>/\s]", "", block)
    return len(body) < MIN_BODY_CHARS

def attach_headings(blocks:list[str])-> list[tuple[str,str]]:

    context = ""
    
    pairs: list[tuple[str, str]] = []
    stack: dict[int, str] = {}

    for block in blocks:
        level = heading_level(block)

        if level is not None:
            # Entering a level-N section closes every deeper section.
            stack = {lvl: text for lvl, text in stack.items() if lvl < level}
            stack[level] = block.strip()
            continue                       # heading leaves the block stream

        context = "\n".join(stack[lvl] for lvl in sorted(stack))
        pairs.append((block, context))

    return pairs

def chunk_markdown(
    markdown_file: str,
    source_company: str,
    filing_year: int,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    min_repeats: int = 5,
) -> list[dict]:
    content = read_markdown(markdown_path=markdown_file)
    raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]

    pairs = attach_headings(raw_blocks)

    prose_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,

        )

    chunks: list[dict] = []
    consumed: set[int] = set()

    for i, (block, context) in enumerate(pairs):
            if i in consumed:
                continue
    
            if is_table_block(block):
                caption = None
                if i - 1 >= 0 and (i - 1) not in consumed:
                    prev_block, prev_context = pairs[i - 1]
                    # Same context = same section, so the preceding block really
                    # is about this table. Different context means a heading sat
                    # between them, i.e. the table opens a new section and the
                    # block behind it belongs to the previous one — pairing there
                    # would mislabel the table AND delete a real paragraph.
                    if not is_table_block(prev_block) and prev_context == context:
                        caption = prev_block
                        consumed.add(i - 1)
    
                parts = [p for p in (context, caption, block) if p]
                chunks.append({
                    "text": "\n".join(parts),
                    "content_type": "table",
                    "source_company": source_company,
                    "filing_year": filing_year,
                    "heading_context": context,
                    "conversion_status": "pending",
                })
            else:
                for sub_chunk in prose_splitter.split_text(block):
                    parts = [p for p in (context, sub_chunk) if p]
                    chunks.append({
                        "text": "\n".join(parts),
                        "content_type": "prose",
                        "source_company": source_company,
                        "filing_year": filing_year,
                        "heading_context": context,
                        "conversion_status": "n/a",
                    })
    
    return chunks








    