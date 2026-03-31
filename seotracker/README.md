# SEO Crawler — Multi-tenant Technical Audit Engine

A scalable, multi-tenant SEO crawler and technical audit engine designed to crawl ~200 sites × 10,000 pages/site monthly.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Control Plane                     │
│  FastAPI API · Tenant Config · Scheduler · UI     │
└────────────┬────────────────────────┬────────────┘
             │                        │
┌────────────▼───────┐  ┌────────────▼───────────┐
│   HTTP Workers     │  │   Render Workers        │
│   (httpx async)    │  │   (Playwright pool)     │
└────────────┬───────┘  └────────────┬───────────┘
             │                        │
┌────────────▼────────────────────────▼───────────┐
│            Audit Rules Engine                     │
│  robots · redirects · canonical · on-page · JS    │
└────────────┬────────────────────────────────────┘
             │
┌────────────▼────────────────────────────────────┐
│            Storage                                │
│  Postgres (data) · Redis (queues) · S3 (snapshots)│
└─────────────────────────────────────────────────┘
```

## Quick Start (CLI mode)

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Run a crawl
python -m app.crawler.runner --domain example.com --max-pages 500 --concurrency 3

# Results saved to ./crawl_output/example_com_YYYYMMDD_HHMMSS/
```

## Quick Start (API mode)

```bash
# Set up Postgres + Redis (docker-compose or local)
cp .env.example .env
# Edit .env with your database credentials

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --host 0.0.0.0 --port 8000

# API docs at http://localhost:8000/docs
```

## Docker Compose (Full Stack)

```bash
# Start everything: Postgres + Redis + API + Dashboard
docker compose up --build

# API at http://localhost:8000 (docs at /docs)
# Dashboard at http://localhost:5174
```

## Project Structure

```
seo-crawler/
├── app/
│   ├── main.py              # FastAPI entry + lifespan + scheduler
│   ├── config.py             # Settings from .env
│   ├── scheduler.py          # Background periodic crawl scheduler
│   ├── api/
│   │   ├── routes.py         # REST API endpoints + exports
│   │   └── schemas.py        # Pydantic request/response models
│   ├── db/
│   │   ├── session.py        # SQLAlchemy async engine
│   │   ├── models.py         # All database tables
│   │   └── persistence.py    # Crawl result → Postgres persistence
│   ├── middleware/
│   │   └── quota.py          # Multi-tenant rate & budget enforcement
│   ├── crawler/
│   │   ├── robots.py         # robots.txt parser (RFC 9309)
│   │   ├── sitemap.py        # Sitemap discovery + parsing
│   │   ├── url_normalizer.py # URL normalization + param policies
│   │   ├── frontier.py       # Priority crawl queue + dedup
│   │   ├── fetcher.py        # HTTP fetch + redirect chains + backoff
│   │   ├── extractor.py      # HTML → SEO data extraction
│   │   ├── renderer.py       # Playwright JS render pool
│   │   ├── orchestrator.py   # Full crawl pipeline coordinator
│   │   ├── runner.py         # CLI runner (standalone)
│   │   └── tasks.py          # Background crawl task management
│   ├── audit/
│   │   └── rules.py          # All audit rules (14 categories)
│   └── export/
│       └── excel_report.py   # 7-sheet XLSX report generator
├── dashboard/                 # React + Vite + TailwindCSS + Recharts
│   └── src/
│       ├── App.jsx           # Main app (file upload + API modes)
│       ├── hooks/useApi.js   # API client hook
│       └── components/       # Charts, tables, cards
├── tests/                     # 89 unit tests
├── alembic/                   # Database migrations
├── Dockerfile                 # API service image
├── docker-compose.yml         # Full stack orchestration
├── requirements.txt
├── .env.example
├── SPEC.md                   # Full specification
└── PROGRESS.md               # Build progress tracker
```

## Modules

