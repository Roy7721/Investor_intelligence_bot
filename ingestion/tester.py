import pymupdf, pymupdf4llm
from pathlib import Path
doc = pymupdf.open("./data/raw_pdfs/2024_Microsoft.pdf")
#toc_headers = pymupdf4llm.TocHeaders(doc)
#hdr_info=toc_headers
md_text = pymupdf4llm.to_markdown(doc, )

repo_path = Path(__file__).resolve().parents[1]


md_file = repo_path / "new_microsoft.md"

md_file.write_text(
        data=md_text,
        encoding="utf-8"
    )