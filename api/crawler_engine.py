"""
crawler_engine.py — SEO crawl engine.

Primary:  seotracker's async CrawlOrchestrator (httpx + BeautifulSoup + sitemap + robots)
Fallback: basic synchronous requests-based BFS crawler.

crawl_multiple() returns dict[start_url -> domain_result_dict]:
  {
    "domain":  str,
    "summary": {total_pages, pages_200, pages_4xx, missing_titles, ...},
    "pages":   [{"url", "status_code", "title", "h1", "meta_description",
                 "canonical", "noindex", "internal_links_count",
                 "external_links_count", "images_without_alt", "broken_links",
                 "word_count", "crawl_depth"}, ...]
  }
"""

import asyncio
import logging
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, urldefrag

# ── Try to load seotracker orchestrator ────────────────────────────────────
_SEOTRACKER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'seotracker')
if os.path.isdir(_SEOTRACKER_DIR) and _SEOTRACKER_DIR not in sys.path:
    sys.path.insert(0, _SEOTRACKER_DIR)

try:
    from app.crawler.orchestrator import CrawlOrchestrator   # type: ignore
    _HAS_ORCHESTRATOR = True
    logging.getLogger(__name__).info("Using seotracker CrawlOrchestrator engine.")
except Exception as _e:
    _HAS_ORCHESTRATOR = False
    logging.getLogger(__name__).warning("seotracker not available (%s), using basic crawler.", _e)

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "AmazingTools-SEO-Crawler/1.0 (+https://davidvesterlund.com/amazingtools)",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 15
CRAWL_DELAY    = 0.3   # seconds between requests


@dataclass
class PageData:
    url: str
    status_code: Optional[int]       = None
    title: Optional[str]             = None
    h1: Optional[str]                = None
    h1_count: int                    = 0
    meta_description: Optional[str]  = None
    canonical: Optional[str]         = None
    noindex: bool                    = False
    robots_meta: Optional[str]       = None
    internal_links: list             = field(default_factory=list)
    external_links: list             = field(default_factory=list)
    broken_links: list               = field(default_factory=list)
    internal_links_count: int        = 0
    external_links_count: int        = 0
    images_without_alt: int          = 0
    images_total: int                = 0
    word_count: int                  = 0
    crawl_depth: int                 = 0
    content_type: Optional[str]      = None
    error: Optional[str]             = None


@dataclass
class CrawlSummary:
    total_pages: int         = 0
    pages_200: int           = 0
    pages_3xx: int           = 0
    pages_4xx: int           = 0
    pages_5xx: int           = 0
    missing_titles: int      = 0
    duplicate_titles: int    = 0
    missing_h1: int          = 0
    duplicate_h1: int        = 0
    missing_meta_desc: int   = 0
    long_meta_desc: int      = 0
    short_meta_desc: int     = 0
    missing_canonical: int   = 0
    noindex_count: int       = 0
    broken_links: int        = 0
    total_internal_links: int = 0
    total_external_links: int = 0
    images_without_alt: int  = 0
    orphaned_pages: int      = 0


@dataclass
class DomainResult:
    domain: str
    summary: CrawlSummary = field(default_factory=CrawlSummary)
    pages: list            = field(default_factory=list)   # list[PageData]
    robots_txt: Optional[str] = None


def _normalize_url(url: str) -> str:
    """Strip fragment and trailing slash from URL."""
    url, _ = urldefrag(url)
    return url.rstrip('/')


