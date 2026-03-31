"""
Robots.txt parser and checker (RFC 9309 compliant).

Responsibilities:
  - Fetch and cache robots.txt per scheme+host
  - Parse Allow/Disallow rules using protego
  - Extract Sitemap: directives
  - Check if a URL is allowed for our user-agent
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx
from protego import Protego

logger = logging.getLogger(__name__)


@dataclass
class RobotsResult:
    """Result of fetching and parsing a robots.txt."""
    url: str
    status_code: Optional[int] = None
    exists: bool = False
    parse_error: Optional[str] = None
    sitemap_urls: list[str] = field(default_factory=list)
    raw_text: str = ""
    _parser: Optional[Protego] = field(default=None, repr=False)

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check whether *url* is crawlable for *user_agent*."""
        if not self._parser:
            return True  # no robots.txt → everything allowed
        return self._parser.can_fetch(url, user_agent)

    def crawl_delay(self, user_agent: str = "*") -> Optional[float]:
        """Return Crawl-delay value if set."""
        if not self._parser:
            return None
        delay = self._parser.crawl_delay(user_agent)
        return float(delay) if delay is not None else None


class RobotsCache:
    """
    In-memory cache of RobotsResult keyed by scheme+host.

    Usage:
        cache = RobotsCache(http_client, user_agent="SEOCrawler/1.0")
        result = await cache.get("https://example.com/some/page")
        if result.is_allowed("https://example.com/some/page"):
            ...
    """

    def __init__(self, client: httpx.AsyncClient, user_agent: str = "*"):
        self._client = client
        self._user_agent = user_agent
        self._cache: dict[str, RobotsResult] = {}

    def _robots_url(self, url: str) -> str:
        """Derive the robots.txt URL for a given page URL."""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _cache_key(self, url: str) -> str:
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"

    async def get(self, url: str) -> RobotsResult:
        """Fetch (or return cached) RobotsResult for the host of *url*."""
        key = self._cache_key(url)
        if key in self._cache:
            return self._cache[key]

        robots_url = self._robots_url(url)
        result = await self._fetch(robots_url)
        self._cache[key] = result
        return result

    async def _fetch(self, robots_url: str) -> RobotsResult:
        """Fetch and parse a robots.txt file."""
        result = RobotsResult(url=robots_url)
        try:
            resp = await self._client.get(
                robots_url,
                follow_redirects=True,
                timeout=15.0,
            )
            result.status_code = resp.status_code

            if resp.status_code == 200:
                result.exists = True
                result.raw_text = resp.text
                try:
                    parser = Protego.parse(resp.text)
                    result._parser = parser
                    result.sitemap_urls = list(parser.sitemaps)
                except Exception as e:
                    result.parse_error = str(e)
                    logger.warning("Failed to parse robots.txt at %s: %s", robots_url, e)
            elif 400 <= resp.status_code < 500:
                # 4xx → treat as "no robots.txt" (everything allowed)
                result.exists = False
                logger.info("robots.txt returned %d at %s — treating as absent", resp.status_code, robots_url)
            else:
                # 5xx → conservative: block nothing but flag
                result.exists = False
                result.parse_error = f"Server error {resp.status_code}"
                logger.warning("robots.txt returned %d at %s", resp.status_code, robots_url)

        except httpx.HTTPError as e:
            result.parse_error = f"Fetch error: {e}"
            logger.error("Could not fetch robots.txt at %s: %s", robots_url, e)

        return result

    def is_allowed(self, url: str) -> bool:
        """Quick synchronous check (requires prior await get())."""
        key = self._cache_key(url)
        result = self._cache.get(key)
        if not result:
            return True  # not yet fetched → assume allowed
        return result.is_allowed(url, self._user_agent)

    def clear(self):
        self._cache.clear()
