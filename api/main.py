from __future__ import annotations
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
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, HttpUrl

from crawler_engine import crawl_multiple, compute_ipr
from ahrefs_client import fetch_ref_domains, fetch_organic_keywords
from playwright_analysis import run_playwright_analysis
import wp_agent
import gsc_client
import pagespeed_client
import entity_extractor
import vision_client
import sub_agents
import memory_client
import marketing_agents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", "jobs.db")


# ── Database (SQLAlchemy — SQLite locally, PostgreSQL on Railway) ─────────────

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_DB_URL = os.environ.get("DATABASE_URL", f"sqlite:///./{DB_PATH}")
if _DB_URL.startswith("postgres://"):          # Railway uses legacy scheme
    _DB_URL = _DB_URL.replace("postgres://", "postgresql://", 1)
_IS_SQLITE = _DB_URL.startswith("sqlite")

if _IS_SQLITE:
    engine = create_engine(
        _DB_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    engine = create_engine(_DB_URL, pool_pre_ping=True, pool_size=5, max_overflow=10)

db_lock = threading.Lock()


def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                client_url      TEXT NOT NULL,
                competitor_urls TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL,
                started_at      TEXT,
                completed_at    TEXT,
                pages_crawled   INTEGER DEFAULT 0,
                error_message   TEXT,
                results         TEXT,
                analysis        TEXT
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS seo_history (
                id          TEXT PRIMARY KEY,
                site_url    TEXT NOT NULL,
                job_id      TEXT NOT NULL,
                analysis    TEXT,
                actions     TEXT,
                metrics     TEXT,
                created_at  TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS seo_memory (
            id                  TEXT PRIMARY KEY,
            site_url            TEXT NOT NULL,
            page_url            TEXT NOT NULL,
            action_type         TEXT NOT NULL,
            action_value        TEXT,
            context_text        TEXT,
            context_embedding   TEXT,
            before_metrics      TEXT,
            after_metrics       TEXT,
            reward_score        REAL,
            job_id              TEXT,
            action_taken_at     TEXT,
            reward_computed_at  TEXT
        )
    """))
    with engine.begin() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS site_documentation (
                id          TEXT PRIMARY KEY,
                site_url    TEXT NOT NULL,
                job_id      TEXT NOT NULL,
                doc_md      TEXT NOT NULL,
                created_at  TEXT NOT NULL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS managed_sites (
                url             TEXT PRIMARY KEY,
                interval_hours  INTEGER NOT NULL DEFAULT 24,
                max_pages       INTEGER NOT NULL DEFAULT 200,
                calculate_ipr   INTEGER NOT NULL DEFAULT 1,
                last_run_at     TEXT,
                next_run_at     TEXT,
                wp_url          TEXT,
                wp_user         TEXT,
                wp_app_password TEXT
            )
        """))
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_jobs (
                id           TEXT PRIMARY KEY,
                agent        TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                input_data   TEXT,
                result       TEXT,
                error        TEXT,
                created_at   TEXT NOT NULL,
                completed_at TEXT
            )
        """))
    for col in ["analysis"]:
        try:
            with engine.begin() as conn:
                stmt = f"ALTER TABLE jobs ADD COLUMN {col} TEXT"
                if not _IS_SQLITE:
                    stmt = f"ALTER TABLE jobs ADD COLUMN IF NOT EXISTS {col} TEXT"
                conn.execute(text(stmt))
        except Exception:
            pass
    for col in [
        "gsc_property_url TEXT",
        "gsc_service_account_json TEXT",
    ]:
        try:
            with engine.begin() as conn:
                stmt = f"ALTER TABLE managed_sites ADD COLUMN {col}"
                if not _IS_SQLITE:
                    stmt = f"ALTER TABLE managed_sites ADD COLUMN IF NOT EXISTS {col}"
                conn.execute(text(stmt))
        except Exception:
            pass
    for col in ["wp_url TEXT", "wp_user TEXT", "wp_app_password TEXT"]:
        try:
            with engine.begin() as conn:
                stmt = f"ALTER TABLE managed_sites ADD COLUMN {col}"
                if not _IS_SQLITE:
                    stmt = f"ALTER TABLE managed_sites ADD COLUMN IF NOT EXISTS {col}"
                conn.execute(text(stmt))
        except Exception:
            pass
    _seed_managed_sites()


def _seed_managed_sites():
    """Seed managed sites from MANAGED_SITES env var (JSON array) if table empty."""
    raw = os.environ.get("MANAGED_SITES", "")
    if not raw:
        return
    try:
        sites = json.loads(raw)
    except Exception:
        return
    with engine.begin() as conn:
        for s in sites:
            conn.execute(text("""
                INSERT INTO managed_sites (url, interval_hours, max_pages, calculate_ipr, wp_url, wp_user, wp_app_password)
                VALUES (:url, :ih, :mp, :ipr, :wurl, :wuser, :wpw)
                ON CONFLICT (url) DO NOTHING
            """), {"url": s["url"], "ih": s.get("interval_hours", 24),
                   "mp": s.get("max_pages", 200), "ipr": 1 if s.get("calculate_ipr", True) else 0,
                   "wurl": s.get("wp_url"), "wuser": s.get("wp_user"), "wpw": s.get("wp_app_password")})


def db_update(job_id: str, **kwargs):
    with db_lock:
        sets   = ", ".join(f"{k} = :{k}" for k in kwargs)
        params = {**kwargs, "_jid": job_id}
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE jobs SET {sets} WHERE id = :_jid"), params)


# ── App lifespan ──────────────────────────────────────────────────────────────

_scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _start_scheduler()
    logger.info("Amazing Tools SEO Crawler API starting up.")
    yield
    _scheduler.shutdown(wait=False)
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
    use_ahrefs:      bool      = False
    # Enhanced Playwright analysis options
    playwright_ua:              str  = "default"   # googlebot_desktop | googlebot_mobile | default
    playwright_block_resources: bool = False        # block analytics/trackers
    playwright_scroll:          bool = False        # trigger infinite scroll
    playwright_dismiss_modals:  bool = False        # try to close popups
    playwright_auth_cookies:    str  = ""          # JSON array of cookie dicts


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
              use_playwright: bool = False, calculate_ipr: bool = False,
              use_ahrefs: bool = False,
              playwright_ua: str = "default", playwright_block_resources: bool = False,
              playwright_scroll: bool = False, playwright_dismiss_modals: bool = False,
              playwright_auth_cookies: str = "",
              wp_creds: dict | None = None,
              gsc_property: str = "",
              gsc_sa_json: str = ""):

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

        # ── Playwright enhanced analysis (client URL only) ─────────────────
        if use_playwright:
            client_result = results_dict.get(client_url, {})
            pages = client_result.get("pages", [])
            urls_to_analyse = [
                p.get("url") for p in pages
                if p.get("url") and (p.get("status_code") or 0) == 200
            ][:50]  # cap at 50 pages per analysis run
            if urls_to_analyse:
                import json as _json
                _cookies = []
                if playwright_auth_cookies:
                    try:
                        _cookies = _json.loads(playwright_auth_cookies)
                    except Exception:
                        pass
                pw_options = {
                    "user_agent":       playwright_ua,
                    "block_resources":  playwright_block_resources,
                    "scroll_pages":     playwright_scroll,
                    "dismiss_modals":   playwright_dismiss_modals,
                    "auth_cookies":     _cookies,
                }
                logger.info("Playwright analysis: %d pages for %s", len(urls_to_analyse), client_url)
                try:
                    pw_results = run_playwright_analysis(urls_to_analyse, pw_options)
                    for page in pages:
                        purl = page.get("url", "")
                        if purl in pw_results:
                            pw = pw_results[purl]
                            page.update({
                                "pw_seo":          pw.get("seo", {}),
                                "pw_ux":           pw.get("ux", {}),
                                "pw_architecture": pw.get("architecture", {}),
                            })
                    logger.info("Playwright analysis complete for %s", client_url)
                except Exception as _pw_err:
                    logger.error("Playwright analysis failed: %s", _pw_err)

        # ── Ahrefs enrichment (client URL only) ─────────────────────────────
        if use_ahrefs:
            ahrefs_api_key = os.environ.get("AHREFS_API_KEY", "")
            if ahrefs_api_key:
                client_result = results_dict.get(client_url, {})
                pages = client_result.get("pages", [])
                external_authority: dict[str, float] = {}
                logger.info("Ahrefs enrichment: %d pages for %s", len(pages), client_url)
                for page in pages:
                    url = page.get("url", "")
                    if not url:
                        continue
                    ref_data = fetch_ref_domains(url, ahrefs_api_key)
                    kw_data  = fetch_organic_keywords(url, ahrefs_api_key, limit=10)
                    page["ahrefs_ref_domains_dr10"]  = ref_data["ref_domains_dr10"]
                    page["ahrefs_ref_domains_total"] = ref_data["ref_domains_total"]
                    page["ahrefs_keywords"]          = kw_data
                    external_authority[url] = float(ref_data["ref_domains_dr10"])
                    time.sleep(0.5)  # stay within Ahrefs rate limits
                # Re-run IPR with external authority personalisation
                if calculate_ipr and external_authority:
                    compute_ipr(client_result, external_authority=external_authority)
                    logger.info("IPR re-computed with Ahrefs authority for %s", client_url)
            else:
                logger.warning("use_ahrefs=True but AHREFS_API_KEY not set — skipping.")

        # ── GSC enrichment ──────────────────────────────────────────────────
        gsc_prop = gsc_property or ""
        if gsc_prop:
            gsc_data = gsc_client.fetch_gsc_data(
                site_url=gsc_prop,
                service_account_json=gsc_sa_json or None,
            )
            client_result = results_dict.get(client_url, {})
            pages = client_result.get("pages", [])
            gsc_client.merge_gsc_into_pages(pages, gsc_data)
            logger.info(
                "GSC enrichment: %d/%d pages matched for %s",
                sum(1 for p in pages if p.get("gsc_clicks") is not None),
                len(pages), client_url,
            )

        # ── PageSpeed / Core Web Vitals enrichment (top 20 pages) ──────────
        client_result = results_dict.get(client_url, {})
        pages = client_result.get("pages", [])
        psi_urls = [
            p["url"] for p in pages
            if p.get("status_code") == 200 and not p.get("noindex")
        ][:20]
        if psi_urls:
            psi_data = pagespeed_client.fetch_pagespeed_batch(
                psi_urls,
                api_key=os.environ.get("PSI_API_KEY", ""),
            )
            pagespeed_client.merge_psi_into_pages(pages, psi_data)
            logger.info(
                "PSI enrichment: %d/%d pages measured for %s",
                len(psi_data), len(psi_urls), client_url,
            )

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

        # ── Auto analyze + act ────────────────────────────────────────────
        api_key = os.environ.get("OPENAI_API_KEY")
        if api_key:
            threading.Thread(
                target=_auto_analyze_and_act,
                args=(job_id, client_url, results_dict, api_key),
                kwargs={"wp_creds": wp_creds},
                daemon=True,
            ).start()

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
    return {
        "status":  "ok",
        "service": "seo-crawler-api",
        "db":      "sqlite" if _IS_SQLITE else "postgresql",
    }


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
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO jobs (id, client_url, competitor_urls, status, created_at) "
                     "VALUES (:id, :cu, :comps, :status, :ts)"),
                {"id": job_id, "cu": req.client_url, "comps": json.dumps(req.competitor_urls),
                 "status": "pending", "ts": now},
            )

    background_tasks.add_task(
        run_crawl, job_id,
        req.client_url, req.competitor_urls,
        req.max_pages, req.check_externals, req.respect_robots,
        req.use_playwright, req.calculate_ipr, req.use_ahrefs,
        req.playwright_ua, req.playwright_block_resources,
        req.playwright_scroll, req.playwright_dismiss_modals,
        req.playwright_auth_cookies,
    )

    return {"id": job_id, "status": "pending", "created_at": now}


@app.get("/api/jobs")
def list_jobs(limit: int = 20, offset: int = 0):
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, client_url, competitor_urls, status, created_at, completed_at, pages_crawled "
                 "FROM jobs ORDER BY created_at DESC LIMIT :lim OFFSET :off"),
            {"lim": limit, "off": offset},
        ).mappings().fetchall()

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
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}
        ).mappings().fetchone()

    if not row:
        raise HTTPException(404, detail="Job not found.")

    return {
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
            headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"}
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


# ── Ahrefs integration ─────────────────────────────────────────────────────────

class AhrefsRequest(BaseModel):
    target: str        # domain or full URL
    mode:   str = "domain"  # "domain" or "url"


def _ahrefs_bonus(dr: float) -> int:
    """Map Ahrefs Domain Rating (0-100) → IPR bonus (+1 to +10) per PRD table."""
    if dr <= 0:
        return 1
    return min(10, int(dr // 10) + 1)


async def _ahrefs_get(path: str, params: dict, api_key: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(
                f"https://api.ahrefs.com/v3/{path}",
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            e.response.status_code,
            detail=f"Ahrefs API error {e.response.status_code}: {e.response.text[:300]}"
        )
    except Exception as e:
        raise HTTPException(502, detail=f"Ahrefs unreachable: {e}")


@app.post("/api/analyze/ahrefs")
async def ahrefs_analysis(req: AhrefsRequest):
    api_key = os.environ.get("AHREFS_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="AHREFS_API_KEY not configured.")

    from urllib.parse import urlparse
    raw = req.target if req.target.startswith("http") else f"https://{req.target}"
    parsed = urlparse(raw)
    domain = parsed.netloc or parsed.path.strip("/")
    target = req.target if req.mode == "url" else domain

    _today = date.today().isoformat()

    # 1) Domain Rating — primary signal, raise if it fails
    dr_resp = await _ahrefs_get(
        "site-explorer/domain-rating",
        {"target": domain, "date": _today},
        api_key,
    )
    # Ahrefs v3 may return {"domain": {"domain_rating": N}} or {"domain_rating": N}
    _dr_obj = dr_resp.get("domain") or dr_resp
    dr = float(_dr_obj.get("domain_rating") or _dr_obj.get("dr") or 0)
    domain_bonus = _ahrefs_bonus(dr)

    # 2) Referring domains count — best-effort, skip if unavailable
    refdomains_count = 0
    try:
        ref_resp = await _ahrefs_get(
            "site-explorer/refdomains",
            {"target": domain, "mode": "domain", "limit": 1,
             "select": "referring_domain,domain_rating_source", "date": _today},
            api_key,
        )
        refdomains_count = ref_resp.get("total", 0) or len(ref_resp.get("refdomains") or [])
    except Exception:
        pass

    # 3) Top backlinks with per-link DR — best-effort
    raw_links: list = []
    try:
        bl_resp = await _ahrefs_get(
            "site-explorer/backlinks",
            {
                "target":  target,
                "limit":   50,
                "mode":    req.mode,
                "select":  "url_from,domain_from,domain_rating_source,anchor,nofollow,url_to",
                "date":    _today,
            },
            api_key,
        )
        raw_links = bl_resp.get("backlinks") or []
    except Exception:
        pass

    enriched = []
    total_bonus = 0
    for bl in raw_links:
        dr_src = float(bl.get("domain_rating_source") or 0)
        bonus  = _ahrefs_bonus(dr_src)
        total_bonus += bonus
        enriched.append({
            "url_from":    bl.get("url_from", ""),
            "domain_from": bl.get("domain_from", ""),
            "dr":          round(dr_src, 1),
            "bonus":       bonus,
            "anchor":      bl.get("anchor", ""),
            "nofollow":    bool(bl.get("nofollow", False)),
            "url_to":      bl.get("url_to", ""),
        })

    enriched.sort(key=lambda x: x["dr"], reverse=True)

    return {
        "domain":              domain,
        "target":              target,
        "domain_rating":       round(dr, 1),
        "domain_ipr_bonus":    domain_bonus,
        "total_backlink_bonus":total_bonus,
        "backlinks_count":     len(enriched),
        "referring_domains":   refdomains_count,
        "organic_traffic":     0,
        "backlinks":           enriched,
    }


# ── Ahrefs per-page keywords (on-demand from results page) ───────────────────

class AhrefsKeywordsRequest(BaseModel):
    urls:  list[str]
    limit: int = 10


@app.post("/api/analyze/ahrefs-keywords")
async def ahrefs_keywords_analysis(req: AhrefsKeywordsRequest):
    api_key = os.environ.get("AHREFS_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="AHREFS_API_KEY not configured.")
    if not req.urls:
        raise HTTPException(400, detail="urls list is empty.")

    import asyncio
    from ahrefs_client import fetch_organic_keywords as _fetch_kw

    async def _fetch_one(url: str) -> dict:
        kws = await asyncio.to_thread(_fetch_kw, url, api_key, req.limit)
        return {"url": url, "keywords": kws}

    tasks = [_fetch_one(u) for u in req.urls[:30]]  # cap at 30 pages
    pages = await asyncio.gather(*tasks, return_exceptions=False)
    pages = [p for p in pages if p["keywords"]]     # drop empty
    return {"pages": pages}


# ── PageSpeed Insights ────────────────────────────────────────────────────────

@app.get("/api/analyze/pagespeed")
async def pagespeed_analysis(url: str, strategy: str = "mobile"):
    """
    Calls Google PageSpeed Insights v5 API and returns structured CWV metrics.
    Requires PSI_API_KEY environment variable.
    strategy: "mobile" | "desktop"
    """
    api_key = os.environ.get("PSI_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="PSI_API_KEY not configured on server.")

    try:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.get(
                "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                params={
                    "url":      url,
                    "key":      api_key,
                    "strategy": strategy,
                    "category": "performance",
                },
            )
            if r.status_code != 200:
                raise HTTPException(r.status_code,
                    detail=f"PSI API error {r.status_code}: {r.text[:300]}")
            data = r.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, detail=f"PSI unreachable: {e}")

    lhr      = data.get("lighthouseResult", {})
    audits   = lhr.get("audits", {})
    cats     = lhr.get("categories", {})

    def ms(key):   return round(audits.get(key, {}).get("numericValue") or 0)
    def sc(key):   return round((audits.get(key, {}).get("score") or 0) * 100)
    def flt(key):  return round(audits.get(key, {}).get("numericValue") or 0, 3)

    perf = round((cats.get("performance", {}).get("score") or 0) * 100)

    return {
        "url":               url,
        "strategy":          strategy,
        "performance_score": perf,
        "fcp_ms":            ms("first-contentful-paint"),
        "lcp_ms":            ms("largest-contentful-paint"),
        "cls":               flt("cumulative-layout-shift"),
        "tbt_ms":            ms("total-blocking-time"),
        "speed_index_ms":    ms("speed-index"),
        "tti_ms":            ms("interactive"),
        "fcp_score":         sc("first-contentful-paint"),
        "lcp_score":         sc("largest-contentful-paint"),
        "cls_score":         sc("cumulative-layout-shift"),
        "tbt_score":         sc("total-blocking-time"),
        "si_score":          sc("speed-index"),
    }


# ── Ahrefs debug endpoint ─────────────────────────────────────────────────────

@app.get("/api/debug/ahrefs")
async def debug_ahrefs(url: str = "https://ahrefs.com"):
    """
    Raw Ahrefs API probe. Hit this to see exactly what the API returns
    so field names / auth issues can be diagnosed.
    Example: GET /api/debug/ahrefs?url=https://example.com
    """
    api_key = os.environ.get("AHREFS_API_KEY", "")
    if not api_key:
        return {"error": "AHREFS_API_KEY not set on server"}

    from urllib.parse import urlparse as _up
    _parsed = _up(url if url.startswith("http") else f"https://{url}")
    domain  = _parsed.netloc or url.strip("/")

    results: dict = {}
    for label, path, params in [
        ("refdomains_sample", "site-explorer/refdomains",
         {"target": domain, "mode": "domain", "select": "domain_rating_source,referring_domain", "limit": "3"}),
        ("organic_kw_sample", "site-explorer/organic-keywords",
         {"target": url, "mode": "exact", "select": "keyword,pos,volume,traffic", "limit": "3", "order_by": "traffic:desc"}),
        ("domain_rating", "site-explorer/domain-rating",
         {"target": domain}),
    ]:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(
                    f"https://api.ahrefs.com/v3/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                results[label] = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text[:500]}
        except Exception as e:
            results[label] = {"error": str(e)}

    return results


# ── AI analysis ───────────────────────────────────────────────────────────────

def _get_learning_context(site_url: str, limit: int = 3) -> str:
    """Return a summary of the last N analyses for a site, for use in prompts."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT analysis, actions, metrics, created_at FROM seo_history "
                     "WHERE site_url = :url ORDER BY created_at DESC LIMIT :lim"),
                {"url": site_url, "lim": limit},
            ).mappings().fetchall()
        if not rows:
            return ""
        parts = ["## HISTORIK (senaste körningar, för inlärning och trendanalys):\n"]
        for i, row in enumerate(rows, 1):
            ts = (row["created_at"] or "")[:10]
            analysis_snippet = (row["analysis"] or "")[:800]
            metrics = json.loads(row["metrics"]) if row["metrics"] else {}
            actions = json.loads(row["actions"]) if row["actions"] else []
            ok_actions = [a for a in actions if a.get("ok")]
            parts.append(f"### Körning {i} ({ts}):")
            if metrics:
                parts.append(f"  Metrics: sidor={metrics.get('total_pages','?')}, "
                             f"orphaned={metrics.get('orphaned_pages','?')}, "
                             f"missing_titles={metrics.get('missing_titles','?')}, "
                             f"total_links={metrics.get('total_internal_links','?')}")
            if ok_actions:
                parts.append(f"  Åtgärder utförda: {len(ok_actions)} st")
                for a in ok_actions[:5]:
                    atype = a.get("action", {}).get("type", "?")
                    aurl  = a.get("action", {}).get("url") or a.get("action", {}).get("source_url", "?")
                    parts.append(f"    - {atype}: {aurl}")
            if analysis_snippet:
                parts.append(f"  Analys-sammanfattning:\n{analysis_snippet}")
            parts.append("")
        return "\n".join(parts)
    except Exception as e:
        logger.warning("_get_learning_context failed: %s", e)
        return ""