### Crawler Pipeline
1. **robots.py** — RFC 9309 robots.txt parsing, caching, Sitemap: extraction
2. **sitemap.py** — Discovery via robots directives, common paths, WP `/wp-sitemap.xml`; sitemap index expansion; gzip support
3. **url_normalizer.py** — Scheme/host/path normalization, tracking param stripping, param allow/deny lists, internal/external classification
4. **frontier.py** — Priority queue (sitemap > seed > low depth > deep), dedup via normalized keys, max_pages/max_depth caps
5. **fetcher.py** — Async HTTP with manual redirect following (captures full chain), per-host rate limiting, exponential backoff on 429/5xx
6. **extractor.py** — Title, meta, canonical, hreflang, headings, links (with nav/footer/content context), images, JSON-LD, content hash
7. **renderer.py** — Pooled Playwright (desktop + mobile profiles), targeted rendering heuristic, raw-vs-rendered parity diff, console error capture
8. **orchestrator.py** — Ties it all together: robots → sitemap → seed → async workers → extract → render → store

### Audit Rules (14 categories)
1. Crawlability & Discovery (robots.txt, sitemaps)
2. Status Codes (4xx, 5xx, soft 404)
3. Redirects (chains, loops, mixed types)
4. Canonicalization (missing, multiple, mismatch)
5. Indexing Policy (noindex conflicts, robots+noindex)
6. On-Page (titles, descriptions, headings, thin content)
7. Links (broken internal, orphans, click depth)
8. Images (missing alt, broken lazy-load)
9. Structured Data (JSON-LD validation)
10. JS Parity (raw vs rendered content/links)
11. Performance (TTFB, page size)
12. Hreflang (self-ref, reciprocity, canonical conflict)
13. Duplicate Content (hash, title+H1 fingerprint, param dupes)
14. Mobile Parity (desktop vs mobile content & link sampling)

### API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/tenants` | Create tenant |
| GET | `/api/v1/tenants` | List tenants |
| GET | `/api/v1/tenants/{id}/quota` | Quota usage for tenant |
| POST | `/api/v1/tenants/{id}/sites` | Create site |
| GET | `/api/v1/tenants/{id}/sites` | List sites |
| PATCH | `/api/v1/sites/{id}/policy` | Update crawl policy |
| POST | `/api/v1/sites/{id}/runs` | Trigger crawl run (background) |
| GET | `/api/v1/sites/{id}/runs` | List runs |
| GET | `/api/v1/sites/{id}/runs/latest` | Latest run report |
| GET | `/api/v1/sites/{id}/trends` | Trend data (3/6/12 months) |
| GET | `/api/v1/runs/{id}/issues` | List issues (filterable) |
| POST | `/api/v1/runs/{id}/cancel` | Cancel active crawl |
| GET | `/api/v1/runs/active` | List active run IDs |
| GET | `/api/v1/runs/{id}/export/json` | Download full run as JSON |
| GET | `/api/v1/runs/{id}/export/csv` | Download pages/issues/links as CSV |
| GET | `/api/v1/runs/{id}/export/xlsx` | Download multi-sheet Excel report |

## Output Files (CLI mode)
- `pages.json` — All crawled page records
- `links.json` — Full link graph
- `issues.json` — Audit findings with severity + fix guidance
- `summary.json` — Run statistics and issue counts
- `seo_report.xlsx` — Multi-sheet Excel workbook (7 sheets)

## Testing

```bash
# Run all 89 tests
python -m pytest tests/ -v

# Run specific test module
python -m pytest tests/test_audit_rules.py -v
```

## Multi-tenant Quotas

The quota middleware enforces per-tenant limits (set via `X-Tenant-ID` header):
- **Concurrent runs**: max 2 active crawls
- **Monthly page budget**: 100,000 pages/month
- **API rate limit**: 120 requests/minute

## Dashboard

The React dashboard supports two data modes:
1. **File upload** — Drag & drop JSON output files from CLI crawls
2. **API connection** — Connect to a running API instance by Site ID

Features: issue severity filtering, status code distribution, depth analysis, content quality metrics, XLSX export download.

## Environment Variables

See `.env.example` for all configurable settings.
