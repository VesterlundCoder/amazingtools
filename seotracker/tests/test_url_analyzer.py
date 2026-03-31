"""Tests for URLAnalyzer."""

import pytest
from app.crawler.url_analyzer import URLAnalyzer


@pytest.fixture
def sample_pages():
    return [
        {"url": "https://example.com/", "status_code": 200},
        {"url": "https://example.com/About-Us", "status_code": 200},
        {"url": "https://example.com/blog/post-1", "status_code": 200},
        {"url": "https://example.com/a/b/c/d/e/f/deep-page", "status_code": 200},
        {"url": "https://example.com/page?sort=price&color=red", "status_code": 200},
        {"url": "https://example.com/page?sort=price&color=blue", "status_code": 200},
        {"url": "https://example.com/page?sort=price&color=green", "status_code": 200},
        {"url": "https://example.com/page?sort=price&color=yellow", "status_code": 200},
        {"url": "https://example.com/page?sort=price&color=black", "status_code": 200},
        {"url": "https://example.com/page?sort=price&color=white", "status_code": 200},
        {"url": "https://example.com/path/with spaces/file", "status_code": 200},
    ]


class TestURLAnalyzer:
    def test_mixed_case_detection(self, sample_pages):
        analyzer = URLAnalyzer(sample_pages)
        mixed = analyzer.get_mixed_case_urls()
        assert "https://example.com/About-Us" in mixed
        assert "https://example.com/" not in mixed

    def test_deep_urls(self, sample_pages):
        analyzer = URLAnalyzer(sample_pages)
        deep = analyzer.get_deep_urls(max_depth=5)
        assert "https://example.com/a/b/c/d/e/f/deep-page" in deep
        assert "https://example.com/blog/post-1" not in deep

    def test_special_char_urls(self, sample_pages):
        analyzer = URLAnalyzer(sample_pages)
        special = analyzer.get_special_char_urls()
        assert "https://example.com/path/with spaces/file" in special

    def test_sitemap_gap(self, sample_pages):
        sitemap_urls = [
            "https://example.com/",
            "https://example.com/blog/post-1",
            "https://example.com/missing-page",
        ]
        analyzer = URLAnalyzer(sample_pages, sitemap_urls=sitemap_urls)
        gap = analyzer.get_sitemap_gap()
        assert "https://example.com/missing-page" in gap["in_sitemap_not_crawled"]
        assert gap["sitemap_count"] == 3

    def test_faceted_navigation(self, sample_pages):
        analyzer = URLAnalyzer(sample_pages)
        results = analyzer.analyze()
        suspects = results["faceted_nav_suspects"]
        assert "https://example.com/page" in suspects

    def test_empty_pages(self):
        analyzer = URLAnalyzer([])
        results = analyzer.analyze()
        assert results["mixed_case_urls"] == []
        assert results["deep_urls"] == []

    def test_full_analysis(self, sample_pages):
        analyzer = URLAnalyzer(sample_pages)
        results = analyzer.analyze()
        assert "mixed_case_urls" in results
        assert "deep_urls" in results
        assert "special_char_urls" in results
        assert "sitemap_gap" in results