def _extract_metrics(results: dict, client_url: str) -> dict:
    """Extract key summary metrics from crawl results for a site."""
    s = results.get(client_url, {}).get("summary", {})
    return {
        "total_pages":        s.get("total_pages", 0),
        "missing_titles":     s.get("missing_titles", 0),
        "missing_h1":         s.get("missing_h1", 0),
        "missing_meta_desc":  s.get("missing_meta_desc", 0),
        "orphaned_pages":     s.get("orphaned_pages", 0),
        "total_internal_links": s.get("total_internal_links", 0),
        "broken_links":       s.get("broken_links", 0),
    }


def _build_action_prompt(results: dict, client_url: str, analysis: str) -> str:
    """Build a prompt asking GPT-4o for a JSON list of concrete WordPress actions."""
    pages = results.get(client_url, {}).get("pages", [])

    missing_titles = [
        {"url": p["url"], "h1": p.get("h1") or "", "words": p.get("word_count", 0)}
        for p in pages if not p.get("title") and p.get("status_code") == 200
    ][:20]

    missing_meta = [
        {"url": p["url"], "title": p.get("title") or "", "h1": p.get("h1") or ""}
        for p in pages if not p.get("meta_description") and p.get("status_code") == 200
    ][:20]

    orphaned = [
        {"url": p["url"], "title": p.get("title") or p.get("h1") or "", "words": p.get("word_count", 0)}
        for p in pages
        if p.get("ipr_inbound", 0) == 0 and p.get("status_code") == 200 and not p.get("noindex")
    ][:15]

    all_pages = [
        {"url": p["url"], "title": p.get("title") or p.get("h1") or p["url"].rstrip("/").split("/")[-1]}
        for p in pages if p.get("status_code") == 200
    ]

    return f"""You are an SEO automation agent. Given the analysis below and site data, produce a JSON object with an "actions" key containing an array of WordPress actions to execute.

Site: {client_url}

Analysis summary:
{analysis[:1200]}

Pages missing title ({len(missing_titles)}):
{json.dumps(missing_titles[:10], ensure_ascii=False)}

Pages missing meta description ({len(missing_meta)}):
{json.dumps(missing_meta[:10], ensure_ascii=False)}

Orphaned pages — 0 internal inbound links ({len(orphaned)}):
{json.dumps(orphaned[:10], ensure_ascii=False)}

All crawled pages (for link targets):
{json.dumps(all_pages[:30], ensure_ascii=False)}

Return a JSON object in this exact format:
{{"actions": [
  {{"type": "update_title",      "url": "...", "title": "..."}},
  {{"type": "update_meta_desc",  "url": "...", "meta_desc": "..."}},
  {{"type": "add_internal_link", "source_url": "...", "anchor_text": "...", "target_url": "..."}}
]}}

Rules:
- Write titles as: "Keyword — Site Name" max 60 chars, in the same language as the page content
- Write meta descriptions: compelling, 140-155 chars, include target keyword, in same language
- For internal links: pick natural anchor text that plausibly exists in the source page content
- Add 2-4 internal links pointing TO each orphaned page from topically related content pages
- Max 40 actions total. Prioritize: meta_desc > title > internal links
- Output ONLY the JSON object, no markdown code fences, no explanation
"""


