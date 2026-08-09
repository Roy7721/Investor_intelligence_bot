"""
Full ingestion path for an uploaded filing.

Calls on_progress(stage, detail) after each step so the browser can stream real
messages rather than a fake timer. Every stage already reports something true —
page counts, chunk counts, table counts — so there is nothing to invent.

Ordering matters in two places:

  * The hash check comes FIRST. Re-uploading a filing already ingested returns
    in milliseconds, which is what makes the demo instant.
  * identify() comes straight after conversion and gates everything expensive.
    A document without a 10-K cover page stops there, before ~1,200 embeddings
    and 8 LLM calls. Conversion is the only cost that cannot be avoided, since
    you need the text to know what you have.
"""

import hashlib
import json
from pathlib import Path

from config.config import ROOT
from ingestion.pdf_to_markdown import submit, poll
from ingestion.chunking_v5 import chunk_markdown
from vector_store.vector_store_v2 import embed_and_store
from Rag.kpi import extract_kpis
from ingestion.identify import identify


UPLOADS = ROOT / "data" / "uploads"
MARKDOWN = ROOT / "data" / "markdown_datalab"
KPI = ROOT / "data" / "kpi"


class NotAnAnnualFiling(Exception):
    """Raised when the cover page has no registrant or fiscal-year markers.
    Not a crash — the honest answer for a press release or a slide deck."""
class NotAFinancialDocument(Exception):
    """Nothing resembling financial statements. Stop before spending money."""


class NeedsIdentification(Exception):
    """Financial statements present, but no 10-K cover page to read the
    company and year from. The caller should ask, then retry with them."""



def _fingerprint(pdf_bytes: bytes) -> str:
    return hashlib.sha256(pdf_bytes).hexdigest()[:16]


def _cached(fingerprint: str) -> dict | None:
    """A sidecar written after a successful run. Both it AND the KPI file must
    exist — a sidecar alone would mean a run that died partway, and returning
    that as a cache hit would show an empty dashboard with no explanation."""
    sidecar = UPLOADS / f"{fingerprint}.json"
    if not sidecar.exists():
        return None
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    if not (KPI / f"{meta['company']}_{meta['year']}.json").exists():
        return None
    return meta


