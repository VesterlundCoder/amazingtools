"""
HTTP fetcher with redirect chain logging, backoff, and status policy.

Responsibilities:
  - Fetch URLs with configurable timeouts and retries
  - Log full redirect chains (each hop: url + status_code)
  - Detect redirect loops and long chains
  - Handle gzip/br/deflate transparently
  - Rate limiting per host (via semaphore + delay)
  - Backoff on 429/503/5xx with jitter
  - Record TTFB, download time, response size
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MAX_REDIRECT_HOPS = 10
MAX_RETRIES = 3
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


@dataclass
class RedirectHop:
    """A single hop in a redirect chain."""
    url: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class FetchResult:
    """Result of fetching a single URL."""
    url: str                                    # requested URL
    final_url: Optional[str] = None             # after redirects
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    charset: Optional[str] = None
    response_bytes: int = 0
    ttfb_ms: Optional[float] = None
    download_time_ms: Optional[float] = None

    # Content
    html: str = ""
    raw_bytes: bytes = b""

    # Redirect chain
    redirect_chain: list[RedirectHop] = field(default_factory=list)
    is_redirect_loop: bool = False
    redirect_hops: int = 0

    # Headers
    headers: dict[str, str] = field(default_factory=dict)
    cache_headers: dict[str, str] = field(default_factory=dict)
    x_robots_tag: Optional[str] = None
    hreflang_header: list[str] = field(default_factory=list)

    # Error
    error: Optional[str] = None
    retries: int = 0


class HostRateLimiter:
    """Per-host rate limiter using token bucket approach."""

    def __init__(self, rps: float = 2.0, burst: int = 5):
        self._rps = rps
        self._burst = burst
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._last_request: dict[str, float] = {}
        self._min_interval = 1.0 / rps if rps > 0 else 0

    def _get_host(self, url: str) -> str:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower()

    async def acquire(self, url: str):
        """Wait until it's safe to send a request to this host."""
        host = self._get_host(url)

        # Create semaphore for host if needed
        if host not in self._semaphores:
            self._semaphores[host] = asyncio.Semaphore(self._burst)

        await self._semaphores[host].acquire()

        # Enforce minimum interval between requests to same host
        now = time.monotonic()
        last = self._last_request.get(host, 0)
        wait = self._min_interval - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)

        self._last_request[host] = time.monotonic()

    def release(self, url: str):
        host = self._get_host(url)
        sem = self._semaphores.get(host)
        if sem:
            sem.release()


