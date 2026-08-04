"""
llamaparse_convert.py — PDF -> markdown via LlamaParse, for the extractor trial.

Third extractor under test, after pymupdf4llm and docling. Writes to
data/markdown_llamaparse/ so all four outputs coexist and can be diffed.

    python Scripts/llamaparse_convert.py 2024_Microsoft 37 43

Pages are given 1-indexed (as you'd read them in a PDF viewer) and converted
to LlamaParse's 0-indexed target_pages here. Page 37 -> "36".

Unlike pymupdf4llm and docling this is a CLOUD service: the PDF is uploaded.
Fine for a public SEC filing, and worth a deliberate decision before it becomes
the production path — it turns ingestion into an API dependency with a
per-page cost, which cuts against the local/free-tier constraint in journey.md.

Needs LLAMA_CLOUD_API_KEY in .env (already gitignored). Get one from
https://cloud.llamaindex.ai. Never print or commit the value.
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

API_KEY = os.getenv("LLAMA_CLOUD_API_KEY")
if not API_KEY:
    raise SystemExit(
        "LLAMA_CLOUD_API_KEY not set. Add it to .env:\n"
        "    LLAMA_CLOUD_API_KEY=llx-...\n"
        "Key from https://cloud.llamaindex.ai"
    )

try:
    from llama_cloud_services import LlamaParse
except ImportError:
    # Older releases shipped as llama-parse with this module path.
    from llama_parse import LlamaParse


def convert(stem: str, first_page: int | None = None, last_page: int | None = None) -> None:
    pdf_path = ROOT / "data" / "raw_pdfs" / f"{stem}.pdf"
    if not pdf_path.exists():
        raise SystemExit(f"No such PDF: {pdf_path}")

    kwargs = {"api_key": API_KEY, "result_type": "markdown"}

    if first_page is not None:
        # LlamaParse target_pages is 0-indexed, comma/range separated.
        kwargs["target_pages"] = f"{first_page - 1}-{last_page - 1}"
        suffix = f"_p{first_page}-{last_page}"
    else:
        suffix = ""

    out_path = ROOT / "data" / "markdown_llamaparse" / f"{stem}{suffix}.md"

    parser = LlamaParse(**kwargs)

    start = time.perf_counter()
    documents = parser.load_data(str(pdf_path))
    elapsed = time.perf_counter() - start

    markdown = "\n\n".join(d.text for d in documents)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    print()
    print(f"{pdf_path.name} -> {out_path.relative_to(ROOT)}")
    print(f"  pages           : {'all' if first_page is None else f'{first_page}-{last_page}'}")
    print(f"  conversion time : {elapsed:.1f}s")
    print(f"  characters      : {len(markdown):,}")
    print(f"  lines           : {markdown.count(chr(10)):,}")
    print(f"  table pipe rows : {sum(1 for l in markdown.split(chr(10)) if l.strip().startswith('|'))}")


if __name__ == "__main__":
    stem = sys.argv[1] if len(sys.argv) > 1 else "2024_Microsoft"
    if len(sys.argv) > 3:
        convert(stem, int(sys.argv[2]), int(sys.argv[3]))
    else:
        convert(stem)
