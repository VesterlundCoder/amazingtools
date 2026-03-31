# Amazing Tools

Internal tooling platform at **davidvesterlund.com/amazingtools**.

Login: `amazing` / `toTO33hhGG669bb`

---

## Structure

```
amazingtools/
  frontend/          — Static HTML pages (upload to davidvesterlund.com/amazingtools/)
    login.html
    dashboard.html
    seo-crawler.html
    results.html
  api/               — FastAPI backend (deploy to Railway)
    main.py
    crawler_engine.py
    requirements.txt
    Procfile
    railway.toml
```

---

## Deployment

### 1. Frontend (cPanel / static host)

Upload the contents of `frontend/` to `public_html/amazingtools/` on your host.
Files are fully self-contained (no build step).

**After deploying the API, update `API_BASE` in each HTML file:**
```js
const API_BASE = 'https://YOUR-RAILWAY-APP.up.railway.app';
```

### 2. Backend (Railway)

```bash
# From the api/ directory
railway init          # create new project "seo-crawler-api"
railway up            # deploy
```

Or connect the GitHub repo in Railway dashboard → select `api/` as root directory.

Set environment variables in Railway if needed:
- `DB_PATH` — SQLite file path (default: `jobs.db`)

API will be live at `https://seo-crawler-api.up.railway.app`

---

## Tools

| Tool | Status | Description |
|------|--------|-------------|
| **SEO Crawler** | ✅ Active | Crawl client + up to 5 competitors. Technical SEO metrics. |
| **QueryMatch** | 🔜 Coming soon | AI keyword & content matching. |

---

## SEO Crawler — What it measures

- HTTP status codes (2xx / 3xx / 4xx / 5xx)
- Title tags: missing, duplicate, length
- H1 tags: missing, duplicate, count
- Meta descriptions: missing, too short (<70), too long (>160)
- Canonical tags: presence
- Noindex directives
- Internal link counts
- External link counts
- Broken links (internal + external)
- Images without alt text
- Orphaned pages
- Crawl depth
- Word count per page

Results available as in-browser dashboard or CSV export.

---

## Adding the VesterlundCoder/seo-crawler engine

Once the repo is accessible, swap `crawler_engine.py`:

1. Install the crawler package in `requirements.txt`
2. Replace the `crawl_domain()` / `crawl_multiple()` functions in `crawler_engine.py`
   with calls to the external engine — keeping the same return interface
   (`DomainResult`, `CrawlSummary`, `PageData` dataclasses).
3. No changes to `main.py` or frontend needed.
