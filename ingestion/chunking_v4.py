"""
chunking_v4.py — PIPELINE_VERSION 5

Changes vs v3
-------------
1. Synthetic header REMOVED.
   v3 prepended "{company} {year} 10-K" to every chunk. A string present in
   all chunks cannot discriminate between them, so it added no ranking
   signal — but it did dominate the embedding of any low-content block,
   parking content-free chunks right where every company/year query lands.
   Company and year live in metadata, where they can be filtered exactly.

2. Heading blocks are extracted and carried forward.
   Markdown headings ("#### Revenue Recognition") were being emitted as
   their own chunks: short, topically dense, zero information — ideal
   decoys. They are now attached as context to the content blocks they
   head, and carried forward until the next heading replaces them.
   Consecutive headings accumulate (h4 + h4 + content -> one chunk).

3. Caption pairing is scoped to a section.
   A table absorbs the block before it only when both share the same
   heading context. Different context means a heading sat between them,
   so the table opens a new section and the block behind it belongs to
   the previous one — pairing there mislabels the table and deletes a
   real paragraph.
   Cost: a caption separated from its table by a subheading stays an
   orphan. Accepted, because the table still carries its own heading,
   table-to-text makes it self-describing, and the table-guaranteed
   retrieval merge surfaces it regardless of rank. The alternative was
   inferring intent from phrasing ("does this sentence announce a
   table?"), which is the kind of heuristic Rule A was chosen to avoid.

4. Degenerate blocks are dropped.
   Cover-page debris ("x", "o") is removed. The threshold is deliberately
   conservative — see MIN_BODY_CHARS.

5. Table conversion outcome is recorded.
   table_to_text() now reports whether it converted or fell back to raw
   table syntax, stored as conversion_status. Silent degradation was
   previously invisible.
"""

import re
import time
from collections import Counter
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import RateLimitError

from confiq.confiq import LLM_MODEL


PIPELINE_VERSION = 5

# Deliberately conservative. Only kills blocks with essentially no content
# ("x", "o" checkbox marks). Short-but-real answers like "None." survive,
# because after the heading merge they carry their section heading and
# become meaningful ("Item 4. Mine Safety Disclosures / None.").
# Re-measure with inspect_chunks.py before raising this.
MIN_BODY_CHARS = 3


# --------------------------------------------------------------------------
# Block preparation
# --------------------------------------------------------------------------

def read_markdown(markdown_file: str) -> str:
    """Read a markdown file's content as UTF-8 text."""
    return Path(markdown_file).read_text(encoding="utf-8")


def remove_repeating_boilerplate(raw_blocks: list[str], min_repeats: int = 5) -> list[str]:
    """
    Remove blocks that repeat near-identically across the document (page
    footers, running headers, copyright lines). Real content doesn't repeat
    like this.

    Digits are normalized away for COUNTING only, so "...page 1" and
    "...page 2" count as the same pattern. The original block is what's
    kept or dropped — real numbers are never altered.
    """
    normalized = [re.sub(r"\d+", "#", b) for b in raw_blocks]
    counts = Counter(normalized)

    return [
        block
        for block, norm in zip(raw_blocks, normalized)
        if counts[norm] < min_repeats
    ]


def is_table_block(block: str) -> bool:
    """A block counts as a table if any of its lines start or end with '|'."""
    return any(
        line.strip().startswith("|") or line.strip().endswith("|")
        for line in block.split("\n")
    )


def is_heading_block(block: str) -> bool:
    """
    A block is a heading if it is a single line beginning with a markdown
    '#' marker.

    Rule A (structural), chosen over a length threshold: this reads the
    document's own markup rather than inferring from size. Its failure mode
    is inherited from pymupdf4llm's heading detection — it may MISS a
    heading, but it never merges real content into the wrong section, which
    a length rule would (e.g. "None." is short but is real content).
    """
    stripped = block.strip()
    if "\n" in stripped:
        return False
    return stripped.startswith("#")


def is_degenerate(block: str) -> bool:
    """Blocks with essentially no content — cover-page checkbox marks etc."""
    body = re.sub(r"[#*_<>/\s]", "", block)
    return len(body) < MIN_BODY_CHARS