def _reward_cron_job():
    """Weekly cron: compute reward scores for past SEO actions using fresh GSC data."""
    logger.info("[reward-cron] Starting weekly reward computation")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("[reward-cron] OPENAI_API_KEY not set — skipping")
        return
    memory_client.run_reward_cron(engine, db_lock, api_key)


def _auto_analyze_and_act(job_id: str, client_url: str, results_dict: dict, api_key: str, wp_creds: dict | None = None):
    """Run after crawl: sub-agent analysis, action extraction, WP execution, memory + history."""
    logger.info("[auto-agent] Starting for job %s (%s)", job_id, client_url)
    oai          = OpenAI(api_key=api_key)
    client_data  = results_dict.get(client_url, {})
    pages        = client_data.get("pages", [])
    metrics      = _extract_metrics(results_dict, client_url)
    now          = datetime.now(timezone.utc).isoformat()

    # ── Phase 2a: Entity extraction ────────────────────────────────────
    try:
        entity_extractor.extract_entities_for_pages(pages, api_key)
        logger.info("[auto-agent] Entities done for job %s", job_id)
    except Exception as e:
        logger.warning("[auto-agent] Entity extraction failed: %s", e)

    # ── Phase 2b: Vision alt-text actions ────────────────────────────
    vision_actions: list[dict] = []
    try:
        vision_actions = vision_client.generate_alt_texts_for_job(pages, api_key)
        logger.info("[auto-agent] Vision: %d alt-text actions", len(vision_actions))
    except Exception as e:
        logger.warning("[auto-agent] Vision alt-text failed: %s", e)

    # ── Phase 4: Retrieve similar past memories for learning context ───────
    memory_context = ""
    try:
        ctx_summary = (
            f"site:{client_url}  pages:{metrics.get('total_pages',0)}  "
            f"4xx:{metrics.get('pages_4xx',0)}  missing_titles:{metrics.get('missing_titles',0)}"
        )
        memories = memory_client.retrieve_similar(
            engine, ctx_summary, api_key, limit=5
        )
        memory_context = memory_client.build_memory_prompt(memories)
    except Exception as e:
        logger.warning("[auto-agent] Memory retrieval failed: %s", e)

    # ── Phase 3a: Tech SEO Agent ────────────────────────────────────────
    tech_text = ""
    try:
        tech_text = sub_agents.run_tech_seo_agent(pages, metrics, client_url, oai)
    except Exception as e:
        logger.error("[auto-agent] Tech agent failed: %s", e)

    # ── Phase 3b: Content SEO Agent ──────────────────────────────────
    content_actions: list[dict] = []
    try:
        content_actions = sub_agents.run_content_seo_agent(
            pages, client_url, oai, memory_context=memory_context
        )
    except Exception as e:
        logger.error("[auto-agent] Content agent failed: %s", e)

    # ── Phase 3c: Master Agent ─────────────────────────────────────────
    analysis_text  = tech_text
    actions_json: list[dict] = []
    try:
        analysis_text, actions_json = sub_agents.run_master_agent(
            tech_text, content_actions, vision_actions, client_url, oai
        )
        db_update(job_id, analysis=analysis_text)
        logger.info("[auto-agent] Master agent: %d final actions", len(actions_json))
    except Exception as e:
        logger.error("[auto-agent] Master agent failed: %s", e)
        db_update(job_id, analysis=analysis_text)

    # ── Execute actions via WordPress API ─────────────────────────────
    action_results: list[dict] = []
    if actions_json:
        try:
            action_results = wp_agent.execute_actions(actions_json, override=wp_creds)
            ok = sum(1 for r in action_results if r.get("ok"))
            logger.info("[auto-agent] WP actions: %d/%d succeeded", ok, len(action_results))
        except Exception as e:
            logger.error("[auto-agent] WP action execution failed: %s", e)

    # ── Phase 4: Store successful actions in memory ──────────────────────
    try:
        for act, result in zip(actions_json, action_results):
            if not result.get("ok"):
                continue
            p_url  = act.get("url") or act.get("page_url", "")
            page_d = next((p for p in pages if p.get("url") == p_url), {})
            before = {
                "gsc_ctr":         page_d.get("gsc_ctr"),
                "gsc_position":    page_d.get("gsc_position"),
                "gsc_impressions": page_d.get("gsc_impressions"),
            }
            ctx = (
                f"site:{client_url}  page:{p_url}  "
                f"entities:{page_d.get('entities', [])[:5]}  "
                f"words:{page_d.get('word_count',0)}"
            )
            atype = act.get("type") or act.get("action", "")
            aval  = act.get("title") or act.get("meta_desc") or act.get("new_value") or act.get("alt_text", "")
            memory_client.store_action(engine, db_lock,
                site_url=client_url, page_url=p_url,
                action_type=atype, action_value=aval,
                context_text=ctx, before_metrics=before,
                api_key=api_key, job_id=job_id)
    except Exception as e:
        logger.warning("[auto-agent] Memory store failed: %s", e)

    # ── Step 4: save history ─────────────────────────────────────────────────
    metrics = _extract_metrics(results_dict, client_url)
    history_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db_lock:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO seo_history (id, site_url, job_id, analysis, actions, metrics, created_at)
                    VALUES (:id, :site, :jid, :analysis, :actions, :metrics, :ts)
                """), {
                    "id":       history_id,
                    "site":     client_url,
                    "jid":      job_id,
                    "analysis": analysis_text,
                    "actions":  json.dumps(action_results),
                    "metrics":  json.dumps(metrics),
                    "ts":       now,
                })
    except Exception as e:
        logger.error("[auto-agent] History save failed: %s", e)

    # ── Step 5: generate and save site documentation ──────────────────────
    try:
        ok_actions = [r for r in action_results if r.get("ok")]
        doc_prompt = (
            f"Write a short markdown documentation (max 300 words, bullet points) summarising "
            f"what was done on {client_url} in this SEO agent run.\n"
            f"Include: date ({now[:10]}), pages crawled ({metrics.get('total_pages',0)}), "
            f"key issues found (missing titles: {metrics.get('missing_titles',0)}, "
            f"missing meta: {metrics.get('missing_meta_desc',0)}, "
            f"orphaned pages: {metrics.get('orphaned_pages',0)}, "
            f"broken links: {metrics.get('broken_links',0)}), "
            f"actions applied ({len(ok_actions)} of {len(action_results)} succeeded).\n"
            f"Analysis summary (first 600 chars):\n{analysis_text[:600]}"
        )
        doc_resp = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": doc_prompt}],
            max_tokens=500,
            temperature=0.3,
        )
        doc_md = doc_resp.choices[0].message.content.strip()
        doc_id = str(uuid.uuid4())[:8]
        with db_lock:
            with engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO site_documentation (id, site_url, job_id, doc_md, created_at)
                    VALUES (:id, :site, :jid, :doc, :ts)
                """), {"id": doc_id, "site": client_url, "jid": job_id, "doc": doc_md, "ts": now})
        logger.info("[auto-agent] Site doc saved id=%s for job %s", doc_id, job_id)
    except Exception as e:
        logger.error("[auto-agent] Site doc generation failed: %s", e)

    logger.info("[auto-agent] Done for job %s — history id=%s", job_id, history_id)


