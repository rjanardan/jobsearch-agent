"""Read-only viewer server: Postgres job store -> static JSON for the HTML UI.

Local-only (binds 127.0.0.1). Serves /api/jobs (joined match rows),
/api/dims (dimension evidence keyed by job_id), and the static index.html.
This is a thin convenience layer over the same DB the agent writes; it makes
no schema changes and exposes no write endpoints. NFR-1: nothing here leaves
the host; bind loopback only.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text

from jobagent.store.db import session_scope

app = FastAPI(title="jobsearch-agent viewer", version="0.1.0")

HERE = Path(__file__).resolve().parent
INDEX = HERE / "index.html"

_JOBS_SQL = text(
    """
    SELECT DISTINCT ON (j.id)
           j.id AS job_id,
           j.title, j.company_name, j.location, j.posted_at, j.url,
           j.source, j.level, j.remote,
           m.score, m.passed, m.profile_version, m.gaps
    FROM job j
    LEFT JOIN match m ON m.job_id = j.id
    WHERE j.active
    ORDER BY j.id, m.score DESC NULLS LAST, j.posted_at DESC NULLS LAST
    """
)

_DIMS_SQL = text(
    """
    SELECT m.job_id, m.dimensions, m.rationale
    FROM match m
    WHERE m.dimensions IS NOT NULL
    """
)


def _jsonable(row) -> dict:
    """Map a SQLAlchemy Row to a plain JSON-safe dict."""
    d = dict(row._mapping)
    if d.get("posted_at") is not None:
        d["posted_at"] = str(d["posted_at"])
    if d.get("gaps") is not None and isinstance(d["gaps"], str):
        try:
            d["gaps"] = json.loads(d["gaps"])
        except Exception:  # noqa: BLE001
            pass
    return d


@app.get("/api/jobs")
def jobs() -> JSONResponse:
    with session_scope() as s:
        rows = s.execute(_JOBS_SQL).all()
    return JSONResponse([_jsonable(r) for r in rows])


@app.get("/api/dims")
def dims() -> JSONResponse:
    out: dict = {}
    with session_scope() as s:
        for r in s.execute(_DIMS_SQL).all():
            m = r._mapping
            job_id = str(m["job_id"])
            dim = m["dimensions"]
            if isinstance(dim, str):
                try:
                    dim = json.loads(dim)
                except Exception:  # noqa: BLE001
                    dim = {}
            out[job_id] = {
                "dimensions": dim,
                "rationale": m["rationale"],
            }
    return JSONResponse(out)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(INDEX)


def _phoenix_healthy() -> bool:
    try:
        httpx.get("http://localhost:6006", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


@app.get("/health")
def health() -> JSONResponse:
    """Liveness: DB reachable + (optionally) Phoenix up."""
    try:
        with session_scope() as s:
            s.execute(text("SELECT 1"))
        db = "ok"
    except Exception as e:  # noqa: BLE001
        db = f"error: {e}"
    return JSONResponse({"db": db, "phoenix": _phoenix_healthy()})