def attach_headings(raw_blocks: list[str]) -> list[tuple[str, str]]:
    """
    Remove heading blocks from the stream and attach them as context to the
    content blocks that follow.

    Returns a list of (content_block, heading_context) pairs.

    Consecutive headings accumulate:
        #### Results of Operations
        #### Revenues
        <paragraph>
    -> one pair, context = both headings.

    Context carries forward until the next heading appears, so every
    paragraph in a section is labelled, not just the first.
    """
    pairs: list[tuple[str, str]] = []
    pending: list[str] = []
    context = ""
    prev_was_heading = False

    for block in raw_blocks:
        if is_heading_block(block):
            if not prev_was_heading:
                pending = []          # new heading run — start fresh
            pending.append(block.strip())
            prev_was_heading = True
            continue

        if pending:
            context = "\n".join(pending)
            pending = []
        prev_was_heading = False
        pairs.append((block, context))

    return pairs


# --------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------

def chunk_markdown(
    markdown_file: str,
    source_company: str,
    filing_year: int,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    min_repeats: int = 5,
) -> list[dict]:
    """Convert a markdown 10-K into chunk dicts ready for embedding."""
    content = read_markdown(markdown_file)

    raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]
    raw_blocks = [re.sub("<br>", "", b) for b in raw_blocks]
    raw_blocks = remove_repeating_boilerplate(raw_blocks, min_repeats=min_repeats)

    # Headings out of the stream first, so caption pairing sees true adjacency.
    pairs = attach_headings(raw_blocks)

    # Degenerate blocks out before pairing, so a stray "x" can never be
    # mistaken for a table's caption.
    pairs = [(b, ctx) for b, ctx in pairs if is_table_block(b) or not is_degenerate(b)]

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
                    "conversion_status": "n/a",
                })

    return chunks


# --------------------------------------------------------------------------
# Table -> natural language
# --------------------------------------------------------------------------

TABLE_TO_TEXT_SYSTEM_PROMPT = """You convert financial tables into clear, natural-language sentences.
Rewrite every row of the given table as one or more complete sentences, preserving every number and label exactly.
Do not summarize, round, or omit any figures. Do not add commentary or analysis.
"""
import re

LONG_WAIT_THRESHOLD_SECONDS = 90

_WAIT_SPEC_RE = re.compile(r"try again in\s+([0-9hms.]+)", re.IGNORECASE)
_UNIT_RE = re.compile(r"([\d.]+)\s*([hms])")


class QuotaExhausted(Exception):
    """The failure is about the account, not this table."""

    def __init__(self, wait_seconds: float, detail: str):
        self.wait_seconds = wait_seconds
        self.detail = detail
        super().__init__(detail)


def _parse_retry_after(error: Exception) -> float | None:
    """Pull the server's own wait time out of the error text. None if absent."""
    match = _WAIT_SPEC_RE.search(str(error))
    if not match:
        return None
    seconds = 0.0
    found = False
    unit_dict = {"h": 3600.0, "m": 60.0, "s": 1.0}
    for value, unit in _UNIT_RE.findall(match.group(1)):
        seconds += float(value) * unit_dict[unit]
        found = True
    return seconds if found else None

def table_to_text(table_chunk_text: str, max_retries: int = 3) -> tuple[str, str]:
    """
    Convert a table chunk to prose.

    Returns (text, status) where status is one of:
      "converted"    — the LLM produced output
      "raw_fallback" — conversion failed; raw table syntax kept instead

    The status matters: a raw_fallback chunk is stored as bare table syntax,
    which is the exact condition the table-to-text step exists to avoid.
    Without this marker, degradation is invisible after ingestion.
    """
    messages = [
        {"role": "system", "content": TABLE_TO_TEXT_SYSTEM_PROMPT},
        {"role": "user", "content": table_chunk_text},
    ]

    for attempt in range(max_retries):
        try:
            response = LLM_MODEL.invoke(messages)
            result = response.content.strip() if response.content else ""
            if result:
                return result, "converted"
            print("Empty conversion — falling back to raw table text.")
            return table_chunk_text, "raw_fallback"

        except RateLimitError as e:
            print(f"    GROQ ERROR: {e}")
            wait = _parse_retry_after(e)

            if wait is not None and wait > LONG_WAIT_THRESHOLD_SECONDS:
                raise QuotaExhausted(wait, str(e)) from e

            if wait is None:
                wait = 5 * (attempt + 1)
                print(f"    No wait time in the message; backing off {wait}s.")
            else:
                wait += 1
                print(f"    Server asked for {wait:.1f}s; sleeping.")

            if attempt < max_retries - 1:
                time.sleep(wait)

    print("Max retries hit — falling back to raw table text.")
    return table_chunk_text, "raw_fallback"


