"""
crawler_engine.py — SEO crawl engine.

Crawls a domain up to max_pages deep (BFS), extracts technical SEO metrics
per page, and returns a structured CrawlResult.

Replaces this with the VesterlundCoder/seo-crawler repo engine once available.
"""

import re
import time
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse, urldefrag

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


def crawl_domain(
    start_url: str,
    max_pages: int = 100,
    check_externals: bool = True,
    respect_robots: bool = True,
    progress_callback=None,
) -> DomainResult:
    """
    BFS crawl of a single domain. Returns DomainResult.
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


def crawl_multiple(
    client_url: str,
    competitor_urls: list[str],
    max_pages: int = 100,
    check_externals: bool = True,
    respect_robots: bool = True,
    progress_callback=None,
) -> dict[str, DomainResult]:
    """
    Crawl client + all competitors. Returns dict keyed by URL.
    """
    results = {}
    all_urls = [client_url] + competitor_urls
    total   = len(all_urls)

    for i, url in enumerate(all_urls):
        logger.info(f"Crawling domain {i+1}/{total}: {url}")
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
            )
        except Exception as e:
            logger.error(f"Failed to crawl {url}: {e}")
            results[url] = DomainResult(domain=url)

    return results
