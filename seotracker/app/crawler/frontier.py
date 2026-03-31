"""
Crawl frontier: priority queue with dedup, depth tracking, and backpressure.

Responsibilities:
  - Maintain a per-run URL queue with priority ordering
  - Deduplicate via normalized URL keys
  - Enforce max_pages and max_depth caps
  - Prioritize: sitemap URLs > low depth > high depth
  - Track visited URLs
"""

from __future__ import annotations

import heapq
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from app.crawler.url_normalizer import URLNormalizer

logger = logging.getLogger(__name__)


class URLPriority(IntEnum):
    """Lower value = higher priority (used in min-heap)."""
    SITEMAP_RECENT = 0    # sitemap URL with recent lastmod
    SITEMAP = 1           # sitemap URL
    SEED = 2              # start URL / homepage
    DEPTH_0 = 3           # homepage links
    DEPTH_1 = 4           # category/section pages
    DEPTH_2 = 5           # article/product pages
    DEPTH_DEEP = 6        # deep pages
    DISCOVERED = 7        # found via crawl, no special signal


@dataclass(order=True)
class FrontierItem:
    """An item in the crawl frontier priority queue."""
    priority: int
    url: str = field(compare=False)
    url_normalized: str = field(compare=False)
    depth: int = field(compare=False, default=0)
    parent_url: Optional[str] = field(compare=False, default=None)
    source: str = field(compare=False, default="crawl")  # "seed", "sitemap", "crawl"


class CrawlFrontier:
    """
    Priority-based crawl frontier with dedup and caps.

    Usage:
        frontier = CrawlFrontier(normalizer, max_pages=10000, max_depth=50)
        frontier.seed(["https://example.com/"])
        frontier.add_sitemap_urls(sitemap_urls)

        while not frontier.is_empty() and not frontier.is_budget_exhausted():
            item = frontier.pop()
            # ... crawl item.url ...
            frontier.mark_done(item.url_normalized)
            frontier.add_discovered(new_urls, depth=item.depth + 1, parent=item.url)
    """

    def __init__(
        self,
        normalizer: URLNormalizer,
        max_pages: int = 10000,
        max_depth: int = 50,
    ):
        self._normalizer = normalizer
        self._max_pages = max_pages
        self._max_depth = max_depth

        self._queue: list[FrontierItem] = []  # min-heap
        self._seen: set[str] = set()           # normalized URLs ever enqueued
        self._done: set[str] = set()           # normalized URLs fully processed
        self._in_queue: set[str] = set()       # currently in queue (not yet popped)

    @property
    def total_seen(self) -> int:
        return len(self._seen)

    @property
    def total_done(self) -> int:
        return len(self._done)

    @property
    def queue_size(self) -> int:
        return len(self._in_queue)

    def is_empty(self) -> bool:
        return len(self._in_queue) == 0

    def is_budget_exhausted(self) -> bool:
        return self._done.__len__() >= self._max_pages

    def _should_add(self, url_normalized: str, depth: int) -> bool:
        """Check if URL should be added to frontier."""
        if url_normalized in self._seen:
            return False
        if depth > self._max_depth:
            return False
        if self._normalizer.is_resource_url(url_normalized):
            return False
        if not self._normalizer.is_internal(url_normalized):
            return False
        return True

    def _enqueue(self, item: FrontierItem):
        """Add item to the priority queue."""
        if item.url_normalized in self._seen:
            return
        self._seen.add(item.url_normalized)
        self._in_queue.add(item.url_normalized)
        heapq.heappush(self._queue, item)

    def seed(self, start_urls: list[str]):
        """Add seed/start URLs with highest priority."""
        for url in start_urls:
            normalized = self._normalizer.normalize(url)
            if not normalized:
                continue
            self._enqueue(FrontierItem(
                priority=URLPriority.SEED,
                url=url,
                url_normalized=normalized,
                depth=0,
                source="seed",
            ))
        logger.info("Frontier seeded with %d start URLs", len(start_urls))

    def add_sitemap_urls(self, sitemap_urls: list[dict]):
        """
        Add URLs from sitemap discovery.
        
        Args:
            sitemap_urls: list of {"loc": str, "lastmod": str|None, ...}
        """
        added = 0
        for entry in sitemap_urls:
            loc = entry.get("loc") if isinstance(entry, dict) else getattr(entry, "loc", str(entry))
            normalized = self._normalizer.normalize(str(loc))
            if not normalized:
                continue
            if not self._should_add(normalized, depth=1):
                continue

            lastmod = entry.get("lastmod") if isinstance(entry, dict) else getattr(entry, "lastmod", None)
            priority = URLPriority.SITEMAP_RECENT if lastmod else URLPriority.SITEMAP

            self._enqueue(FrontierItem(
                priority=priority,
                url=str(loc),
                url_normalized=normalized,
                depth=1,
                source="sitemap",
            ))
            added += 1

        logger.info("Added %d sitemap URLs to frontier (total seen: %d)", added, self.total_seen)

    def add_discovered(
        self,
        urls: list[str],
        depth: int,
        parent_url: Optional[str] = None,
    ) -> int:
        """
        Add URLs discovered during crawl.
        Returns number of new URLs added.
        """
        added = 0
        for url in urls:
            normalized = self._normalizer.normalize(url)
            if not normalized:
                continue
            if not self._should_add(normalized, depth):
                continue

            # Assign priority based on depth
            if depth == 0:
                priority = URLPriority.DEPTH_0
            elif depth == 1:
                priority = URLPriority.DEPTH_1
            elif depth == 2:
                priority = URLPriority.DEPTH_2
            elif depth <= 5:
                priority = URLPriority.DEPTH_DEEP
            else:
                priority = URLPriority.DISCOVERED

            self._enqueue(FrontierItem(
                priority=priority,
                url=url,
                url_normalized=normalized,
                depth=depth,
                parent_url=parent_url,
                source="crawl",
            ))
            added += 1

        return added

    def pop(self) -> Optional[FrontierItem]:
        """Pop the highest-priority URL from the frontier."""
        while self._queue:
            item = heapq.heappop(self._queue)
            self._in_queue.discard(item.url_normalized)
            # Skip if already done (shouldn't happen often but safety check)
            if item.url_normalized in self._done:
                continue
            return item
        return None

    def mark_done(self, url_normalized: str):
        """Mark a URL as fully processed."""
        self._done.add(url_normalized)
        self._in_queue.discard(url_normalized)

    def has_visited(self, url: str) -> bool:
        """Check if a URL has been seen (enqueued or done)."""
        normalized = self._normalizer.normalize(url)
        if not normalized:
            return True  # skip non-normalizable
        return normalized in self._seen

    def stats(self) -> dict:
        """Return frontier statistics."""
        return {
            "total_seen": self.total_seen,
            "total_done": self.total_done,
            "queue_size": self.queue_size,
            "budget_remaining": max(0, self._max_pages - self.total_done),
            "budget_exhausted": self.is_budget_exhausted(),
        }
