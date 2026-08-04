"""
docling_convert.py — PDF -> markdown via docling, for the docling-trial comparison.

Writes to data/markdown_docling/ so both extractors' output can coexist and be
diffed directly. data/markdown/ (pymupdf4llm) is never touched.

    python Scripts/docling_convert.py 2024_Microsoft            # whole document
    python Scripts/docling_convert.py 2024_Microsoft 1 15       # pages 1-15 only

Tuned for an 8 GB machine with no MSVC toolchain. Three deviations from
docling's defaults, all forced by this box:

1. TORCHDYNAMO_DISABLE — torch.compile JITs the layout model to C++ and needs
   MSVC's cl.exe. Not installed here, so the run dies with InvalidCxxCompiler.
   Eager mode is slower but correct. Must be set BEFORE torch is imported.

2. do_ocr = False — the default pipeline runs RapidOCR, which renders every
   page to a full-resolution bitmap. On 7.9 GB that produced std::bad_alloc on
   pages 13-61, i.e. a silently truncated document. These 10-Ks are digitally
   generated and have a real text layer, so OCR is recovering text that is
   already there. Turning it off removes the memory pressure and most of the
   runtime. Only re-enable for a scanned filing.

3. page_batch_size = 1 — pages held in memory at once. Default 4.

do_table_structure stays ON. TableFormer is the reason for this trial.
"""

import os

# Must precede any torch import (docling pulls it in transitively).
os.environ.setdefault("TORCHDYNAMO_DISABLE", "1")

import sys
import time
from pathlib import Path

from docling.backend.docling_parse_v4_backend import DoclingParseV4DocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.settings import settings
from docling.document_converter import DocumentConverter, PdfFormatOption

ROOT = Path(__file__).resolve().parents[1]

settings.perf.page_batch_size = 1

# std::bad_alloc came from docling-parse, the C++ default backend: it died at
# page 12 of 61 and stayed dead, unmoved by page_batch_size 4 -> 1 or by
# disabling OCR. That is cumulative allocation inside the parser, not per-page
# pressure, so the fix is to stop using it. pypdfium2 is pure Python bindings
# over PDFium.
#
# Tradeoff: docling-parse exposes richer text-cell geometry, which TableFormer
# uses for cell matching, so table structure may be slightly worse here. A
# working backend beats a better one that cannot reach page 13.
#
#   $env:DOCLING_BACKEND="parsev4"    to switch back and compare
BACKENDS = {
    "pypdfium": PyPdfiumDocumentBackend,
    "parsev4": DoclingParseV4DocumentBackend,
}
BACKEND_NAME = os.environ.get("DOCLING_BACKEND", "pypdfium")

# $env:DOCLING_OCR="1" to render pages and read cell text from the image
# instead of the PDF text layer. Different path to cell assignment, so it may
# recover header rows the text-layer path drops.
#
# Two costs. Memory: OCR bitmaps caused std::bad_alloc on the full 61 pages, so
# keep OCR runs to short page ranges. Accuracy: OCR can misread a digit, and in
# a financial table a silent 3->8 is worse than any missing header. Never ship
# OCR output without checking figures against the PDF.
USE_OCR = os.environ.get("DOCLING_OCR", "") not in ("", "0", "false", "False")


def build_converter() -> DocumentConverter:
    opts = PdfPipelineOptions()
    opts.do_ocr = USE_OCR
    opts.do_table_structure = True
    opts.table_structure_options.do_cell_matching = True
    opts.generate_page_images = False
    opts.generate_picture_images = False

    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=opts,
                backend=BACKENDS[BACKEND_NAME],
            )
        }
    )


def convert(stem: str, page_range: tuple[int, int] | None = None) -> None:
    pdf_path = ROOT / "data" / "raw_pdfs" / f"{stem}.pdf"
    if not pdf_path.exists():
        raise SystemExit(f"No such PDF: {pdf_path}")

    suffix = "" if page_range is None else f"_p{page_range[0]}-{page_range[1]}"
    ocr_tag = "_ocr" if USE_OCR else ""
    out_path = ROOT / "data" / "markdown_docling" / f"{stem}{suffix}_{BACKEND_NAME}{ocr_tag}.md"

    converter = build_converter()

    kwargs = {} if page_range is None else {"page_range": page_range}

    start = time.perf_counter()
    result = converter.convert(str(pdf_path), **kwargs)
    elapsed = time.perf_counter() - start

    markdown = result.document.export_to_markdown()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    print()
    print(f"{pdf_path.name} -> {out_path.relative_to(ROOT)}")
    print(f"  backend         : {BACKEND_NAME}")
    print(f"  ocr             : {'ON' if USE_OCR else 'off'}")
    print(f"  pages           : {'all' if page_range is None else f'{page_range[0]}-{page_range[1]}'}")
    print(f"  conversion time : {elapsed:.1f}s")
    print(f"  characters      : {len(markdown):,}")
    print(f"  lines           : {markdown.count(chr(10)):,}")
    print(f"  tables found    : {len(result.document.tables)}")


if __name__ == "__main__":
    stem = sys.argv[1] if len(sys.argv) > 1 else "2024_Microsoft"
    pages = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else None
    convert(stem, pages)
