# SEO Crawler — Specification

## Scale
- ~200 sites × up to 10,000 pages/site × monthly = ~2,000,000 URLs/month
- Goal: detect & prioritize technical + on-page SEO issues, store historical runs, track progress
- JS rendering: required as optional/targeted capability

## Architecture
- **Control Plane**: Tenant/Site Config, Scheduler, Run Orchestrator, API + Dashboard, Notifications
- **Data Plane**: HTTP Crawl Workers, Playwright Render Pool, Audit/Rules Engine, Storage (Postgres), Queues (Redis)

## Deliverables
1. Multi-tenant data model (Postgres) + API
2. Robots.txt parser (RFC 9309) + sitemap discovery + seeding
3. Frontier queue + URL normalization + loop protection
4. HTTP fetcher + redirect chain logging + status policy
5. JS render pool (Playwright) + raw-vs-rendered diff
6. Audit rules engine (technical SEO + on-page)
7. Reporting UI + exports (CSV/XLSX/JSON)

## Tech Stack
- Python 3.11+ (async)
- FastAPI (API layer)
- PostgreSQL (data store)
- Redis (queues/frontier)
- Playwright (JS rendering)
- SQLAlchemy + Alembic (ORM + migrations)
- aiohttp/httpx (async HTTP fetching)