class HTTPFetcher:
    """
    Async HTTP fetcher with redirect chain logging and rate limiting.

    Usage:
        async with httpx.AsyncClient() as client:
            fetcher = HTTPFetcher(client, user_agent="SEOCrawler/1.0", rps=2.0)
            result = await fetcher.fetch("https://example.com/page")
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        user_agent: str = "SEOCrawler/1.0",
        rps: float = 2.0,
        max_retries: int = MAX_RETRIES,
        timeout: float = 30.0,
    ):
        self._client = client
        self._user_agent = user_agent
        self._rate_limiter = HostRateLimiter(rps=rps)
        self._max_retries = max_retries
        self._timeout = timeout

    async def fetch(self, url: str) -> FetchResult:
        """
        Fetch a URL, following redirects manually to capture the full chain.
        """
        result = FetchResult(url=url)
        current_url = url
        seen_urls: set[str] = set()
        retries = 0

        while True:
            # Loop detection
            if current_url in seen_urls:
                result.is_redirect_loop = True
                result.error = "Redirect loop detected"
                logger.warning("Redirect loop at %s", current_url)
                break
            seen_urls.add(current_url)

            # Max hops
            if len(result.redirect_chain) >= MAX_REDIRECT_HOPS:
                result.error = f"Exceeded {MAX_REDIRECT_HOPS} redirect hops"
                break

            # Rate limit
            await self._rate_limiter.acquire(current_url)
            try:
                fetch_result = await self._fetch_single(current_url)
            finally:
                self._rate_limiter.release(current_url)

            if fetch_result.error and fetch_result.status_code in RETRY_STATUS_CODES:
                retries += 1
                if retries <= self._max_retries:
                    # Exponential backoff with jitter
                    delay = (2 ** retries) + random.uniform(0, 1)
                    logger.info("Retry %d/%d for %s (status %s), waiting %.1fs",
                                retries, self._max_retries, current_url,
                                fetch_result.status_code, delay)
                    await asyncio.sleep(delay)
                    seen_urls.discard(current_url)  # allow retry
                    continue
                else:
                    result.error = f"Max retries exceeded (last status: {fetch_result.status_code})"
                    result.status_code = fetch_result.status_code
                    result.retries = retries
                    break

            # Record the hop if it's a redirect
            status = fetch_result.status_code or 0
            if 300 <= status < 400 and fetch_result.headers.get("location"):
                result.redirect_chain.append(RedirectHop(
                    url=current_url,
                    status_code=status,
                    headers=dict(fetch_result.headers),
                ))
                # Resolve relative redirect
                from urllib.parse import urljoin
                next_url = urljoin(current_url, fetch_result.headers["location"])
                current_url = next_url
                continue

            # Final response (non-redirect)
            result.final_url = current_url
            result.status_code = fetch_result.status_code
            result.content_type = fetch_result.content_type
            result.charset = fetch_result.charset
            result.response_bytes = fetch_result.response_bytes
            result.ttfb_ms = fetch_result.ttfb_ms
            result.download_time_ms = fetch_result.download_time_ms
            result.html = fetch_result.html
            result.raw_bytes = fetch_result.raw_bytes
            result.headers = fetch_result.headers
            result.error = fetch_result.error
            result.retries = retries

            # Extract SEO-relevant headers
            result.x_robots_tag = fetch_result.headers.get("x-robots-tag")
            result.cache_headers = {
                k: v for k, v in fetch_result.headers.items()
                if k.lower() in ("cache-control", "expires", "etag", "last-modified", "age")
            }
            # Hreflang from HTTP headers (Link: <url>; rel="alternate"; hreflang="xx")
            link_headers = [v for k, v in fetch_result.headers.items() if k.lower() == "link"]
            result.hreflang_header = link_headers

            result.redirect_hops = len(result.redirect_chain)
            break

        return result

    async def _fetch_single(self, url: str) -> FetchResult:
        """Perform a single HTTP request (no redirect following)."""
        result = FetchResult(url=url)
        try:
            t_start = time.monotonic()
            resp = await self._client.request(
                "GET",
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                follow_redirects=False,
                timeout=self._timeout,
            )
            t_headers = time.monotonic()

            result.status_code = resp.status_code
            result.headers = dict(resp.headers)
            result.ttfb_ms = (t_headers - t_start) * 1000

            # Content type
            ct = resp.headers.get("content-type", "")
            result.content_type = ct.split(";")[0].strip() if ct else None
            if "charset=" in ct.lower():
                result.charset = ct.split("charset=")[-1].strip().strip('"').strip("'")

            # Read body
            content = resp.content
            result.raw_bytes = content
            result.response_bytes = len(content)

            # Decode to text if HTML-like
            if result.content_type and "html" in result.content_type.lower():
                try:
                    result.html = content.decode(result.charset or "utf-8", errors="replace")
                except (UnicodeDecodeError, LookupError):
                    result.html = content.decode("utf-8", errors="replace")

            t_end = time.monotonic()
            result.download_time_ms = (t_end - t_start) * 1000

            # Flag retryable errors
            if result.status_code in RETRY_STATUS_CODES:
                result.error = f"HTTP {result.status_code}"

        except httpx.TimeoutException as e:
            result.error = f"Timeout: {e}"
            logger.warning("Timeout fetching %s: %s", url, e)
        except httpx.HTTPError as e:
            result.error = f"HTTP error: {e}"
            logger.warning("HTTP error fetching %s: %s", url, e)
        except Exception as e:
            result.error = f"Unexpected: {e}"
            logger.error("Unexpected error fetching %s: %s", url, e)

        return result

    async def head(self, url: str) -> Optional[int]:
        """Quick HEAD request, returns status code or None on error."""
        try:
            resp = await self._client.head(
                url,
                headers={"User-Agent": self._user_agent},
                follow_redirects=True,
                timeout=10.0,
            )
            return resp.status_code
        except Exception:
            return None