def _scheduled_crawl(
    site_url: str,
    max_pages: int = 200,
    calculate_ipr: bool = True,
    wp_creds: dict | None = None,
    gsc_property: str = "",
    gsc_sa_json: str = "",
):
    """Called by scheduler: create and run a crawl job for a managed site."""
    logger.info("[scheduler] Starting scheduled crawl for %s", site_url)
    job_id = str(uuid.uuid4())[:8]
    now    = datetime.now(timezone.utc).isoformat()
    # Load GSC creds from DB if not passed directly (e.g. after server restart)
    if not gsc_property:
        try:
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT gsc_property_url, gsc_service_account_json FROM managed_sites WHERE url=:url"),
                    {"url": site_url},
                ).mappings().fetchone()
            if row:
                gsc_property = row["gsc_property_url"] or ""
                gsc_sa_json  = row["gsc_service_account_json"] or ""
        except Exception:
            pass
    with db_lock:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO jobs (id, client_url, competitor_urls, status, created_at) "
                     "VALUES (:id, :cu, :comps, :status, :ts)"),
                {"id": job_id, "cu": site_url, "comps": "[]", "status": "pending", "ts": now},
            )
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE managed_sites SET last_run_at=:ts WHERE url=:url"),
                {"ts": now, "url": site_url}
            )
    except Exception:
        pass
    run_crawl(
        job_id, site_url, [], max_pages, True, True,
        calculate_ipr=calculate_ipr, wp_creds=wp_creds,
        gsc_property=gsc_property, gsc_sa_json=gsc_sa_json,
    )


