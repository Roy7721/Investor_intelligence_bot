
"""
FastAPI app for the Investor Intelligence dashboard.

Serves the static frontend plus a small JSON API over the KPI cache. The page
renders client-side: index.html arrives with empty slots and its JavaScript
fills them from /api/*. That is forced by the chat panel — it has to update
without a page reload, and a server-rendered dashboard beside a client-rendered
chat would mean two mental models in one page.

    uvicorn app.main:app --reload
"""

from pathlib import Path
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config.config import ROOT
from app.metrics import derive

from pydantic import BaseModel

# Imported at module scope on purpose: it costs ~20s (openai + chromadb +
# langchain_google_genai). Paying that once at startup is better than making
# the first person to ask a question wait 20 seconds while watching a spinner.
# If the --reload loop gets annoying, move it inside chat() instead.
from Rag.chatbot import ask

import asyncio
import json as _json

from fastapi import File, Form, UploadFile
from fastapi.responses import StreamingResponse

from app import jobs


MAX_UPLOAD_MB = 25



STATIC = ROOT / "static"
KPI_DIR = ROOT / "data" / "kpi"

app = FastAPI(title="Investor Intelligence")


def _load(company: str, year: int) -> dict | None:
    """Read one cached filing. Returns None rather than raising so callers
    decide what a miss means — a 404 here, an empty peer entry elsewhere."""
    path = KPI_DIR / f"{company}_{year}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

def _available() -> list[dict]:
    """Every filing in the cache, from the filenames. rpartition splits on the
    LAST underscore, so a company name containing one still parses."""
    out = []
    for path in sorted(KPI_DIR.glob("*.json")):
        company, _, year = path.stem.rpartition("_")
        out.append({"company": company, "year": int(year)})
    return out




@app.get("/api/health")
def health() -> dict:
    """Cheapest possible proof the server is up and routing works."""
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/companies")
def companies() -> list[dict]:
    return _available()


@app.get("/api/kpi/{company}/{year}")
def kpi(company: str, year: int) -> dict:
    """One filing: raw metrics, derived ratios, and every filing's ratios for
    the comparison bars. Peers include the requested company — the frontend
    highlights it rather than the API removing it, so the bar chart shows
    where this filing sits rather than only who it isn't."""
    filing = _load(company, year)
    if filing is None:
        raise HTTPException(status_code=404, detail=f"No KPI data for {company} {year}")

    peers = []
    for entry in _available():
        other = _load(entry["company"], entry["year"])
        peers.append({**entry, **derive(other["metrics"])})

    return {
        "company": filing["company"],
        "year": filing["year"],
        "metrics": filing["metrics"],
        "derived": derive(filing["metrics"]),
        "peers": peers,
    }


class ChatRequest(BaseModel):
    question: str
    company: str
    year: int | None = None

@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    """One question against one filing. All the work — retrieval, the scope
    declaration, the prompt — already lives in ask(); this is only the seam
    between HTTP and that function."""
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is empty")

    answer = ask(question=question, source_company=req.company, filing_year=req.year)
    return {"answer": answer}


@app.post("/api/upload")
async def upload(
    file: UploadFile = File(...),
    company: str | None = Form(None),
    year: int | None = Form(None),
) -> dict:
    """Accept a PDF and start ingesting it. Returns immediately with a job id;
    progress arrives on /api/progress/{job_id}.

    company and year are optional and normally absent — they are only sent on a
    retry, after a first attempt raised NeedsIdentification because the document
    had no 10-K cover page to read them from.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than {MAX_UPLOAD_MB} MB. Conversion is billed "
                   f"per page, so very large documents are rejected up front.",
        )
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That is not a PDF file.")

    return {"job_id": jobs.start(data, company=company, year=year)}



@app.get("/api/progress/{job_id}")
async def progress(job_id: str) -> StreamingResponse:
    """Server-Sent Events: one message per pipeline stage as it happens.

    The pipeline already reports real detail at every stage — page counts,
    chunk counts, table counts — so nothing here is invented.
    """
    if jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Unknown job")

    async def stream():
        sent = 0
        while True:
            job = jobs.get(job_id)
            while sent < len(job["events"]):
                yield f"data: {_json.dumps(job['events'][sent])}\n\n"
                sent += 1
            if job["done"]:
                yield "data: " + _json.dumps({
                    "stage": "finished",
                    "result": job["result"],
                    "error": job["error"],
                }) + "\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")

@app.get("/api/progress/{job_id}")
async def progress(job_id: str) -> StreamingResponse:
    """Server-Sent Events: one message per pipeline stage as it happens.

    The pipeline already reports real detail at every stage — page counts,
    chunk counts, table counts — so nothing here is invented.
    """
    if jobs.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Unknown job")

    async def stream():
        sent = 0
        while True:
            job = jobs.get(job_id)
            while sent < len(job["events"]):
                yield f"data: {_json.dumps(job['events'][sent])}\n\n"
                sent += 1
            if job["done"]:
                yield "data: " + _json.dumps({
                    "stage": "finished",
                    "result": job["result"],
                    "error": job["error"],
                }) + "\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream")

# Mounted at /static rather than / so it can never shadow an /api route.
app.mount("/static", StaticFiles(directory=STATIC), name="static")