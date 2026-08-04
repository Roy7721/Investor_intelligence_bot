"""
datalab_convert.py — PDF -> markdown via Datalab (Marker API), extractor trial.

Fourth extractor under test, after pymupdf4llm, docling and LlamaParse.
Writes to data/markdown_datalab/ so all outputs coexist and can be diffed.

    python Scripts/datalab_convert.py 2024_Microsoft 37 43

Pages are 1-indexed here (as in a PDF viewer) and converted to Marker's
0-indexed page_range. Page 37 -> 36.

Cloud service, like LlamaParse: the PDF is uploaded. Fine for a public SEC
filing; a deliberate decision if it ever becomes the production path, since it
makes ingestion an API dependency with a per-page cost.

Needs DATALAB_API_KEY in .env (already gitignored). Never printed or committed.

The API is asynchronous: POST returns a check URL, which is polled until the
job reports complete.
"""

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[1]

API_KEY = os.getenv("DATALAB_API_KEY")
if not API_KEY:
    raise SystemExit(
        "DATALAB_API_KEY not set. Add it to .env:\n"
        "    DATALAB_API_KEY=...\n"
        "Key from https://www.datalab.to/app/api"
    )

SUBMIT_URL = "https://www.datalab.to/api/v1/marker"
POLL_INTERVAL_SECONDS = 3
MAX_POLLS = 200


def submit(pdf_path: Path, page_range: str | None) -> str:
    """POST the file, return the URL to poll for the result."""
    data = {"output_format": "markdown"}
    if page_range:
        data["page_range"] = page_range

    with pdf_path.open("rb") as fh:
        response = requests.post(
            SUBMIT_URL,
            headers={"X-Api-Key": API_KEY},
            files={"file": (pdf_path.name, fh, "application/pdf")},
            data=data,
            timeout=120,
        )

    if response.status_code != 200:
        raise SystemExit(f"Submit failed [{response.status_code}]: {response.text[:500]}")

    payload = response.json()
    if not payload.get("success", True):
        raise SystemExit(f"Submit rejected: {payload}")

    check_url = payload.get("request_check_url")
    if not check_url:
        raise SystemExit(f"No request_check_url in response: {payload}")
    return check_url


def poll(check_url: str) -> dict:
    """Poll until the job completes. Raises on failure or timeout."""
    for attempt in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL_SECONDS)
        response = requests.get(check_url, headers={"X-Api-Key": API_KEY}, timeout=60)
        payload = response.json()

        status = payload.get("status")
        if status == "complete":
            if not payload.get("success", True):
                raise SystemExit(f"Job failed: {payload.get('error')}")
            return payload

        print(f"  ... {status} ({(attempt + 1) * POLL_INTERVAL_SECONDS}s)", end="\r")

    raise SystemExit(f"Timed out after {MAX_POLLS * POLL_INTERVAL_SECONDS}s")


def convert(stem: str, first_page: int | None = None, last_page: int | None = None) -> None:
    pdf_path = ROOT / "data" / "raw_pdfs" / f"{stem}.pdf"
    if not pdf_path.exists():
        raise SystemExit(f"No such PDF: {pdf_path}")

    if first_page is None:
        page_range, suffix = None, ""
    else:
        page_range = f"{first_page - 1}-{last_page - 1}"   # Marker is 0-indexed
        suffix = f"_p{first_page}-{last_page}"

    out_path = ROOT / "data" / "markdown_datalab" / f"{stem}{suffix}.md"

    start = time.perf_counter()
    check_url = submit(pdf_path, page_range)
    print(f"submitted, polling {check_url}")
    result = poll(check_url)
    elapsed = time.perf_counter() - start

    markdown = result.get("markdown") or ""
    if not markdown:
        raise SystemExit(f"Completed but no markdown in response. Keys: {list(result)}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown, encoding="utf-8")

    print()
    print(f"{pdf_path.name} -> {out_path.relative_to(ROOT)}")
    print(f"  pages           : {'all' if first_page is None else f'{first_page}-{last_page}'}")
    print(f"  round trip      : {elapsed:.1f}s")
    print(f"  characters      : {len(markdown):,}")
    print(f"  lines           : {markdown.count(chr(10)):,}")
    print(f"  table pipe rows : {sum(1 for l in markdown.split(chr(10)) if l.strip().startswith('|'))}")


if __name__ == "__main__":
    stem = sys.argv[1] if len(sys.argv) > 1 else "2024_Microsoft"
    if len(sys.argv) > 3:
        convert(stem, int(sys.argv[2]), int(sys.argv[3]))
    else:
        convert(stem)