def _start_scheduler():
    """Read managed_sites from DB and schedule periodic crawls."""
    try:
        with engine.connect() as conn:
            sites = conn.execute(text("SELECT * FROM managed_sites")).mappings().fetchall()
    except Exception:
        return

    for site in sites:
        url   = site["url"]
        hours = int(site["interval_hours"] or 24)
        mp    = int(site["max_pages"] or 200)
        ipr   = bool(site["calculate_ipr"])
        wp_creds = None
        if site.get("wp_url") or site.get("wp_user"):
            wp_creds = {"wp_url": site.get("wp_url"), "wp_user": site.get("wp_user"), "wp_app_password": site.get("wp_app_password")}
        _scheduler.add_job(
            _scheduled_crawl,
            trigger="interval",
            hours=hours,
            args=[url, mp, ipr],
            kwargs={
                "wp_creds":    wp_creds,
                "gsc_property": site.get("gsc_property_url") or "",
                "gsc_sa_json":  site.get("gsc_service_account_json") or "",
            },
            id=f"crawl_{url}",
            replace_existing=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=2),
        )
        logger.info("[scheduler] Scheduled %s every %dh", url, hours)

    # Weekly reward cron (Phase 4)
    _scheduler.add_job(
        _reward_cron_job,
        trigger="interval",
        hours=168,
        id="reward_cron",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    logger.info("[scheduler] Reward cron scheduled (weekly)")

    if not _scheduler.running:
        _scheduler.start()


def _build_prompt(results: dict, learning_context: str = "") -> str:
    urls = list(results.keys())
    client_url = urls[0]
    client = results[client_url]
    s = client.get("summary", {})
    pages = client.get("pages", [])

    lines = [
        "Du är en expert SEO-konsult. Analysera all crawldata nedan och svara ENBART på svenska.\n",
        f"## KLIENTENS WEBBPLATS: {client_url}",
        f"- Crawlade sidor: {s.get('total_pages', 0)}",
        f"- HTTP 200: {s.get('pages_200', 0)}  |  3xx: {s.get('pages_3xx', 0)}  |  4xx-fel: {s.get('pages_4xx', 0)}  |  5xx-fel: {s.get('pages_5xx', 0)}",
        f"- Saknar title-tag: {s.get('missing_titles', 0)}  |  Dubblerade titlar: {s.get('duplicate_titles', 0)}",
        f"- Saknar H1: {s.get('missing_h1', 0)}  |  Dubblerade H1: {s.get('duplicate_h1', 0)}",
        f"- Saknar meta description: {s.get('missing_meta_desc', 0)}  |  För lång: {s.get('long_meta_desc', 0)}  |  För kort: {s.get('short_meta_desc', 0)}",
        f"- Saknar canonical: {s.get('missing_canonical', 0)}  |  Noindex-sidor: {s.get('noindex_count', 0)}",
        f"- Totalt brutna interna länkar: {s.get('broken_links', 0)}",
        f"- Bilder utan alt-text: {s.get('images_without_alt', 0)}",
        f"- Totalt interna länkar (crawlen): {s.get('total_internal_links', 0)}",
        f"- Föräldralösa sidor (0 inbound): {s.get('orphaned_pages', 0)}",
        "",
    ]

    # ── Internal PageRank (IPR) ──────────────────────────────────────────────
    ipr_pages = [p for p in pages if p.get("ipr") is not None]
    if ipr_pages:
        sorted_ipr = sorted(ipr_pages, key=lambda p: p.get("ipr", 0), reverse=True)
        lines.append("### Internal PageRank (IPR) — topp 10 sidor (högst länkauktoritet):")
        for p in sorted_ipr[:10]:
            ib = p.get("ipr_inbound", "?")
            ob = p.get("ipr_outbound", "?")
            lines.append(f"  {p.get('ipr', 0):.3f}  ib={ib} ob={ob}  {p.get('url','')}")

        bottom_ipr = [p for p in sorted_ipr if p.get("ipr_inbound", 0) == 0 and p.get("status_code") == 200]
        if bottom_ipr:
            lines.append(f"\n### Föräldralösa sidor — 0 inbound interna länkar ({len(bottom_ipr)} st), urval:")
            for p in bottom_ipr[:8]:
                lines.append(f"  - {p.get('url','')}")

        # Link sink pages (many inbound, few outbound — potential PageRank drain)
        sinks = sorted(
            [p for p in ipr_pages if p.get("ipr_outbound", 0) == 0 and p.get("ipr_inbound", 0) > 1],
            key=lambda p: p.get("ipr_inbound", 0), reverse=True
        )[:5]
        if sinks:
            lines.append("\n### Länk-sänkor — sidor med inbound men 0 outbound (tappar PageRank):")
            for p in sinks:
                lines.append(f"  ib={p.get('ipr_inbound')}  {p.get('url','')}")
        lines.append("")

    # ── Broken links with URLs ───────────────────────────────────────────────
    broken_detail = []
    for p in pages:
        for bl in (p.get("broken_links") or []):
            broken_detail.append((p.get("url", ""), bl.get("url", ""), bl.get("status", "?")))
    if broken_detail:
        lines.append(f"### Brutna interna länkar ({len(broken_detail)} st) — urval topp 10:")
        for src, dst, code in broken_detail[:10]:
            lines.append(f"  [{code}] {dst}  (länkad från: {src})")
        lines.append("")

    # ── Thin content ────────────────────────────────────────────────────────
    thin = sorted(
        [p for p in pages if p.get("word_count", 0) < 200 and p.get("status_code") == 200
         and not p.get("noindex")],
        key=lambda p: p.get("word_count", 0)
    )[:8]
    if thin:
        lines.append(f"### Tunt innehåll — sidor under 200 ord ({len(thin)} st urval):")
        for p in thin:
            lines.append(f"  {p.get('word_count', 0)} ord  {p.get('url','')}")
        lines.append("")

    # ── Pages with critical issues (top 10) ─────────────────────────────────
    def issue_score(p):
        return (
            (1 if not p.get("title") else 0) +
            (1 if not p.get("h1") else 0) +
            (1 if not p.get("meta_description") else 0) +
            len(p.get("broken_links") or []) * 2 +
            (1 if p.get("noindex") else 0)
        )
    problem_pages = sorted(pages, key=issue_score, reverse=True)[:10]
    has_issues = [p for p in problem_pages if issue_score(p) > 0]
    if has_issues:
        lines.append("### Sidor med flest SEO-problem (topp 10):")
        for p in has_issues:
            issues = []
            if not p.get("title"):            issues.append("saknar title")
            if not p.get("h1"):               issues.append("saknar H1")
            if not p.get("meta_description"): issues.append("saknar meta desc")
            if p.get("noindex"):              issues.append("noindex")
            bl = len(p.get("broken_links") or [])
            if bl:                            issues.append(f"{bl} brutna utgående")
            wc = p.get("word_count", 0)
            if 0 < wc < 200:                  issues.append(f"tunt innehåll ({wc} ord)")
            if issues:
                lines.append(f"  - {p.get('url','')}: {', '.join(issues)}")
        lines.append("")

    # ── External links summary ───────────────────────────────────────────────
    total_ext = sum(p.get("external_links_count", 0) for p in pages)
    pages_with_ext = [p for p in pages if p.get("external_links_count", 0) > 3]
    lines.append(f"### Externa länkar: totalt {total_ext} utgående externa länkar")
    if pages_with_ext:
        top_ext = sorted(pages_with_ext, key=lambda p: p.get("external_links_count", 0), reverse=True)[:5]
        lines.append("  Sidor med flest externa utgående länkar:")
        for p in top_ext:
            lines.append(f"  - {p.get('external_links_count')} ext  {p.get('url','')}")
    lines.append("")

    # ── Google Search Console data ─────────────────────────────────────
    gsc_pages = [p for p in pages if p.get("gsc_impressions") is not None]
    if gsc_pages:
        low_ctr = sorted(
            [p for p in gsc_pages if (p.get("gsc_impressions") or 0) >= 50],
            key=lambda p: p.get("gsc_ctr") or 100,
        )[:8]
        high_pos = sorted(
            [p for p in gsc_pages if (p.get("gsc_position") or 99) > 10],
            key=lambda p: p.get("gsc_impressions") or 0, reverse=True,
        )[:8]
        lines.append(f"### Google Search Console (senaste 28 dagarna) — {len(gsc_pages)} sidor med data:")
        if low_ctr:
            lines.append("  Låg CTR (hög exponering, låg klickfrekvens) — kandidater för title/meta-optimering:")
            for p in low_ctr:
                lines.append(
                    f"    CTR={p.get('gsc_ctr')}%  pos={p.get('gsc_position')}  "
                    f"imp={p.get('gsc_impressions')}  klick={p.get('gsc_clicks')}  {p.get('url','')}"
                )
        if high_pos:
            lines.append("  Sidor på position 11-20 (nära första sidan) — prioritera för optimering:")
            for p in high_pos:
                lines.append(
                    f"    pos={p.get('gsc_position')}  imp={p.get('gsc_impressions')}  "
                    f"CTR={p.get('gsc_ctr')}%  {p.get('url','')}"
                )
        lines.append("")

    # ── PageSpeed / Core Web Vitals ──────────────────────────────────────
    psi_pages = [p for p in pages if p.get("psi_lcp_ms") is not None]
    if psi_pages:
        bad_lcp  = [p for p in psi_pages if (p.get("psi_lcp_ms") or 0) > 2500]
        bad_cls  = [p for p in psi_pages if (p.get("psi_cls") or 0) > 0.1]
        bad_inp  = [p for p in psi_pages if (p.get("psi_inp_ms") or 0) > 200]
        avg_score = round(sum(p.get("psi_score", 0) for p in psi_pages) / len(psi_pages))
        lines.append(f"### Core Web Vitals (PageSpeed Insights, {len(psi_pages)} sidor mätta):")
        lines.append(f"  Snittpoäng: {avg_score}/100  |  Dålig LCP(>2.5s): {len(bad_lcp)}  "
                     f"|  Dålig CLS(>0.1): {len(bad_cls)}  |  Dålig INP(>200ms): {len(bad_inp)}")
        worst = sorted(psi_pages, key=lambda p: p.get("psi_score", 100))[:5]
        if worst:
            lines.append("  Sämst presterande sidor:")
            for p in worst:
                lines.append(
                    f"    score={p.get('psi_score')}  LCP={p.get('psi_lcp_ms')}ms  "
                    f"CLS={p.get('psi_cls')}  INP={p.get('psi_inp_ms')}ms  {p.get('url','')}"
                )
        lines.append("")
    else:
        lines.append("### Core Web Vitals: mätning ej genomförd (PSI_API_KEY saknas eller inga sidor mätta)")
        lines.append("")

    # ── Competitor summaries ─────────────────────────────────────────────────
    comp_urls = urls[1:]
    if comp_urls:
        lines.append("## KONKURRENTDATA:")
        for cu in comp_urls:
            cd = results.get(cu, {})
            cs = cd.get("summary", {})
            cp  = cd.get("pages", [])
            ci  = [p for p in cp if p.get("ipr") is not None]
            lines.append(f"\n### {cu}")
            lines.append(f"- Sidor: {cs.get('total_pages', 0)}")
            lines.append(f"- Saknar title: {cs.get('missing_titles', 0)}  |  Saknar H1: {cs.get('missing_h1', 0)}")
            lines.append(f"- Saknar meta desc: {cs.get('missing_meta_desc', 0)}")
            lines.append(f"- Brutna länkar: {cs.get('broken_links', 0)}")
            lines.append(f"- Bilder utan alt: {cs.get('images_without_alt', 0)}")
            lines.append(f"- Föräldralösa sidor: {cs.get('orphaned_pages', 0)}")
            lines.append(f"- Totalt interna länkar: {cs.get('total_internal_links', 0)}")
            if ci:
                top_c = max(ci, key=lambda p: p.get("ipr", 0))
                lines.append(f"- Högsta IPR-sida: {top_c.get('ipr', 0):.3f}  {top_c.get('url','')}")

        lines.append("")

        # ── Learning context ────────────────────────────────────────────────────
    if learning_context:
        lines.append(learning_context)
        lines.append("")

    lines.append("""
Svara i EXAKT detta format (håll dig strikt till rubrikerna, ge konkreta URL-exempel där relevant):

## Sammanfattning
[4-5 meningar om klientens övergripande SEO-status — inkludera starka och svaga sidor]

## Topprioriteringar
1. [Viktigaste åtgärden — konkret, specifik, nämn URL om relevant]
2. [Intern länkstruktur / IPR-optimering — specifika sidor att åtgärda]
3. [Tekniska SEO-problem]
4. [Innehållskvalitet / tunt innehåll]
5. [Externa länkar / länkprofil]
6. [Meta-data och on-page SEO]
7. [PageSpeed — förbered för integration, vad att tänka på nu]
8. [Övrigt med stor potential]

## Intern länkstrategi
[Specifika rekommendationer för IPR-optimering: vilka sidor behöver mer inbound-länkar, vilka är länksänkor, hur fördela länkauktoriteten bättre. Nämn konkreta URL:er.]

## Konkurrentanalys
[Jämför klienten med konkurrenterna. Vad gör konkurrenterna bättre? Var har klienten fördelar? Kvantifiera skillnaderna med data från ovan.]
""")
    return "\n".join(lines)


@app.post("/api/jobs/{job_id}/analyze")
def analyze_job(job_id: str, apply_actions: bool = True):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}
        ).mappings().fetchone()

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
    client_url = row["client_url"]

    if apply_actions:
        threading.Thread(
            target=_auto_analyze_and_act,
            args=(job_id, client_url, results, api_key),
            daemon=True,
        ).start()
        return {"status": "analyzing", "message": "Analysis + actions started in background — check /api/history for results."}

    learning_ctx = _get_learning_context(client_url)
    prompt = _build_prompt(results, learning_context=learning_ctx)

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Du är en expert SEO-konsult som ger konkreta, handlingsinriktade råd på svenska."},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=3000,
        temperature=0.4,
    )

    analysis_text = response.choices[0].message.content.strip()
    db_update(job_id, analysis=analysis_text)
    return {"analysis": analysis_text}


