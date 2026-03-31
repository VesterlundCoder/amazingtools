"""
Link graph analyzer for internal link structure analysis.

Provides:
  - BFS-based click depth calculation from homepage
  - Orphan page detection (pages with no inbound internal links)
  - Internal link distribution metrics
  - Anchor text distribution per target URL
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class LinkGraphAnalyzer:
    """
    Analyze the internal link graph of a crawled site.

    Usage:
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        results = analyzer.analyze()
    """

    def __init__(
        self,
        pages: list[dict],
        links: list[dict],
        start_urls: list[str] | None = None,
    ):
        self._pages = pages
        self._links = links
        self._start_urls = set(
            url.rstrip("/") for url in (start_urls or [])
        )

        # Build graph structures
        self._page_urls: set[str] = set()
        self._inlinks: dict[str, list[dict]] = defaultdict(list)
        self._outlinks: dict[str, list[dict]] = defaultdict(list)
        self._click_depths: dict[str, int] = {}

        self._build_graph()

    def _normalize_url(self, url: str) -> str:
        """Strip trailing slash for consistent comparison."""
        return url.rstrip("/") if url else ""

    def _build_graph(self):
        """Build adjacency lists from link data."""
        for p in self._pages:
            url = self._normalize_url(p.get("url_normalized") or p.get("url", ""))
            if url:
                self._page_urls.add(url)

        for link in self._links:
            if not link.get("is_internal"):
                continue
            source = self._normalize_url(link.get("source_url", ""))
            dest = self._normalize_url(
                link.get("dest_url_normalized") or link.get("dest_url", "")
            )
            if source and dest:
                self._outlinks[source].append(link)
                self._inlinks[dest].append(link)

    def analyze(self) -> dict:
        """Run full link graph analysis. Returns results dict."""
        self._compute_click_depths()

        return {
            "orphan_pages": self.get_orphan_pages(),
            "click_depths": dict(self._click_depths),
            "link_distribution": self._get_link_distribution(),
            "anchor_text_stats": self._get_anchor_text_stats(),
            "depth_distribution": self.get_depth_distribution(),
        }

    def _compute_click_depths(self):
        """BFS from start URLs to compute click depth."""
        queue = deque()

        # Seed with start URLs
        for start in self._start_urls:
            normalized = self._normalize_url(start)
            if normalized in self._page_urls:
                self._click_depths[normalized] = 0
                queue.append(normalized)

        # If no start URLs match, use pages at depth 0
        if not queue:
            for p in self._pages:
                if p.get("depth", -1) == 0:
                    url = self._normalize_url(
                        p.get("url_normalized") or p.get("url", "")
                    )
                    if url and url not in self._click_depths:
                        self._click_depths[url] = 0
                        queue.append(url)

        # BFS
        while queue:
            current = queue.popleft()
            current_depth = self._click_depths[current]

            for link in self._outlinks.get(current, []):
                dest = self._normalize_url(
                    link.get("dest_url_normalized") or link.get("dest_url", "")
                )
                if dest and dest in self._page_urls and dest not in self._click_depths:
                    self._click_depths[dest] = current_depth + 1
                    queue.append(dest)

    def get_orphan_pages(self) -> list[str]:
        """Get pages with zero inbound internal links (excluding seeds)."""
        orphans = []
        for p in self._pages:
            url = self._normalize_url(p.get("url_normalized") or p.get("url", ""))
            if not url:
                continue
            # Skip seed URLs
            if url in self._start_urls:
                continue
            # Skip non-indexable or error pages
            if not p.get("is_indexable", True):
                continue
            if (p.get("status_code") or 0) != 200:
                continue
            # Check inlinks
            if len(self._inlinks.get(url, [])) == 0:
                orphans.append(p.get("url", url))
        return orphans

    def get_click_depth(self, url: str) -> int:
        """Get click depth for a specific URL. Returns -1 if unreachable."""
        return self._click_depths.get(self._normalize_url(url), -1)

    def get_pages_by_depth(self, max_depth: int = 10) -> dict[int, list[str]]:
        """Group pages by click depth."""
        by_depth: dict[int, list[str]] = defaultdict(list)
        for url, depth in self._click_depths.items():
            if depth <= max_depth:
                by_depth[depth].append(url)
        return dict(by_depth)

    def get_depth_distribution(self) -> dict[int, int]:
        """Get count of pages at each depth level."""
        dist: dict[int, int] = defaultdict(int)
        for depth in self._click_depths.values():
            dist[depth] += 1
        # Add unreachable pages
        unreachable = len(self._page_urls) - len(self._click_depths)
        if unreachable > 0:
            dist[-1] = unreachable
        return dict(sorted(dist.items()))

    def _get_link_distribution(self) -> dict:
        """Get link count stats per page."""
        inlink_counts = {}
        outlink_counts = {}
        for url in self._page_urls:
            inlink_counts[url] = len(self._inlinks.get(url, []))
            outlink_counts[url] = len(self._outlinks.get(url, []))

        return {
            "inlink_counts": inlink_counts,
            "outlink_counts": outlink_counts,
            "pages_with_few_inlinks": [
                url for url, count in inlink_counts.items() if count < 2
            ],
            "pages_with_many_outlinks": [
                url for url, count in outlink_counts.items() if count > 100
            ],
        }

    def _get_anchor_text_stats(self) -> dict[str, list[str]]:
        """Get anchor text distribution per target URL."""
        anchor_texts: dict[str, list[str]] = defaultdict(list)
        for link in self._links:
            if not link.get("is_internal"):
                continue
            dest = self._normalize_url(
                link.get("dest_url_normalized") or link.get("dest_url", "")
            )
            text = (link.get("anchor_text") or "").strip()
            if dest and text:
                anchor_texts[dest].append(text)
        return dict(anchor_texts)
