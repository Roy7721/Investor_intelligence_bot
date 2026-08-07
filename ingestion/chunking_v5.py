from pathlib import Path
import re
from config.config import MIN_BODY_CHARS
from langchain_text_splitters import RecursiveCharacterTextSplitter
from collections import Counter

def read_markdown(markdown_path : str):
    return Path(markdown_path).read_text(encoding='utf-8')


def is_table_block(block:str) -> bool:
    return any(line.strip().startswith("|") or line.strip().endswith("|")
               for line in block.split('\n'))

UNITS_RE = re.compile(r"^\(?\s*in\s+(millions|thousands|billions)\b(?:,\s*[a-zA-Z]+)?", re.I)

def remove_repeating_boilerplate(blocks: list[str], min_repeats: int = 5) -> list[str]:
    normalized = [re.sub(r"\d+", "#", b) for b in blocks]
    counts = Counter(normalized)

    kept: list[str] = []
    for block, norm in zip(blocks, normalized):
        if counts[norm] >= min_repeats and not UNITS_RE.match(block.strip("*_ ")):
            continue
        kept.append(block)
    return kept


HEADING_RE = re.compile(r"^(#{1,6})\s+\S")


def heading_level(block: str) -> int | None:
    """Markdown heading level 1-6, or None if this block isn't a heading."""
    stripped = block.strip()
    if "\n" in stripped:
        return None
    match = HEADING_RE.match(stripped)
    return len(match.group(1)) if match else None



def is_degenerate(block:str)-> bool:
    body = re.sub(r"[#*_<>/\s-]", "", block)
    if len(body) < MIN_BODY_CHARS:
        if block.strip().upper() in {"N/A", "NA", "YES", "NO"}:
            return False
        return True
    return False

def attach_headings(blocks:list[str])-> list[tuple[str,str]]:

    
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

    raw_blocks = remove_repeating_boilerplate(raw_blocks, min_repeats=min_repeats)

    raw_blocks = [b.replace("\\$", "$") for b in raw_blocks]


    pairs = attach_headings(raw_blocks)

    pairs = [(b, ctx) for b, ctx in pairs if is_table_block(b) or not is_degenerate(b)]

    prose_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,

        )

    chunks: list[dict] = []
    captions: dict[int, str] = {}
    consumed: set[int] = set()

    for i, (block, context) in enumerate(pairs):
        if not is_table_block(block):
            continue
        parts: list[str] = []
        j = i - 1
        while j >= 0 and len(parts) < 3:
            if j in consumed:
                break
            prev_block, prev_context = pairs[j]
            if is_table_block(prev_block) or prev_context != context:
                break
            parts.append(prev_block)
            consumed.add(j)
            j -= 1
        if parts:
            captions[i] = "\n".join(reversed(parts))

    # Pass 2: emit.
    for i, (block, context) in enumerate(pairs):
        if i in consumed:
            continue

        if is_table_block(block):
            parts = [p for p in (context, captions.get(i), block) if p]
            chunks.append({"text": "\n".join(parts),
                            "content_type": "table",
                            "source_company": source_company,
                            "filing_year": filing_year,})
        else:
            for sub_chunk in prose_splitter.split_text(block):
                parts = [p for p in (context, sub_chunk) if p]
                chunks.append({
                    "text": "\n".join(parts),
                    "content_type": "prose",
                    "source_company": source_company,
                    "filing_year": filing_year,
                })
    
    return chunks










    