def ingest_pdf(pdf_bytes: bytes,company: str | None = None,
               year: int | None = None, on_progress=None) -> dict:
    emit = on_progress or (lambda stage, detail="": None)

    # --- 1. fingerprint and cache ------------------------------------------
    emit("hashing", "checking whether this filing is already ingested")
    fingerprint = _fingerprint(pdf_bytes)

    hit = _cached(fingerprint)
    if hit:
        emit("cached", f"{hit['company']} FY{hit['year']} — already ingested")
        return {**hit, "cached": True}

    UPLOADS.mkdir(parents=True, exist_ok=True)
    pdf_path = UPLOADS / f"{fingerprint}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    # --- 2. convert ---------------------------------------------------------
    emit("converting", "sending to the PDF converter — this is the slow step")
    result = poll(submit(pdf_path, None))
    markdown = result.get("markdown") or ""
    if not markdown:
        raise RuntimeError("converter returned no markdown")
    emit("converting", f"{len(markdown):,} characters extracted")

    # --- 3. identify, and gate ---------------------------------------------
    emit("identifying", "reading the cover page")
    ident = identify(markdown)

    if not ident["is_financial"]:
        raise NotAFinancialDocument(
            f"Only {ident['financial_score']} financial-statement markers found. "
            "This does not look like a company's financial filing."
        )

    company = company or ident["company"]
    year = year or ident["year"]

    if not (company and year):
        raise NeedsIdentification(
            "This looks like a financial document but has no Form 10-K cover "
            "page, so the company and fiscal year could not be read. Please "
            "supply them."
        )

    source = "cover page" if ident["has_cover_page"] else "supplied"
    emit("identifying", f"{company} — fiscal year {year} ({source})")

    MARKDOWN.mkdir(parents=True, exist_ok=True)
    md_path = MARKDOWN / f"{year}_{company}.md"
    md_path.write_text(markdown, encoding="utf-8")

    # --- 4. chunk -----------------------------------------------------------
    emit("chunking", "splitting into retrievable pieces")
    chunks = chunk_markdown(
        markdown_file=str(md_path), source_company=company, filing_year=year
    )
    tables = sum(1 for c in chunks if c["content_type"] == "table")
    emit("chunking", f"{len(chunks):,} chunks, {tables} tables")

    # --- 5. embed -----------------------------------------------------------
    emit("embedding", f"embedding {len(chunks):,} chunks")
    embed_and_store(chunks)
    emit("embedding", "stored")

    # --- 6. extract ---------------------------------------------------------
    emit("extracting", "pulling KPIs from the filing")
    kpis = extract_kpis(company, year, refresh=True)
    found = sum(1 for m in kpis["metrics"].values() if m.get("value") is not None)
    emit("extracting", f"{found} of {len(kpis['metrics'])} metrics found")

    # --- 7. remember, so the next upload of this file is instant -------------
    meta = {"company": company, "year": year, "fingerprint": fingerprint}
    (UPLOADS / f"{fingerprint}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    emit("done", f"{company} FY{year} ready")
    return {**meta, "cached": False}



if __name__ == "__main__":
    import re
    import sys

    RAW = ROOT / "data" / "raw_pdfs"

    def _from_filename(path: Path) -> tuple[str | None, int | None]:
        """Company and year from "{year}_{Company}.pdf".

        A Docker build has nobody to ask. Microsoft's filing has no 10-K cover
        page, so identify() cannot name it and ingest_pdf would raise
        NeedsIdentification — failing the build. The filename supplies what the
        cover page cannot, using the same convention as the markdown files.
        """
        m = re.fullmatch(r"(\d{4})_([A-Za-z][\w.-]*)", path.stem)
        return (m.group(2), int(m.group(1))) if m else (None, None)



    targets =[Path(a) if Path(a).exists() else RAW / a for a in sys.argv[1:]] or sorted(RAW.glob("*.pdf"))
    if not targets:
        raise SystemExit(f"No PDFs found in {RAW}")

    failures = []
    for pdf in targets:
        company, year = _from_filename(pdf)
        print(f"\n=== {pdf.name}  ->  {company or '?'} {year or '?'}", flush=True)
        try:
            result = ingest_pdf(
                pdf.read_bytes(),
                company=company,
                year=year,
                on_progress=lambda stage, detail="": print(f"  [{stage}] {detail}", flush=True),
            )
            print(f"  done: {result}", flush=True)
        except Exception as e:                      # noqa: BLE001
            # Deliberately broad: report every failure in one run rather than
            # stopping at the first, so a build log shows all of them at once.
            print(f"  FAILED: {type(e).__name__}: {e}", flush=True)
            failures.append(pdf.name)

    # Verify. A build that "succeeds" with an empty store is worse than one
    # that fails, because it only surfaces in production.
    from config.config import COLLECTION_NAME
    from vector_store.client import _client, _embedder

    chunks = _client.get_collection(COLLECTION_NAME, embedding_function=_embedder).count()
    kpis = len(list((ROOT / "data" / "kpi").glob("*.json")))
    print(f"\nstore: {chunks:,} chunks    kpi files: {kpis}")

    if failures:
        raise SystemExit(f"FAILED: {', '.join(failures)}")
    if chunks == 0 or kpis == 0:
        raise SystemExit("Build produced an empty store or no KPI files.")
    print("OK")


    




# if __name__ == "__main__":
#     import sys
#     path = Path(sys.argv[1])
#     def show(stage, detail=""):
#         print(f"  [{stage}] {detail}")
#     print(ingest_pdf(path.read_bytes(), on_progress=show,company="Microsoft",year= 2024))