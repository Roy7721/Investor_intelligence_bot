
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

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

app = FastAPI(title="Investor Intelligence")


@app.get("/api/health")
def health() -> dict:
    """Cheapest possible proof the server is up and routing works."""
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


# Mounted at /static rather than / so it can never shadow an /api route.
app.mount("/static", StaticFiles(directory=STATIC), name="static")