def _same_domain(url: str, base_netloc: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc == base_netloc or parsed.netloc == f"www.{base_netloc}" or f"www.{parsed.netloc}" == base_netloc


def _fetch(url: str, session: requests.Session, check_externals: bool = False) -> tuple[Optional[int], Optional[str], Optional[bytes]]:
    """Return (status_code, content_type, body_bytes) — body only for HTML."""
    try:
        resp = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        ct = resp.headers.get("Content-Type", "")
        if "text/html" not in ct:
            return resp.status_code, ct, None
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        return resp.status_code, resp.headers.get("Content-Type", ""), resp.content
    except requests.exceptions.SSLError:
        return 0, None, None
    except requests.exceptions.ConnectionError:
        return 0, None, None
    except requests.exceptions.Timeout:
        return 0, None, None
    except Exception as e:
        logger.debug(f"Fetch error {url}: {e}")
        return None, None, None


def _fetch_robots(base_url: str, session: requests.Session) -> Optional[str]:
    try:
        r = session.get(f"{base_url}/robots.txt", timeout=10)
        if r.status_code == 200:
            return r.text[:4096]
    except Exception:
        pass
    return None


def _is_blocked_by_robots(url: str, robots_txt: Optional[str]) -> bool:
    """Very simple robots.txt parser — only checks Disallow lines for *."""
    if not robots_txt:
        return False
    path = urlparse(url).path
    in_star = False
    for line in robots_txt.splitlines():
        line = line.strip()
        if line.lower().startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip()
            in_star = agent == "*"
        elif in_star and line.lower().startswith("disallow:"):
            disallowed = line.split(":", 1)[1].strip()
            if disallowed and path.startswith(disallowed):
                return True
    return False


def _parse_page(url: str, body: bytes, base_netloc: str) -> PageData:
    p = PageData(url=url)
    soup = BeautifulSoup(body, "html.parser")

    # Title
    title_tag = soup.find("title")
    p.title = title_tag.get_text(strip=True) if title_tag else None

    # H1
    h1_tags = soup.find_all("h1")
    p.h1_count = len(h1_tags)
    p.h1 = h1_tags[0].get_text(strip=True) if h1_tags else None

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if meta_desc:
        p.meta_description = meta_desc.get("content", "").strip() or None

    # Canonical
    canonical = soup.find("link", rel=lambda r: r and "canonical" in r)
    if canonical:
        p.canonical = canonical.get("href", "").strip() or None

    # Robots meta / noindex
    robots_meta = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if robots_meta:
        content = robots_meta.get("content", "").lower()
        p.robots_meta = content
        p.noindex = "noindex" in content

    # Links
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_url = _normalize_url(urljoin(url, href))
        parsed = urlparse(abs_url)
        if not parsed.scheme.startswith("http"):
            continue
        if _same_domain(abs_url, base_netloc):
            if abs_url not in p.internal_links:
                p.internal_links.append(abs_url)
        else:
            if abs_url not in p.external_links:
                p.external_links.append(abs_url)

    p.internal_links_count = len(p.internal_links)
    p.external_links_count = len(p.external_links)

    # Images without alt
    images = soup.find_all("img")
    p.images_total = len(images)
    p.images_without_alt = sum(1 for img in images if not img.get("alt", "").strip())

    # Word count (rough)
    text = soup.get_text(separator=" ", strip=True)
    p.word_count = len(text.split())

    return p


def _basic_crawl_domain(
    start_url: str,
    max_pages: int = 100,
    check_externals: bool = True,
    respect_robots: bool = True,
    progress_callback=None,
) -> DomainResult:
    """
    Basic synchronous BFS crawl. Returns DomainResult dataclass (fallback).
    progress_callback(pages_done: int) called after each page.
    """
    parsed_start = urlparse(start_url)
    base_netloc   = parsed_start.netloc
    base_url      = f"{parsed_start.scheme}://{base_netloc}"

    result = DomainResult(domain=start_url)

    session = requests.Session()
    session.headers.update(HEADERS)
    session.max_redirects = 5

    # robots.txt
    robots_txt = _fetch_robots(base_url, session) if respect_robots else None
    result.robots_txt = robots_txt

    visited: set[str]  = set()
    queue:   deque     = deque()
    queue.append((_normalize_url(start_url), 0))
    visited.add(_normalize_url(start_url))

    all_internal_urls: set[str] = set()
    linked_from: dict[str, set[str]] = {}  # url -> set of pages linking to it

    pages_crawled = 0

    while queue and pages_crawled < max_pages:
        url, depth = queue.popleft()

        if respect_robots and _is_blocked_by_robots(url, robots_txt):
            logger.debug(f"Blocked by robots.txt: {url}")
            continue

        time.sleep(CRAWL_DELAY)

        status, content_type, body = _fetch(url, session)

        if status is None:
            page = PageData(url=url, error="fetch_failed", crawl_depth=depth)
            result.pages.append(page)
            pages_crawled += 1
            continue

        content_type = content_type or ""

        if "text/html" not in content_type or body is None:
            page = PageData(url=url, status_code=status, content_type=content_type, crawl_depth=depth)
            result.pages.append(page)
            pages_crawled += 1
            if progress_callback:
                progress_callback(pages_crawled)
            continue

        page = _parse_page(url, body, base_netloc)
        page.status_code = status
        page.content_type = content_type
        page.crawl_depth  = depth

        # Enqueue internal links
        for link in page.internal_links:
            all_internal_urls.add(link)
            if link not in linked_from:
                linked_from[link] = set()
            linked_from[link].add(url)
            if link not in visited and pages_crawled + len(queue) < max_pages * 2:
                visited.add(link)
                queue.append((link, depth + 1))

        # Check external / broken links (HEAD only)
        if check_externals:
            for ext_url in page.external_links[:20]:  # cap at 20 per page
                try:
                    r = session.head(ext_url, timeout=8, allow_redirects=True)
                    if r.status_code >= 400:
                        page.broken_links.append({"url": ext_url, "status": r.status_code})
                except Exception:
                    page.broken_links.append({"url": ext_url, "status": 0})

        # Check internal broken links
        for int_url in page.internal_links[:30]:
            if int_url in visited:
                continue

        result.pages.append(page)
        pages_crawled += 1

        if progress_callback:
            progress_callback(pages_crawled)

        logger.debug(f"Crawled [{status}] {url} (depth={depth})")

    # Second pass: detect broken internal links
    crawled_urls = {p.url: p.status_code for p in result.pages}
    for page in result.pages:
        for int_url in page.internal_links:
            if int_url in crawled_urls:
                code = crawled_urls[int_url]
                if code and code >= 400:
                    if not any(b["url"] == int_url for b in page.broken_links):
                        page.broken_links.append({"url": int_url, "status": code})

    # Orphaned pages: crawled but no one links to them (except start_url)
    crawled_set = {p.url for p in result.pages}
    orphaned = crawled_set - all_internal_urls - {_normalize_url(start_url)}

    # Build summary
    s = CrawlSummary()
    title_counts:    dict[str, int] = {}
    h1_counts:       dict[str, int] = {}

    for page in result.pages:
        if page.status_code is None:
            continue
        s.total_pages += 1
        code = page.status_code
        if 200 <= code < 300:    s.pages_200 += 1
        elif 300 <= code < 400:  s.pages_3xx += 1
        elif 400 <= code < 500:  s.pages_4xx += 1
        elif code >= 500:        s.pages_5xx += 1

        if "text/html" in (page.content_type or ""):
            if not page.title:         s.missing_titles  += 1
            else:                       title_counts[page.title] = title_counts.get(page.title, 0) + 1

            if not page.h1:            s.missing_h1      += 1
            else:                       h1_counts[page.h1] = h1_counts.get(page.h1, 0) + 1

            if not page.meta_description:
                s.missing_meta_desc += 1
            elif len(page.meta_description) > 160:
                s.long_meta_desc += 1
            elif len(page.meta_description) < 70:
                s.short_meta_desc += 1

            if not page.canonical:     s.missing_canonical += 1
            if page.noindex:           s.noindex_count   += 1

        s.broken_links         += len(page.broken_links)
        s.total_internal_links += page.internal_links_count
        s.total_external_links += page.external_links_count
        s.images_without_alt   += page.images_without_alt

    s.duplicate_titles = sum(1 for c in title_counts.values() if c > 1)
    s.duplicate_h1     = sum(1 for c in h1_counts.values() if c > 1)
    s.orphaned_pages   = len(orphaned)

    result.summary = s
    return result


# ── Convert DomainResult dataclass → plain dict ────────────────────────────

def _domain_result_to_dict(dr: DomainResult) -> dict:
    from dataclasses import asdict
    return asdict(dr)


# ── Seotracker orchestrator bridge ─────────────────────────────────────────

def _build_summary_from_pages(pages: list[dict]) -> dict:
    title_counts: dict[str, int] = {}
    h1_counts:    dict[str, int] = {}
    s = dict(
        total_pages=0, pages_200=0, pages_3xx=0, pages_4xx=0, pages_5xx=0,
        missing_titles=0, duplicate_titles=0, missing_h1=0, duplicate_h1=0,
        missing_meta_desc=0, long_meta_desc=0, short_meta_desc=0,
        missing_canonical=0, noindex_count=0, broken_links=0,
        total_internal_links=0, total_external_links=0,
        images_without_alt=0, orphaned_pages=0,
    )
    for p in pages:
        code = p.get("status_code") or 0
        if not code:
            continue
        s["total_pages"] += 1
        if 200 <= code < 300:   s["pages_200"] += 1
        elif 300 <= code < 400: s["pages_3xx"] += 1
        elif 400 <= code < 500: s["pages_4xx"] += 1
        elif code >= 500:       s["pages_5xx"] += 1

        ct = p.get("content_type") or ""
        if "html" in ct or not ct:
            t = p.get("title")
            if not t: s["missing_titles"] += 1
            else:     title_counts[t] = title_counts.get(t, 0) + 1

            h = p.get("h1")
            if not h: s["missing_h1"] += 1
            else:     h1_counts[h] = h1_counts.get(h, 0) + 1

            md = p.get("meta_description")
            if not md:             s["missing_meta_desc"] += 1
            elif len(md) > 160:    s["long_meta_desc"]    += 1
            elif len(md) < 70:     s["short_meta_desc"]   += 1

            if not p.get("canonical"): s["missing_canonical"] += 1
            if p.get("noindex"):       s["noindex_count"]     += 1

        s["broken_links"]         += len(p.get("broken_links") or [])
        s["total_internal_links"] += p.get("internal_links_count") or 0
        s["total_external_links"] += p.get("external_links_count") or 0
        s["images_without_alt"]   += p.get("images_without_alt") or 0

    s["duplicate_titles"] = sum(1 for c in title_counts.values() if c > 1)
    s["duplicate_h1"]     = sum(1 for c in h1_counts.values() if c > 1)
    return s


async def _run_orchestrator(start_url: str, max_pages: int,
                             respect_robots: bool, progress_callback,
                             use_playwright: bool = False) -> dict:
    done_count = [0]

    def on_page(_page_record):
        done_count[0] += 1
        if progress_callback:
            progress_callback(done_count[0])

    render_mode = "playwright" if use_playwright else "none"
    orc = CrawlOrchestrator(
        site_id=start_url,
        domain=start_url,
        start_urls=[start_url],
        max_pages=max_pages,
        max_depth=10,
        max_concurrency=5,
        rate_limit_rps=2.0,
        render_mode=render_mode,
        respect_robots=respect_robots,
        on_page_complete=on_page,
    )
    return await orc.run()


def _orchestrator_crawl_domain(
    start_url: str,
    max_pages: int = 100,
    respect_robots: bool = True,
    progress_callback=None,
    use_playwright: bool = False,
) -> dict:
    """Crawl one domain via seotracker's async orchestrator. Returns plain dict."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        raw = loop.run_until_complete(
            _run_orchestrator(start_url, max_pages, respect_robots,
                              progress_callback, use_playwright)
        )
    finally:
        loop.close()

    pages_raw   = raw.get("pages", [])
    links_raw   = raw.get("links", [])
    status_map  = {p.get("url"): p.get("status_code") for p in pages_raw}

    # Build internal link map: source -> [dest, ...]
    internal_by_src: dict[str, list[str]] = {}
    broken_by_source: dict[str, list] = {}
    for link in links_raw:
        if not link.get("is_internal"):
            continue
        src  = link.get("source_url", "")
        dest = link.get("dest_url", "")
        if src and dest:
            internal_by_src.setdefault(src, []).append(dest)
        code = status_map.get(dest, 200) or 200
        if code >= 400:
            broken_by_source.setdefault(src, []).append({"url": dest, "status": code})

    pages = []
    for p in pages_raw:
        url = p.get("url", "")
        ct  = p.get("content_type") or ""
        pages.append({
            "url":                  url,
            "status_code":          p.get("status_code"),
            "title":                p.get("title"),
            "h1":                   p.get("h1_text"),
            "h1_count":             p.get("h1_count", 0),
            "meta_description":     p.get("meta_description"),
            "canonical":            p.get("canonical_url"),
            "noindex":              p.get("is_noindex", False),
            "internal_links":       internal_by_src.get(url, []),
            "internal_links_count": p.get("internal_links_count", 0),
            "external_links_count": p.get("external_links_count", 0),
            "images_without_alt":   p.get("img_missing_alt", 0),
            "images_total":         p.get("img_count", 0),
            "word_count":           p.get("word_count", 0),
            "crawl_depth":          p.get("depth", 0),
            "content_type":         ct,
            "broken_links":         broken_by_source.get(url, []),
        })

    summary = _build_summary_from_pages(pages)

    # Orphaned: crawled pages with no inbound internal link
    all_dest = {lk.get("dest_url") for lk in links_raw if lk.get("is_internal")}
    crawled  = {p["url"] for p in pages}
    summary["orphaned_pages"] = max(0, len(crawled - all_dest) - 1)

    return {"domain": start_url, "summary": summary, "pages": pages}


# ── Internal PageRank (IPR) ─────────────────────────────────────────────────

def compute_ipr(domain_result: dict) -> dict:
    """
    Add 'ipr', 'ipr_inbound', 'ipr_outbound' to every page.
    IPR = inbound_internal_links / max(1, outbound_internal_links)
    Only counts links between pages that were actually crawled.
    Modifies domain_result in place and returns it.
    """
    pages   = domain_result.get("pages", [])
    url_set = {p.get("url", "") for p in pages}

    inbound:  dict[str, int] = {p.get("url", ""): 0 for p in pages}
    outbound: dict[str, int] = {}

    for page in pages:
        url   = page.get("url", "")
        links = page.get("internal_links") or []
        # Resolve dicts (basic BFS stores str, orchestrator stores str too)
        resolved = []
        for l in links:
            if isinstance(l, dict):
                l = l.get("url") or l.get("href", "")
            if isinstance(l, str) and l in url_set and l != url:
                resolved.append(l)
        # Deduplicate (one link = one vote regardless of how many times linked)
        unique = list(dict.fromkeys(resolved))
        outbound[url] = len(unique)
        for target in unique:
            inbound[target] = inbound.get(target, 0) + 1

    for page in pages:
        url = page.get("url", "")
        ib  = inbound.get(url, 0)
        ob  = outbound.get(url, 0)
        page["ipr"]          = round(ib / ob, 4) if ob > 0 else float(ib)
        page["ipr_inbound"]  = ib
        page["ipr_outbound"] = ob

    return domain_result


# ── Public API ──────────────────────────────────────────────────────────────

def crawl_domain(
    start_url: str,
    max_pages: int = 100,
    check_externals: bool = True,
    respect_robots: bool = True,
    progress_callback=None,
    use_playwright: bool = False,
    calculate_ipr: bool = False,
) -> dict:
    """Crawl a single domain. Returns a plain dict (domain, summary, pages)."""
    if _HAS_ORCHESTRATOR:
        try:
            result = _orchestrator_crawl_domain(
                start_url, max_pages, respect_robots, progress_callback,
                use_playwright=use_playwright,
            )
            if calculate_ipr:
                compute_ipr(result)
            return result
        except Exception as e:
            logger.error("Orchestrator failed for %s: %s — falling back", start_url, e)

    # Fallback: basic sync BFS crawler
    dr = _basic_crawl_domain(
        start_url, max_pages, check_externals, respect_robots,
        lambda n: progress_callback(n) if progress_callback else None,
    )
    result = _domain_result_to_dict(dr)
    if calculate_ipr:
        compute_ipr(result)
    return result


def crawl_multiple(
    client_url: str,
    competitor_urls: list[str],
    max_pages: int = 100,
    check_externals: bool = True,
    respect_robots: bool = True,
    progress_callback=None,
    use_playwright: bool = False,
    calculate_ipr: bool = False,
) -> dict[str, dict]:
    """
    Crawl client + all competitors. Returns dict[url -> domain_result_dict].
    """
    results: dict[str, dict] = {}
    all_urls = [client_url] + competitor_urls
    total    = len(all_urls)

    for i, url in enumerate(all_urls):
        logger.info("Crawling domain %d/%d: %s", i + 1, total, url)
        try:
            def cb(n, _url=url, _i=i):
                if progress_callback:
                    progress_callback(_url, n, _i, total)

            results[url] = crawl_domain(
                url,
                max_pages=max_pages,
                check_externals=check_externals,
                respect_robots=respect_robots,
                progress_callback=cb,
                use_playwright=use_playwright,
                calculate_ipr=calculate_ipr,
            )
        except Exception as e:
            logger.error("Failed to crawl %s: %s", url, e)
            results[url] = {"domain": url, "summary": {}, "pages": []}

    return results
