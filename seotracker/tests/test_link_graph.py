"""Tests for LinkGraphAnalyzer."""

import pytest
from app.crawler.link_graph import LinkGraphAnalyzer


@pytest.fixture
def simple_site():
    """A simple site with homepage linking to 3 pages."""
    pages = [
        {"url": "https://example.com/", "url_normalized": "https://example.com/", "status_code": 200, "is_indexable": True, "depth": 0},
        {"url": "https://example.com/about", "url_normalized": "https://example.com/about", "status_code": 200, "is_indexable": True, "depth": 1},
        {"url": "https://example.com/blog", "url_normalized": "https://example.com/blog", "status_code": 200, "is_indexable": True, "depth": 1},
        {"url": "https://example.com/blog/post-1", "url_normalized": "https://example.com/blog/post-1", "status_code": 200, "is_indexable": True, "depth": 2},
        {"url": "https://example.com/orphan", "url_normalized": "https://example.com/orphan", "status_code": 200, "is_indexable": True, "depth": 1},
    ]
    links = [
        {"source_url": "https://example.com/", "dest_url": "https://example.com/about", "dest_url_normalized": "https://example.com/about", "is_internal": True, "anchor_text": "About Us"},
        {"source_url": "https://example.com/", "dest_url": "https://example.com/blog", "dest_url_normalized": "https://example.com/blog", "is_internal": True, "anchor_text": "Blog"},
        {"source_url": "https://example.com/blog", "dest_url": "https://example.com/blog/post-1", "dest_url_normalized": "https://example.com/blog/post-1", "is_internal": True, "anchor_text": "First Post"},
        {"source_url": "https://example.com/about", "dest_url": "https://example.com/", "dest_url_normalized": "https://example.com/", "is_internal": True, "anchor_text": "Home"},
        # No links pointing to /orphan
    ]
    return pages, links


class TestLinkGraphAnalyzer:
    def test_orphan_detection(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        analyzer.analyze()
        orphans = analyzer.get_orphan_pages()
        assert "https://example.com/orphan" in orphans
        assert "https://example.com/about" not in orphans

    def test_click_depth(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        analyzer.analyze()
        assert analyzer.get_click_depth("https://example.com/") == 0
        assert analyzer.get_click_depth("https://example.com/about") == 1
        assert analyzer.get_click_depth("https://example.com/blog/post-1") == 2

    def test_unreachable_page(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        analyzer.analyze()
        assert analyzer.get_click_depth("https://example.com/orphan") == -1

    def test_depth_distribution(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        results = analyzer.analyze()
        dist = results["depth_distribution"]
        assert dist[0] == 1  # homepage
        assert dist[1] == 2  # about + blog
        assert dist[2] == 1  # blog/post-1

    def test_link_distribution(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        results = analyzer.analyze()
        link_dist = results["link_distribution"]
        # Homepage has 2 outlinks
        assert link_dist["outlink_counts"]["https://example.com"] == 2 or link_dist["outlink_counts"].get("https://example.com/", 0) == 2

    def test_anchor_text_stats(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=["https://example.com/"])
        results = analyzer.analyze()
        anchors = results["anchor_text_stats"]
        about_anchors = anchors.get("https://example.com/about", [])
        assert "About Us" in about_anchors

    def test_empty_site(self):
        analyzer = LinkGraphAnalyzer([], [], start_urls=[])
        results = analyzer.analyze()
        assert results["orphan_pages"] == []

    def test_no_start_urls_fallback(self, simple_site):
        pages, links = simple_site
        analyzer = LinkGraphAnalyzer(pages, links, start_urls=[])
        results = analyzer.analyze()
        # Should still compute depths using depth=0 pages
        assert len(results["click_depths"]) > 0