def convert_table_chunks(chunks: list[dict]) -> list[dict]:
    tables = [c for c in chunks if c["content_type"] == "table"]
    total = len(tables)

    for chunk in tables:
        chunk["conversion_status"] = "pending"

    for n, chunk in enumerate(tables, start=1):
        try:
            text, status = table_to_text(chunk["text"])
        except QuotaExhausted as e:
            print(f"\nABORTING RUN at table {n}/{total}.")
            print(f"  Daily quota exhausted; server asked for {e.wait_seconds / 60:.0f}m.")
            print(f"  {total - n + 1} tables left unconverted.")
            break

        chunk["text"] = text
        chunk["conversion_status"] = status
        print(f"  table {n}/{total}: {status}")
        time.sleep(2.5)

    converted = sum(1 for c in tables if c["conversion_status"] == "converted")
    fallback = sum(1 for c in tables if c["conversion_status"] == "raw_fallback")
    pending = sum(1 for c in tables if c["conversion_status"] == "pending")

    print(f"Tables: {converted} converted, {fallback} raw_fallback, {pending} pending.")
    if pending:
        print(f"WARNING: run aborted — {pending}/{total} tables never attempted.")
    return chunks


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------

if __name__ == "__main__":


    chunks = chunk_markdown(
            markdown_file="./data/markdown/2024_Microsoft.md",
            source_company="Microsoft",
            filing_year=2024,
        )
    
    tables = sum(1 for c in chunks if c["content_type"] == "table")
    print(f"Total chunks: {len(chunks)}  (tables: {tables})")
    
    short = [c for c in chunks if len(c["text"].strip()) < 60]
    print(f"\nChunks under 60 chars: {len(short)}")
    for c in short[:20]:
            print(f"  ({c['content_type']}) {c['text']!r}")
    
    print("\nSample chunks with heading context:")
    for c in chunks[:5]:
            print(f"  ---\n{c['text'][:200]}")
    
    print("\nTable chunks (first 3):")
    for c in [c for c in chunks if c["content_type"] == "table"][10:15]:
            print(f"  ---\n{c['text'][:300]}")

    # import re

    # content = read_markdown("./data/markdown/2024_Apple.md")
    # raw_blocks = [b.strip() for b in re.split(r"\n{2,}", content) if b.strip()]
    # raw_blocks = [re.sub("<br>", "", b) for b in raw_blocks]
    # raw_blocks = remove_repeating_boilerplate(raw_blocks)

    # WRAPPED = re.compile(r"^(?:<u>|\*\*|__|_)(.{3,90}?)(?:</u>|\*\*|__|_)$")

    # candidates = []
    # for i, b in enumerate(raw_blocks):
    #     s = b.strip()
    #     if is_heading_block(s) or is_table_block(s) or "\n" in s:
    #         continue
    #     m = WRAPPED.fullmatch(s)
    #     if m and re.search(r"[A-Za-z]{3,}", m.group(1)) \
    #     and not m.group(1).rstrip().endswith((".", ",", ";", ":")):
    #         candidates.append((i, s))

    # print(f"Heading-shaped blocks with no # marker: {len(candidates)}")
    # for i, s in candidates:
    #     print(f"  [{i}] {s}")

    


"""
Here's what `chunk_markdown()` does, in execution order:

1. **Read** the markdown file as UTF-8
2. **Split into blocks** on blank lines, strip whitespace, drop empties
3. **Strip `<br>` tags** left over from the PDF conversion
4. **Remove repeating boilerplate** — normalize digits away, count near-identical patterns, drop anything appearing 5+ times (page footers, running headers)
5. **Extract headings** — any single line starting with `#` leaves the block stream and becomes context for what follows. Consecutive headings accumulate; the context carries forward until a new heading replaces it
6. **Drop degenerate blocks** — non-table blocks with under 3 characters of real content after stripping markdown punctuation (`x`, `o` checkbox marks)
7. **Walk the remaining blocks:**
   - **Tables** stay atomic, never split. Each absorbs the block immediately before it as a caption — but only if both share the same heading context
   - **Prose** goes through `RecursiveCharacterTextSplitter` at 500 chars / 50 overlap
   - Both get their heading context prepended
8. **Tag each chunk** with `content_type`, `source_company`, `filing_year`, `conversion_status`

Then separately, `convert_table_chunks()` — which the dry run does *not* call:

9. **LLM-rewrite each table** into sentences, with retry-and-backoff on rate limits, 2.5s spacing between calls, and a raw-text fallback marked `raw_fallback` plus a summary warning of how many failed

**What it no longer does:** prepend `{company} {year} 10-K` to every chunk."""