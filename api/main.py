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
from datetime import datetime, timezone
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, HttpUrl

from crawler_engine import crawl_multiple, compute_ipr
from ahrefs_client import fetch_ref_domains, fetch_organic_keywords
from playwright_analysis import run_playwright_analysis

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
    try:
        with engine.begin() as conn:
            if _IS_SQLITE:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN analysis TEXT"))
            else:
                conn.execute(text("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS analysis TEXT"))
    except Exception:
        pass


def db_update(job_id: str, **kwargs):
    with db_lock:
        sets   = ", ".join(f"{k} = :{k}" for k in kwargs)
        params = {**kwargs, "_jid": job_id}
        with engine.begin() as conn:
            conn.execute(text(f"UPDATE jobs SET {sets} WHERE id = :_jid"), params)


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
              playwright_auth_cookies: str = ""):

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

    # 1) Domain Rating — primary signal, raise if it fails
    dr_resp = await _ahrefs_get(
        "site-explorer/domain-rating",
        {"target": domain},
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
             "select": "referring_domain,domain_rating_source"},
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

def _build_prompt(results: dict) -> str:
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

    # ── PageSpeed note ───────────────────────────────────────────────────────
    lines.append("### PageSpeed / Core Web Vitals: EJ INTEGRERAT ÄN")
    lines.append("  (Google PageSpeed Insights API-integration planeras — LCP, CLS, INP, TTFB kommer)")
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
def analyze_job(job_id: str):
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
    prompt = _build_prompt(results)

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Du är en expert SEO-konsult som ger konkreta, handlingsinriktade råd på svenska."},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=2500,
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
