"""
URL hygiene analyzer for SEO audits.

Detects:
  - Mixed case URLs
  - Excessive URL depth
  - Special characters in URLs
  - Sitemap vs crawl gap
  - Faceted navigation patterns
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from urllib.parse import urlparse, parse_qs, unquote

logger = logging.getLogger(__name__)


class URLAnalyzer:
    """
    Analyze URL patterns for SEO hygiene issues.

    Usage:
        analyzer = URLAnalyzer(pages, sitemap_urls=["https://..."])
        results = analyzer.analyze()
    """

    def __init__(
        self,
        pages: list[dict],
        sitemap_urls: list[str] | None = None,
    ):
        self._pages = pages
        self._sitemap_urls = set(sitemap_urls or [])
        self._crawled_urls: set[str] = set()

        for p in pages:
            url = p.get("url", "")
            if url:
                self._crawled_urls.add(url)

    def analyze(self) -> dict:
        """Run full URL hygiene analysis."""
        return {
            "mixed_case_urls": self.get_mixed_case_urls(),
            "deep_urls": self.get_deep_urls(),
            "special_char_urls": self.get_special_char_urls(),
            "sitemap_gap": self.get_sitemap_gap(),
            "faceted_nav_suspects": self._detect_faceted_navigation(),
        }

    def get_mixed_case_urls(self) -> list[str]:
        """URLs where path contains uppercase letters."""
        mixed = []
        for p in self._pages:
            url = p.get("url", "")
            if not url:
                continue
            parsed = urlparse(url)
            # Check path for uppercase (exclude scheme and domain which are case-insensitive)
            if parsed.path != parsed.path.lower() and parsed.path != "/":
                mixed.append(url)
        return mixed

    def get_deep_urls(self, max_depth: int = 5) -> list[str]:
        """URLs with more than max_depth path segments."""
        deep = []
        for p in self._pages:
            url = p.get("url", "")
            if not url:
                continue
            parsed = urlparse(url)
            segments = [s for s in parsed.path.split("/") if s]
            if len(segments) > max_depth:
                deep.append(url)
        return deep

    def get_special_char_urls(self) -> list[str]:
        """URLs with non-standard characters in path."""
        # Allow: alphanumeric, hyphens, underscores, slashes, dots, percent-encoded
        pattern = re.compile(r"[^a-zA-Z0-9\-_/\.%]")
        special = []
        for p in self._pages:
            url = p.get("url", "")
            if not url:
                continue
            parsed = urlparse(url)
            decoded_path = unquote(parsed.path)
            if pattern.search(decoded_path):
                special.append(url)
        return special

    def get_sitemap_gap(self) -> dict:
        """Compare sitemap URLs vs crawled URLs."""
        normalized_sitemap = {url.rstrip("/") for url in self._sitemap_urls}
        normalized_crawled = {url.rstrip("/") for url in self._crawled_urls}

        in_sitemap_not_crawled = normalized_sitemap - normalized_crawled
        in_crawled_not_sitemap = normalized_crawled - normalized_sitemap

        return {
            "in_sitemap_not_crawled": list(in_sitemap_not_crawled)[:100],
            "in_crawled_not_sitemap": list(in_crawled_not_sitemap)[:100],
            "sitemap_count": len(self._sitemap_urls),
            "crawled_count": len(self._crawled_urls),
            "overlap_count": len(normalized_sitemap & normalized_crawled),
        }

    def _detect_faceted_navigation(self) -> list[str]:
        """Detect base paths that generate many parameterized variants."""
        path_groups: dict[str, list[str]] = defaultdict(list)
        for url in self._crawled_urls:
            parsed = urlparse(url)
            if parsed.query:
                base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                path_groups[base].append(url)

        suspects = []
        for base, urls in path_groups.items():
            if len(urls) > 5:  # More than 5 parameterized variants
                suspects.append(base)
        return suspects
