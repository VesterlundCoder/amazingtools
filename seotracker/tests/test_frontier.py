"""Tests for crawl frontier module."""

import pytest
from app.crawler.url_normalizer import URLNormalizer
from app.crawler.frontier import CrawlFrontier, URLPriority


@pytest.fixture
def normalizer():
    return URLNormalizer(base_domain="example.com")


@pytest.fixture
def frontier(normalizer):
    return CrawlFrontier(normalizer=normalizer, max_pages=100, max_depth=10)


class TestSeeding:
    def test_seed_adds_urls(self, frontier):
        frontier.seed(["https://example.com/", "https://example.com/about"])
        assert frontier.queue_size == 2
        assert frontier.total_seen == 2

    def test_seed_deduplicates(self, frontier):
        frontier.seed(["https://example.com/", "https://example.com/"])
        assert frontier.queue_size == 1

    def test_seed_accepts_all_urls(self, frontier):
        # Frontier seeds all URLs; external filtering happens at orchestrator level
        frontier.seed(["https://example.com/", "https://other.com/"])
        assert frontier.queue_size == 2


class TestPop:
    def test_pop_returns_item(self, frontier):
        frontier.seed(["https://example.com/"])
        item = frontier.pop()
        assert item is not None
        assert item.url == "https://example.com/"
        assert item.depth == 0

    def test_pop_empty_returns_none(self, frontier):
        assert frontier.pop() is None

    def test_pop_removes_from_queue(self, frontier):
        frontier.seed(["https://example.com/"])
        frontier.pop()
        assert frontier.queue_size == 0
        assert frontier.is_empty()


class TestPriority:
    def test_sitemap_urls_higher_priority(self, frontier):
        frontier.seed(["https://example.com/seed"])
        frontier.add_sitemap_urls([{"loc": "https://example.com/sitemap-page", "lastmod": "2024-01-01"}])
        item = frontier.pop()
        assert item.source == "sitemap"  # sitemap has higher priority than seed

    def test_seed_before_discovered(self, frontier):
        frontier.add_discovered(["https://example.com/deep"], depth=3)
        frontier.seed(["https://example.com/home"])
        item = frontier.pop()
        assert item.source == "seed"


class TestBudget:
    def test_budget_exhausted(self, normalizer):
        frontier = CrawlFrontier(normalizer=normalizer, max_pages=2, max_depth=10)
        frontier.seed(["https://example.com/a", "https://example.com/b", "https://example.com/c"])

        item1 = frontier.pop()
        frontier.mark_done(item1.url_normalized)
        assert not frontier.is_budget_exhausted()

        item2 = frontier.pop()
        frontier.mark_done(item2.url_normalized)
        assert frontier.is_budget_exhausted()

    def test_max_depth_enforced(self, normalizer):
        frontier = CrawlFrontier(normalizer=normalizer, max_pages=100, max_depth=2)
        frontier.seed(["https://example.com/"])
        added = frontier.add_discovered(["https://example.com/deep"], depth=3)
        assert added == 0  # Should not add beyond max_depth


class TestDedup:
    def test_no_duplicate_urls(self, frontier):
        frontier.seed(["https://example.com/page"])
        added = frontier.add_discovered(["https://example.com/page"], depth=1)
        assert added == 0

    def test_has_visited(self, frontier):
        frontier.seed(["https://example.com/page"])
        assert frontier.has_visited("https://example.com/page") is True
        assert frontier.has_visited("https://example.com/other") is False


class TestStats:
    def test_stats_structure(self, frontier):
        frontier.seed(["https://example.com/"])
        stats = frontier.stats()
        assert "total_seen" in stats
        assert "total_done" in stats
        assert "queue_size" in stats
        assert "budget_remaining" in stats
        assert "budget_exhausted" in stats

    def test_mark_done_updates_stats(self, frontier):
        frontier.seed(["https://example.com/"])
        item = frontier.pop()
        frontier.mark_done(item.url_normalized)
        assert frontier.total_done == 1
