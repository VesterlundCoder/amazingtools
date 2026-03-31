"""
Sitemap discovery and parsing.

Responsibilities:
  - Discover sitemaps via robots.txt directives, common paths, WP paths
  - Parse sitemap XML (urlset) and sitemap index files
  - Handle gzip-compressed sitemaps
  - Extract URLs with lastmod, changefreq, priority
  - Seed the crawl frontier from sitemap URLs
"""

from __future__ import annotations

import gzip
import logging
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Optional
from urllib.parse import urlparse

import httpx
from defusedxml import ElementTree as ET

logger = logging.getLogger(__name__)

# Sitemap XML namespace
NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Common sitemap locations to probe
COMMON_SITEMAP_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
    "/sitemap.xml.gz",
]


@dataclass
class SitemapURL:
    """A single URL entry from a sitemap."""
    loc: str
    lastmod: Optional[str] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None


@dataclass
class SitemapResult:
    """Result of parsing one sitemap file."""
    url: str
    status_code: Optional[int] = None
    is_index: bool = False
    child_sitemaps: list[str] = field(default_factory=list)
    urls: list[SitemapURL] = field(default_factory=list)
    error: Optional[str] = None


class SitemapDiscovery:
    """
    Discover and parse sitemaps for a site.

    Usage:
        discovery = SitemapDiscovery(http_client)
        urls = await discovery.discover_and_parse(
            domain="https://example.com",
            robots_sitemap_urls=["https://example.com/sitemap.xml"],
        )
    """

    def __init__(self, client: httpx.AsyncClient, max_sitemaps: int = 50):
        self._client = client
        self._max_sitemaps = max_sitemaps
        self._visited: set[str] = set()

    async def discover_and_parse(
        self,
        domain: str,
        robots_sitemap_urls: list[str] | None = None,
    ) -> list[SitemapURL]:
        """
        Full discovery flow:
        1. Use robots.txt Sitemap: directives (highest priority)
        2. Probe common sitemap paths
        3. Recursively expand sitemap indexes
        Returns deduplicated list of SitemapURL entries.
        """
        self._visited.clear()
        all_urls: dict[str, SitemapURL] = {}  # keyed by loc for dedup

        # 1. Robots.txt sitemap directives
        sitemap_queue: list[str] = list(robots_sitemap_urls or [])

        # 2. Common paths (only if no robots directives found)
        if not sitemap_queue:
            parsed = urlparse(domain)
            base = f"{parsed.scheme}://{parsed.netloc}"
            for path in COMMON_SITEMAP_PATHS:
                sitemap_queue.append(base + path)

        # 3. Process queue (BFS, expanding indexes)
        while sitemap_queue and len(self._visited) < self._max_sitemaps:
            sitemap_url = sitemap_queue.pop(0)
            if sitemap_url in self._visited:
                continue
            self._visited.add(sitemap_url)

            result = await self._fetch_and_parse(sitemap_url)
            if result.error:
                logger.debug("Sitemap %s: %s", sitemap_url, result.error)
                continue

            if result.is_index:
                logger.info("Sitemap index %s → %d child sitemaps", sitemap_url, len(result.child_sitemaps))
                sitemap_queue.extend(result.child_sitemaps)
            else:
                logger.info("Sitemap %s → %d URLs", sitemap_url, len(result.urls))
                for u in result.urls:
                    all_urls[u.loc] = u

        logger.info("Sitemap discovery complete: %d unique URLs from %d sitemaps", len(all_urls), len(self._visited))
        return list(all_urls.values())

    async def _fetch_and_parse(self, url: str) -> SitemapResult:
        """Fetch a single sitemap URL and parse it."""
        result = SitemapResult(url=url)
        try:
            resp = await self._client.get(url, follow_redirects=True, timeout=30.0)
            result.status_code = resp.status_code

            if resp.status_code != 200:
                result.error = f"HTTP {resp.status_code}"
                return result

            content = resp.content

            # Handle gzip
            if url.endswith(".gz") or resp.headers.get("content-encoding") == "gzip":
                try:
                    content = gzip.decompress(content)
                except Exception:
                    pass  # might not actually be gzipped

            # Parse XML
            try:
                root = ET.fromstring(content)
            except ET.ParseError as e:
                result.error = f"XML parse error: {e}"
                return result

            tag = root.tag.lower()

            # Sitemap index
            if "sitemapindex" in tag:
                result.is_index = True
                for sitemap_el in root.findall("sm:sitemap", NS):
                    loc_el = sitemap_el.find("sm:loc", NS)
                    if loc_el is not None and loc_el.text:
                        result.child_sitemaps.append(loc_el.text.strip())
                # Also try without namespace (some sitemaps are non-standard)
                if not result.child_sitemaps:
                    for sitemap_el in root.findall("sitemap"):
                        loc_el = sitemap_el.find("loc")
                        if loc_el is not None and loc_el.text:
                            result.child_sitemaps.append(loc_el.text.strip())

            # URL set
            elif "urlset" in tag:
                for url_el in root.findall("sm:url", NS):
                    loc_el = url_el.find("sm:loc", NS)
                    if loc_el is None or not loc_el.text:
                        continue
                    entry = SitemapURL(loc=loc_el.text.strip())
                    lastmod_el = url_el.find("sm:lastmod", NS)
                    if lastmod_el is not None and lastmod_el.text:
                        entry.lastmod = lastmod_el.text.strip()
                    changefreq_el = url_el.find("sm:changefreq", NS)
                    if changefreq_el is not None and changefreq_el.text:
                        entry.changefreq = changefreq_el.text.strip()
                    priority_el = url_el.find("sm:priority", NS)
                    if priority_el is not None and priority_el.text:
                        try:
                            entry.priority = float(priority_el.text.strip())
                        except ValueError:
                            pass
                    result.urls.append(entry)
                # Try without namespace
                if not result.urls:
                    for url_el in root.findall("url"):
                        loc_el = url_el.find("loc")
                        if loc_el is None or not loc_el.text:
                            continue
                        entry = SitemapURL(loc=loc_el.text.strip())
                        lastmod_el = url_el.find("lastmod")
                        if lastmod_el is not None and lastmod_el.text:
                            entry.lastmod = lastmod_el.text.strip()
                        result.urls.append(entry)
            else:
                result.error = f"Unknown root tag: {root.tag}"

        except httpx.HTTPError as e:
            result.error = f"Fetch error: {e}"
        except Exception as e:
            result.error = f"Unexpected error: {e}"

        return result
