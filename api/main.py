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

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
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
            results         TEXT,            -- JSON
            analysis        TEXT             -- GPT analysis text
        )
    """)
    # Migrate existing tables that lack the analysis column
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN analysis TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists
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
    use_playwright:  bool      = False
    calculate_ipr:   bool      = False


class SemanticRequest(BaseModel):
    url:          str
    query:        str
    max_sections: int = 30


class RewriteRequest(BaseModel):
    section: str
    query:   str
    url:     str = ""


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
              max_pages: int, check_externals: bool, respect_robots: bool,
              use_playwright: bool = False, calculate_ipr: bool = False):

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
            use_playwright   = use_playwright,
            calculate_ipr    = calculate_ipr,
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
    req.max_pages = max(10, req.max_pages)  # no upper cap: 99999 = all pages

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
        req.use_playwright, req.calculate_ipr,
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


# ── Semantic analysis helpers ───────────────────────────────────────────────

def _cosine_sim(a: list, b: list) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = sum(x * x for x in a) ** 0.5
    nb  = sum(x * x for x in b) ** 0.5
    return dot / (na * nb + 1e-10)


async def _fetch_page_sections(url: str) -> list[dict]:
    try:
        async with httpx.AsyncClient(
            timeout=30, follow_redirects=True,
            headers={"User-Agent": "AmazingTools-SEO/1.0 (+https://davidvesterlund.com)"}
        ) as c:
            r = await c.get(url)
            r.raise_for_status()
    except Exception as e:
        raise HTTPException(400, detail=f"Could not fetch URL: {e}")

    soup = BeautifulSoup(r.text, "lxml")
    for tag in soup(["nav", "header", "footer", "script", "style", "noscript", "aside"]):
        tag.decompose()

    body = soup.find("main") or soup.find("article") or soup.body
    if not body:
        raise HTTPException(400, detail="No readable content found on page.")

    sections = []
    current_heading = ""
    for el in body.find_all(["h1","h2","h3","h4","h5","h6","p","li"]):
        text = el.get_text(" ", strip=True)
        if not text or len(text) < 15:
            continue
        if el.name[0] == "h":
            current_heading = text
            sections.append({"type": "heading", "level": int(el.name[1]),
                              "tag": el.name, "text": text, "heading": text})
        else:
            sections.append({"type": "text", "tag": el.name,
                              "text": text, "heading": current_heading})

    return sections[:120]


# ── Semantic endpoints ─────────────────────────────────────────────────────────

@app.post("/api/analyze/semantic")
async def semantic_analysis(req: SemanticRequest):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="OPENAI_API_KEY not configured.")

    sections = await _fetch_page_sections(req.url)
    if not sections:
        raise HTTPException(400, detail="No readable content found.")

    texts = [s["text"] for s in sections]
    oai   = OpenAI(api_key=api_key)

    try:
        emb = oai.embeddings.create(
            model="text-embedding-3-small",
            input=[req.query] + texts,
        )
    except Exception as e:
        raise HTTPException(500, detail=f"Embedding error: {e}")

    embeddings  = [e.embedding for e in emb.data]
    query_emb   = embeddings[0]

    results = []
    for i, sec in enumerate(sections):
        sim = _cosine_sim(query_emb, embeddings[i + 1])
        results.append({**sec, "similarity": round(float(sim), 4), "index": i})

    results.sort(key=lambda x: x["similarity"], reverse=True)
    page_title = next((s["text"] for s in sections if s.get("level") == 1), req.url)

    return {
        "url":            req.url,
        "query":          req.query,
        "page_title":     page_title,
        "total_sections": len(sections),
        "sections":       results[:req.max_sections],
    }


@app.post("/api/analyze/rewrite")
async def rewrite_section(req: RewriteRequest):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="OPENAI_API_KEY not configured.")

    oai = OpenAI(api_key=api_key)
    prompt = (
        f'Rewrite the text below to be more semantically aligned with the keyword/query "{req.query}".\n'
        f'Keep the same language, structure type, and approximate length. Improve relevance naturally.'
        + (f'\nPage: {req.url}' if req.url else '') +
        f'\n\nOriginal:\n{req.section}\n\nRewrite (no preamble):'
    )
    resp = oai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
        temperature=0.6,
    )
    return {"rewritten": resp.choices[0].message.content.strip()}


# ── AI analysis ───────────────────────────────────────────────────────────────

def _build_prompt(results: dict) -> str:
    urls = list(results.keys())
    client_url = urls[0]
    client = results[client_url]
    s = client.get("summary", {})

    lines = [
        "Du är en expert SEO-konsult. Analysera crawldata nedan och svara ENBART på svenska.\n",
        f"## KLIENTENS WEBBPLATS: {client_url}",
        f"- Crawlade sidor: {s.get('total_pages', 0)}",
        f"- HTTP 200: {s.get('pages_200', 0)}  |  4xx-fel: {s.get('pages_4xx', 0)}  |  5xx-fel: {s.get('pages_5xx', 0)}",
        f"- Saknar title-tag: {s.get('missing_titles', 0)}  |  Dubblerade titlar: {s.get('duplicate_titles', 0)}",
        f"- Saknar H1: {s.get('missing_h1', 0)}  |  Dubblerade H1: {s.get('duplicate_h1', 0)}",
        f"- Saknar meta description: {s.get('missing_meta_desc', 0)}  |  För lång: {s.get('long_meta_desc', 0)}  |  För kort: {s.get('short_meta_desc', 0)}",
        f"- Saknar canonical: {s.get('missing_canonical', 0)}  |  Noindex-sidor: {s.get('noindex_count', 0)}",
        f"- Brutna länkar: {s.get('broken_links', 0)}",
        f"- Bilder utan alt-text: {s.get('images_without_alt', 0)}",
        f"- Totalt interna länkar: {s.get('total_internal_links', 0)}",
        "",
    ]

    # Top pages with issues
    pages = client.get("pages", [])
    problem_pages = sorted(
        pages,
        key=lambda p: (
            (1 if not p.get("title") else 0) +
            (1 if not p.get("h1") else 0) +
            len(p.get("broken_links") or []) +
            (1 if p.get("noindex") else 0)
        ),
        reverse=True
    )[:5]
    if problem_pages:
        lines.append("### Sidor med flest problem (topp 5):")
        for p in problem_pages:
            issues = []
            if not p.get("title"):        issues.append("saknar title")
            if not p.get("h1"):           issues.append("saknar H1")
            if not p.get("meta_description"): issues.append("saknar meta desc")
            if p.get("noindex"):          issues.append("noindex")
            bl = len(p.get("broken_links") or [])
            if bl:                        issues.append(f"{bl} brutna länkar")
            if issues:
                lines.append(f"  - {p.get('url', '')}: {', '.join(issues)}")
        lines.append("")

    # Competitor summaries
    comp_urls = urls[1:]
    if comp_urls:
        lines.append("## KONKURRENTDATA:")
        for cu in comp_urls:
            cd = results.get(cu, {})
            cs = cd.get("summary", {})
            lines.append(f"\n### {cu}")
            lines.append(f"- Sidor: {cs.get('total_pages', 0)}")
            lines.append(f"- Saknar title: {cs.get('missing_titles', 0)}  |  Saknar H1: {cs.get('missing_h1', 0)}")
            lines.append(f"- Saknar meta desc: {cs.get('missing_meta_desc', 0)}")
            lines.append(f"- Brutna länkar: {cs.get('broken_links', 0)}")
            lines.append(f"- Bilder utan alt: {cs.get('images_without_alt', 0)}")
        lines.append("")

    lines.append("""
Svara i EXAKT detta format (håll dig till rubrikerna):

## Sammanfattning
[3-4 meningar om klientens övergripande SEO-status]

## Topprioriteringar
1. [Viktigaste åtgärden — konkret och specifik]
2. [Nästa åtgärd]
3. [...]
4. [...]
5. [...]
6. [...]
7. [...]

## Konkurrentanalys
[Jämför klienten med konkurrenterna. Vad gör konkurrenterna bättre? Var har klienten fördelar? Vad kan klienten lära sig?]
""")
    return "\n".join(lines)


@app.post("/api/jobs/{job_id}/analyze")
def analyze_job(job_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, detail="Job not found.")
    if row["status"] != "done":
        raise HTTPException(400, detail="Job is not finished yet.")
    if not row["results"]:
        raise HTTPException(400, detail="No crawl results available.")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="OPENAI_API_KEY not configured on server.")

    results = json.loads(row["results"])
    prompt = _build_prompt(results)

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Du är en expert SEO-konsult som ger konkreta, handlingsinriktade råd på svenska."},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=1500,
        temperature=0.4,
    )

    analysis_text = response.choices[0].message.content.strip()

    db_update(job_id, analysis=analysis_text)

    return {"analysis": analysis_text}


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
