"""
main.py — Amazing Tools SEO Crawler API (FastAPI + SQLite).

Endpoints:
  POST /api/crawl              Start a new crawl job
  GET  /api/jobs               List all jobs (limit, offset)
  GET  /api/jobs/{id}          Get job details + full results
  DELETE /api/jobs/{id}        Delete a job
  GET  /api/health             Health check

Jobs run in a background thread pool; results stored in SQLite.
"""

import json
import logging
import os
import sqlite3
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl

from crawler_engine import crawl_multiple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "jobs.db")


# ── Database ─────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id              TEXT PRIMARY KEY,
            client_url      TEXT NOT NULL,
            competitor_urls TEXT NOT NULL,   -- JSON array
            status          TEXT NOT NULL DEFAULT 'pending',
            created_at      TEXT NOT NULL,
            started_at      TEXT,
            completed_at    TEXT,
            pages_crawled   INTEGER DEFAULT 0,
            error_message   TEXT,
            results         TEXT             -- JSON
        )
    """)
    conn.commit()
    conn.close()


db_lock = threading.Lock()


def db_update(job_id: str, **kwargs):
    with db_lock:
        conn = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values()) + [job_id]
        conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", vals)
        conn.commit()
        conn.close()


# ── App lifespan ──────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Amazing Tools SEO Crawler API starting up.")
    yield
    logger.info("Shutting down.")


app = FastAPI(title="Amazing Tools SEO Crawler API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class CrawlRequest(BaseModel):
    client_url:      str
    competitor_urls: list[str] = []
    max_pages:       int       = 100
    check_externals: bool      = True
    respect_robots:  bool      = True


class JobSummary(BaseModel):
    id:               str
    client_url:       str
    competitor_count: int
    status:           str
    created_at:       str
    completed_at:     Optional[str] = None
    pages_crawled:    Optional[int] = None


# ── Background crawl task ─────────────────────────────────────────────────────

def run_crawl(job_id: str, client_url: str, competitor_urls: list[str],
              max_pages: int, check_externals: bool, respect_robots: bool):

    db_update(job_id, status="running", started_at=datetime.now(timezone.utc).isoformat())
    total_pages = 0

    def progress(url: str, n: int, domain_idx: int, total_domains: int):
        nonlocal total_pages
        total_pages = n + domain_idx * max_pages
        db_update(job_id, pages_crawled=total_pages)

    try:
        results = crawl_multiple(
            client_url       = client_url,
            competitor_urls  = competitor_urls,
            max_pages        = max_pages,
            check_externals  = check_externals,
            respect_robots   = respect_robots,
            progress_callback= progress,
        )

        # results is already dict[url -> plain dict]
        results_dict = results

        pages_total = sum(
            len(dr.get("pages", [])) for dr in results_dict.values()
        )

        db_update(
            job_id,
            status       = "done",
            completed_at = datetime.now(timezone.utc).isoformat(),
            pages_crawled= pages_total,
            results      = json.dumps(results_dict),
        )
        logger.info(f"Job {job_id} done — {pages_total} pages total.")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}", exc_info=True)
        db_update(
            job_id,
            status        = "error",
            completed_at  = datetime.now(timezone.utc).isoformat(),
            error_message = str(e),
        )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "seo-crawler-api"}


@app.post("/api/crawl")
def start_crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    # Validate URLs
    if not req.client_url.startswith(("http://", "https://")):
        raise HTTPException(400, detail="client_url must start with http:// or https://")
    for u in req.competitor_urls:
        if not u.startswith(("http://", "https://")):
            raise HTTPException(400, detail=f"Invalid competitor URL: {u}")
    if len(req.competitor_urls) > 5:
        raise HTTPException(400, detail="Maximum 5 competitor URLs allowed.")
    req.max_pages = max(10, min(500, req.max_pages))

    job_id = str(uuid.uuid4())[:8]
    now    = datetime.now(timezone.utc).isoformat()

    with db_lock:
        conn = get_db()
        conn.execute(
            "INSERT INTO jobs (id, client_url, competitor_urls, status, created_at) VALUES (?,?,?,?,?)",
            (job_id, req.client_url, json.dumps(req.competitor_urls), "pending", now)
        )
        conn.commit()
        conn.close()

    background_tasks.add_task(
        run_crawl, job_id,
        req.client_url, req.competitor_urls,
        req.max_pages, req.check_externals, req.respect_robots,
    )

    return {"id": job_id, "status": "pending", "created_at": now}


@app.get("/api/jobs")
def list_jobs(limit: int = 20, offset: int = 0):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, client_url, competitor_urls, status, created_at, completed_at, pages_crawled "
        "FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset)
    ).fetchall()
    conn.close()

    return [
        {
            "id":               r["id"],
            "client_url":       r["client_url"],
            "competitor_count": len(json.loads(r["competitor_urls"] or "[]")),
            "status":           r["status"],
            "created_at":       r["created_at"],
            "completed_at":     r["completed_at"],
            "pages_crawled":    r["pages_crawled"],
        }
        for r in rows
    ]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, detail="Job not found.")

    result = {
        "id":               row["id"],
        "client_url":       row["client_url"],
        "competitor_urls":  json.loads(row["competitor_urls"] or "[]"),
        "status":           row["status"],
        "created_at":       row["created_at"],
        "started_at":       row["started_at"],
        "completed_at":     row["completed_at"],
        "pages_crawled":    row["pages_crawled"],
        "error_message":    row["error_message"],
        "results":          json.loads(row["results"]) if row["results"] else None,
    }
    return result


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    conn = get_db()
    row = conn.execute("SELECT id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail="Job not found.")
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    return None
