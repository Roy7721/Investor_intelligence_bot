"""
Background ingestion jobs and their progress.

Uploading cannot be handled inline: conversion alone runs for minutes and the
HTTP request would time out. So /api/upload starts a thread, returns a job id
immediately, and the browser follows progress on a separate connection.

State is a plain dict in memory. That is honest for a single-user demo and has
two consequences worth knowing: jobs die on restart (so --reload kills anything
in flight), and nothing is ever evicted. Both are fine at this size and both
would need fixing for real multi-user use.
"""


import threading
import uuid

from app.pipeline import ingest_pdf, NeedsIdentification, NotAFinancialDocument

_JOBS: dict[str, dict] = {}


def start(pdf_bytes: bytes, company: str | None = None, year: int | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {"events": [], "done": False, "result": None, "error": None}

    def run():
        job = _JOBS[job_id]

        def emit(stage: str, detail: str = ""):
            job["events"].append({"stage": stage, "detail": detail})

        try:
            job["result"] = ingest_pdf(pdf_bytes, company=company, year=year, on_progress=emit)
        except NeedsIdentification as e:
            # Not a failure. The document is usable; we just don't know whose
            # it is. The UI turns this into two input fields, not an error.
            job["error"] = {"kind": "needs_identification", "message": str(e)}
        except NotAFinancialDocument as e:
            job["error"] = {"kind": "not_financial", "message": str(e)}
        except Exception as e:                      # noqa: BLE001 — surface anything
            job["error"] = {"kind": "error", "message": f"{type(e).__name__}: {e}"}
        finally:
            job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return job_id


def get(job_id: str) -> dict | None:
    return _JOBS.get(job_id)