class ChatMessage(BaseModel):
    role:    str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    context: str = ""


@app.post("/api/chat")
async def mevo_chat(req: ChatRequest):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(500, detail="OPENAI_API_KEY not configured.")

    system_prompt = (
        "Du är MEVO, en AI-assistent specialiserad inom SEO och digital marknadsföring. "
        "Du arbetar på Amazing Tools-plattformen och hjälper användare att analysera och presentera "
        "SEO-data för sina kunder. Svara alltid på svenska om inte användaren skriver på ett annat "
        "språk. Du är professionell, vänlig och konkret. Du kan hjälpa till med sökordsanalys, "
        "länkstrategi, on-page SEO, intern länkning, presentationsmaterial och strategiska råd. "
        "Håll svaren kortfattade och handlingsinriktade."
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if req.context:
        messages.append({"role": "system", "content": f"Kontext om aktuell data:\n{req.context}"})
    for m in req.history[-12:]:
        messages.append({"role": m.role, "content": m.content})
    messages.append({"role": "user", "content": req.message})

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=600,
            temperature=0.7,
        )
        return {"reply": resp.choices[0].message.content.strip()}
    except Exception as e:
        raise HTTPException(500, detail=f"Chat error: {e}")


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM jobs WHERE id = :id"), {"id": job_id}
        ).mappings().fetchone()
    if not row:
        raise HTTPException(404, detail="Job not found.")
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM jobs WHERE id = :id"), {"id": job_id})
    return None


# ── Memory endpoints (Phase 4) ────────────────────────────────────────────────────

@app.get("/api/memory")
def get_memory(
    site_url: str = "",
    action_type: str = "",
    min_reward: float = -999,
    limit: int = 50,
):
    """Browse the SEO action memory store. Filter by site, action type, or min reward score."""
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, site_url, page_url, action_type, action_value,
                   context_text, reward_score, before_metrics, after_metrics,
                   job_id, action_taken_at, reward_computed_at
            FROM seo_memory
            WHERE (:site = '' OR site_url = :site)
              AND (:atype = '' OR action_type = :atype)
              AND (reward_score IS NULL OR reward_score >= :minr)
            ORDER BY action_taken_at DESC
            LIMIT :lim
        """), {"site": site_url, "atype": action_type,
               "minr": min_reward, "lim": limit}).mappings().fetchall()
    return [
        {
            "id":                r["id"],
            "site_url":          r["site_url"],
            "page_url":          r["page_url"],
            "action_type":       r["action_type"],
            "action_value":      r["action_value"],
            "context_text":      r["context_text"],
            "reward_score":      r["reward_score"],
            "before_metrics":    json.loads(r["before_metrics"]) if r["before_metrics"] else {},
            "after_metrics":     json.loads(r["after_metrics"])  if r["after_metrics"]  else None,
            "job_id":            r["job_id"],
            "action_taken_at":   r["action_taken_at"],
            "reward_computed_at": r["reward_computed_at"],
        }
        for r in rows
    ]


# ── History + actions endpoints ─────────────────────────────────────────────────────

@app.get("/api/history")
def get_history(site_url: str = "", limit: int = 20):
    """Return SEO analysis history, optionally filtered by site."""
    with engine.connect() as conn:
        if site_url:
            rows = conn.execute(
                text("SELECT id, site_url, job_id, analysis, actions, metrics, created_at "
                     "FROM seo_history WHERE site_url = :url ORDER BY created_at DESC LIMIT :lim"),
                {"url": site_url, "lim": limit},
            ).mappings().fetchall()
        else:
            rows = conn.execute(
                text("SELECT id, site_url, job_id, analysis, actions, metrics, created_at "
                     "FROM seo_history ORDER BY created_at DESC LIMIT :lim"),
                {"lim": limit},
            ).mappings().fetchall()
    return [
        {
            "id":         r["id"],
            "site_url":   r["site_url"],
            "job_id":     r["job_id"],
            "analysis":   r["analysis"],
            "actions":    json.loads(r["actions"]) if r["actions"] else [],
            "metrics":    json.loads(r["metrics"]) if r["metrics"] else {},
            "created_at": r["created_at"],
        }
        for r in rows
    ]


@app.get("/api/history/{history_id}")
def get_history_entry(history_id: str):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM seo_history WHERE id = :id"), {"id": history_id}
        ).mappings().fetchone()
    if not row:
        raise HTTPException(404, detail="History entry not found.")
    return {
        "id":         row["id"],
        "site_url":   row["site_url"],
        "job_id":     row["job_id"],
        "analysis":   row["analysis"],
        "actions":    json.loads(row["actions"]) if row["actions"] else [],
        "metrics":    json.loads(row["metrics"]) if row["metrics"] else {},
        "created_at": row["created_at"],
    }


# ── Site documentation endpoints ────────────────────────────────────────────

@app.get("/api/documentation")
def get_documentation(site_url: str = "", limit: int = 20):
    """Return generated run-documentation for a site (or all sites)."""
    with engine.connect() as conn:
        if site_url:
            rows = conn.execute(
                text("SELECT id, site_url, job_id, doc_md, created_at "
                     "FROM site_documentation WHERE site_url = :url ORDER BY created_at DESC LIMIT :lim"),
                {"url": site_url, "lim": limit},
            ).mappings().fetchall()
        else:
            rows = conn.execute(
                text("SELECT id, site_url, job_id, doc_md, created_at "
                     "FROM site_documentation ORDER BY created_at DESC LIMIT :lim"),
                {"lim": limit},
            ).mappings().fetchall()
    return [{"id": r["id"], "site_url": r["site_url"], "job_id": r["job_id"],
             "doc_md": r["doc_md"], "created_at": r["created_at"]} for r in rows]


# ── Managed sites (scheduler) endpoints ──────────────────────────────────────

class ManagedSiteRequest(BaseModel):
    url:                     str
    interval_hours:          int  = 24
    max_pages:               int  = 200
    calculate_ipr:           bool = True
    wp_url:                  str | None = None
    wp_user:                 str | None = None
    wp_app_password:         str | None = None
    gsc_property_url:        str | None = None
    gsc_service_account_json: str | None = None


@app.get("/api/schedule")
def list_managed_sites():
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT * FROM managed_sites")).mappings().fetchall()
    return [dict(r) for r in rows]


@app.post("/api/schedule")
def add_managed_site(req: ManagedSiteRequest, background_tasks: BackgroundTasks):
    """Add or update a managed site for periodic automated crawl+analyze+act."""
    now = datetime.now(timezone.utc).isoformat()
    wp_creds = None
    if req.wp_url or req.wp_user:
        wp_creds = {"wp_url": req.wp_url, "wp_user": req.wp_user, "wp_app_password": req.wp_app_password}
    with db_lock:
        with engine.begin() as conn:
            _params = {
                "url": req.url, "ih": req.interval_hours,
                "mp": req.max_pages, "ipr": 1 if req.calculate_ipr else 0,
                "wurl": req.wp_url, "wuser": req.wp_user, "wpw": req.wp_app_password,
                "gsc_prop": req.gsc_property_url, "gsc_sa": req.gsc_service_account_json,
            }
            _cols = "url,interval_hours,max_pages,calculate_ipr,wp_url,wp_user,wp_app_password,gsc_property_url,gsc_service_account_json"
            _vals = ":url,:ih,:mp,:ipr,:wurl,:wuser,:wpw,:gsc_prop,:gsc_sa"
            _set  = ("interval_hours=excluded.interval_hours,max_pages=excluded.max_pages,"
                     "calculate_ipr=excluded.calculate_ipr,wp_url=excluded.wp_url,"
                     "wp_user=excluded.wp_user,wp_app_password=excluded.wp_app_password,"
                     "gsc_property_url=excluded.gsc_property_url,"
                     "gsc_service_account_json=excluded.gsc_service_account_json")
            _set_pg = _set.replace("excluded.", "EXCLUDED.")
            if _IS_SQLITE:
                conn.execute(text(
                    f"INSERT INTO managed_sites ({_cols}) VALUES ({_vals}) "
                    f"ON CONFLICT(url) DO UPDATE SET {_set}"
                ), _params)
            else:
                conn.execute(text(
                    f"INSERT INTO managed_sites ({_cols}) VALUES ({_vals}) "
                    f"ON CONFLICT (url) DO UPDATE SET {_set_pg}"
                ), _params)

    # Re-schedule
    _scheduler.add_job(
        _scheduled_crawl,
        trigger="interval",
        hours=req.interval_hours,
        args=[req.url, req.max_pages, req.calculate_ipr],
        kwargs={"wp_creds": wp_creds,
                "gsc_property": req.gsc_property_url or "",
                "gsc_sa_json":  req.gsc_service_account_json or ""},
        id=f"crawl_{req.url}",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    if not _scheduler.running:
        _scheduler.start()

    return {"status": "scheduled", "url": req.url,
            "interval_hours": req.interval_hours,
            "next_run": "~1 minute"}


@app.delete("/api/schedule/{site_url:path}", status_code=204)
def remove_managed_site(site_url: str):
    with db_lock:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM managed_sites WHERE url = :url"), {"url": site_url})
    try:
        _scheduler.remove_job(f"crawl_{site_url}")
    except Exception:
        pass
    return None


# ── Marketing Agents endpoints ────────────────────────────────────────────────

class AgentRunRequest(BaseModel):
    agent:     str
    input:     dict
    use_dummy: bool = False


def _execute_agent(job_id: str, agent_id: str, input_data: dict, use_dummy: bool):
    """Run a marketing agent in a background thread and persist result."""
    try:
        with db_lock:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE agent_jobs SET status='running' WHERE id=:id"
                ), {"id": job_id})

        cls = marketing_agents.AGENT_REGISTRY.get(agent_id)
        if cls is None:
            raise ValueError(f"Unknown agent: {agent_id}")

        result = cls.run(input_data, use_dummy=use_dummy)
        now    = datetime.now(timezone.utc).isoformat()

        with db_lock:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE agent_jobs SET status='done', result=:r, completed_at=:t WHERE id=:id"
                ), {"r": json.dumps(result, ensure_ascii=False), "t": now, "id": job_id})

    except Exception as e:
        logger.error("[agent %s] Failed: %s", agent_id, e)
        with db_lock:
            with engine.begin() as conn:
                conn.execute(text(
                    "UPDATE agent_jobs SET status='error', error=:e WHERE id=:id"
                ), {"e": str(e), "id": job_id})


@app.get("/api/agents/list")
def agents_list():
    """Return metadata for all available marketing agents."""
    return marketing_agents.list_agents()


@app.post("/api/agents/run")
def agents_run(req: AgentRunRequest, background_tasks: BackgroundTasks):
    """Start a marketing agent job (async)."""
    if req.agent not in marketing_agents.AGENT_REGISTRY:
        raise HTTPException(status_code=400, detail=f"Unknown agent '{req.agent}'")
    job_id = str(uuid.uuid4())
    now    = datetime.now(timezone.utc).isoformat()
    with db_lock:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_jobs (id, agent, status, input_data, created_at) "
                "VALUES (:id, :ag, 'pending', :inp, :now)"
            ), {"id": job_id, "ag": req.agent,
                "inp": json.dumps(req.input, ensure_ascii=False), "now": now})
    background_tasks.add_task(_execute_agent, job_id, req.agent, req.input, req.use_dummy)
    return {"job_id": job_id, "agent": req.agent}


@app.get("/api/agents/jobs/{job_id}")
def agents_job_get(job_id: str):
    """Poll agent job status and result."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM agent_jobs WHERE id = :id"), {"id": job_id}
        ).mappings().fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    r = dict(row)
    if r.get("result"):
        try:
            r["result"] = json.loads(r["result"])
        except Exception:
            pass
    return r


@app.get("/api/agents/jobs")
def agents_jobs_list(limit: int = 20, agent: Optional[str] = None):
    """List recent agent jobs."""
    with engine.connect() as conn:
        if agent:
            rows = conn.execute(
                text("SELECT id, agent, status, created_at, completed_at FROM agent_jobs "
                     "WHERE agent=:ag ORDER BY created_at DESC LIMIT :lim"),
                {"ag": agent, "lim": limit},
            ).mappings().fetchall()
        else:
            rows = conn.execute(
                text("SELECT id, agent, status, created_at, completed_at FROM agent_jobs "
                     "ORDER BY created_at DESC LIMIT :lim"),
                {"lim": limit},
            ).mappings().fetchall()
    return [dict(r) for r in rows]


@app.get("/api/wp/status")
def wp_status():
    """Check WordPress connectivity and authentication."""
    result = wp_agent.debug_auth()
    if result.get("auth_ok"):
        try:
            url_map = wp_agent.build_url_map()
            result["posts_found"] = len(url_map)
        except Exception as e:
            result["posts_error"] = str(e)
    return result
