"""Tests for audit rules engine."""

import pytest
from app.audit.rules import (
    check_robots_txt,
    check_sitemap_health,
    check_status_codes,
    check_redirects,
    check_canonicals,
    check_on_page,
    check_links,
    check_images,
    check_hreflang,
    check_duplicate_content,
    check_mobile_parity,
    check_performance,
    check_js_parity,
    check_indexing_policy,
    check_structured_data,
    check_meta_tags,
    check_content_quality,
    check_performance_hints,
    check_security,
    check_accessibility,
    run_all_checks,
)


# ---------------------------------------------------------------------------
# Fixtures: sample page/link data
# ---------------------------------------------------------------------------

@pytest.fixture
def healthy_page():
    return {
        "url": "https://example.com/",
        "status_code": 200,
        "is_indexable": True,
        "title": "Example Domain — Quality Content",
        "title_length": 35,
        "meta_description": "A comprehensive meta description with substantial content providing detailed information.",
        "meta_description_length": 85,
        "h1_text": "Welcome to Example",
        "h1_count": 1,
        "word_count": 500,
        "content_hash": "abc123",
        "canonical_url": "https://example.com/",
        "hreflang_tags": [],
        "structured_data": [{"@type": "WebSite"}],
        "structured_data_types": ["WebSite"],
        "img_count": 3,
        "img_missing_alt": 0,
        "internal_links_count": 10,
        "external_links_count": 2,
        "was_rendered": False,
        "redirect_chain": [],
        "ttfb_ms": 200,
        "response_bytes": 50000,
    }


@pytest.fixture
def pages_with_issues():
    return [
        {
            "url": "https://example.com/no-title",
            "status_code": 200,
            "is_indexable": True,
            "title": "",
            "title_length": 0,
            "meta_description": "",
            "h1_text": "",
            "h1_count": 0,
            "word_count": 30,
            "content_hash": "hash1",
            "canonical_url": "",
        },
        {
            "url": "https://example.com/404-page",
            "status_code": 404,
            "is_indexable": False,
        },
        {
            "url": "https://example.com/500-page",
            "status_code": 500,
            "is_indexable": False,
        },
        {
            "url": "https://example.com/redirect",
            "status_code": 200,
            "redirect_chain": [
                {"url": "https://example.com/old", "status_code": 301},
                {"url": "https://example.com/older", "status_code": 301},
                {"url": "https://example.com/oldest", "status_code": 301},
            ],
            "is_indexable": True,
            "title": "Redirected",
            "title_length": 10,
            "h1_count": 1,
            "h1_text": "Redirected",
            "word_count": 200,
            "canonical_url": "https://example.com/redirect",
        },
    ]


# ---------------------------------------------------------------------------
# Robots.txt
# ---------------------------------------------------------------------------

class TestRobotsTxt:
    def test_missing_robots(self, healthy_page):
        robots = {"exists": False, "status_code": 404}
        issues = check_robots_txt(robots, [healthy_page])
        types = {i["issue_type"] for i in issues}
        assert "robots_txt_missing" in types

    def test_present_robots(self, healthy_page):
        robots = {"exists": True, "status_code": 200}
        issues = check_robots_txt(robots, [healthy_page])
        types = {i["issue_type"] for i in issues}
        assert "robots_txt_missing" not in types


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------

class TestSitemap:
    def test_missing_sitemap(self, healthy_page):
        issues = check_sitemap_health(0, [healthy_page])
        types = {i["issue_type"] for i in issues}
        assert "sitemap_missing" in types

    def test_present_sitemap(self, healthy_page):
        issues = check_sitemap_health(50, [healthy_page])
        types = {i["issue_type"] for i in issues}
        assert "sitemap_missing" not in types


# ---------------------------------------------------------------------------
# Status codes
# ---------------------------------------------------------------------------

class TestStatusCodes:
    def test_detects_4xx(self, pages_with_issues):
        issues = check_status_codes(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "http_4xx" in types

    def test_detects_5xx(self, pages_with_issues):
        issues = check_status_codes(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "http_5xx" in types

    def test_no_issues_for_200(self, healthy_page):
        issues = check_status_codes([healthy_page])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Redirects
# ---------------------------------------------------------------------------

class TestRedirects:
    def test_detects_long_chain(self, pages_with_issues):
        issues = check_redirects(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "redirect_chain" in types

    def test_no_redirect_issues(self, healthy_page):
        issues = check_redirects([healthy_page])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Canonicals
# ---------------------------------------------------------------------------

class TestCanonicals:
    def test_missing_canonical(self, pages_with_issues):
        issues = check_canonicals(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "canonical_missing" in types

    def test_valid_canonical(self, healthy_page):
        issues = check_canonicals([healthy_page])
        types = {i["issue_type"] for i in issues}
        assert "canonical_missing" not in types


# ---------------------------------------------------------------------------
# On-page
# ---------------------------------------------------------------------------

class TestOnPage:
    def test_missing_title(self, pages_with_issues):
        issues = check_on_page(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "title_missing" in types

    def test_missing_h1(self, pages_with_issues):
        issues = check_on_page(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "h1_missing" in types

    def test_thin_content(self, pages_with_issues):
        issues = check_on_page(pages_with_issues)
        types = {i["issue_type"] for i in issues}
        assert "thin_content" in types

    def test_healthy_page_no_on_page_issues(self, healthy_page):
        issues = check_on_page([healthy_page])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Hreflang
# ---------------------------------------------------------------------------

class TestHreflang:
    def test_missing_self_reference(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "de", "href": "https://example.com/de"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_missing_self" in types

    def test_valid_self_reference(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "en", "href": "https://example.com/en"},
                {"lang": "de", "href": "https://example.com/de"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_missing_self" not in types

    def test_canonical_conflict(self):
        pages = [{
            "url": "https://example.com/en",
            "canonical_url": "https://example.com/other",
            "hreflang_tags": [
                {"lang": "en", "href": "https://example.com/en"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_canonical_conflict" in types

    def test_no_hreflang_no_issues(self, healthy_page):
        issues = check_hreflang([healthy_page])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Duplicate content
# ---------------------------------------------------------------------------

class TestDuplicateContent:
    def test_exact_duplicates(self):
        pages = [
            {"url": "https://example.com/a", "status_code": 200, "is_indexable": True, "content_hash": "same_hash"},
            {"url": "https://example.com/b", "status_code": 200, "is_indexable": True, "content_hash": "same_hash"},
        ]
        issues = check_duplicate_content(pages)
        types = {i["issue_type"] for i in issues}
        assert "duplicate_content" in types

    def test_no_duplicates(self):
        pages = [
            {"url": "https://example.com/a", "status_code": 200, "is_indexable": True, "content_hash": "hash1"},
            {"url": "https://example.com/b", "status_code": 200, "is_indexable": True, "content_hash": "hash2"},
        ]
        issues = check_duplicate_content(pages)
        types = {i["issue_type"] for i in issues}
        assert "duplicate_content" not in types


# ---------------------------------------------------------------------------
# Mobile parity
# ---------------------------------------------------------------------------

class TestMobileParity:
    def test_content_parity_issue(self):
        pages = [{
            "url": "https://example.com/",
            "mobile_checked": True,
            "word_count": 500,
            "internal_links_count": 20,
            "mobile_diff": {
                "desktop_word_count": 500,
                "mobile_word_count": 100,
                "desktop_internal_links": 20,
                "mobile_internal_links": 20,
            },
        }]
        issues = check_mobile_parity(pages)
        types = {i["issue_type"] for i in issues}
        assert "mobile_content_parity" in types

    def test_no_mobile_data(self, healthy_page):
        issues = check_mobile_parity([healthy_page])
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

class TestPerformance:
    def test_slow_ttfb(self):
        pages = [{"url": "https://example.com/slow", "status_code": 200, "ttfb_ms": 3000}]
        issues = check_performance(pages)
        types = {i["issue_type"] for i in issues}
        assert "slow_ttfb" in types

    def test_fast_ttfb(self, healthy_page):
        issues = check_performance([healthy_page])
        types = {i["issue_type"] for i in issues}
        assert "slow_ttfb" not in types


# ---------------------------------------------------------------------------
# Master runner
# ---------------------------------------------------------------------------

class TestRunAllChecks:
    def test_returns_combined_issues(self, pages_with_issues):
        issues = run_all_checks(
            pages=pages_with_issues,
            links=[],
            robots_data={"exists": False, "status_code": 404},
            sitemap_urls_count=0,
        )
        assert len(issues) > 0
        # Should have at least robots, sitemap, status code, canonical, on-page issues
        types = {i["issue_type"] for i in issues}
        assert "robots_txt_missing" in types
        assert "sitemap_missing" in types

    def test_issue_format(self, pages_with_issues):
        issues = run_all_checks(
            pages=pages_with_issues,
            links=[],
            robots_data={"exists": True, "status_code": 200},
            sitemap_urls_count=10,
        )
        for issue in issues:
            assert "issue_type" in issue
            assert "severity" in issue
            assert issue["severity"] in ("critical", "high", "medium", "low")
            assert "affected_urls_count" in issue
            assert "how_to_fix" in issue
            assert "why_it_matters" in issue

    def test_all_20_checks_run(self, pages_with_issues):
        """Verify run_all_checks invokes all 20 check functions without error."""
        issues = run_all_checks(
            pages=pages_with_issues,
            links=[],
            robots_data={"exists": True, "status_code": 200},
            sitemap_urls_count=10,
        )
        # Should return a list (even if empty would be fine, but we know there are issues)
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# Indexing policy
# ---------------------------------------------------------------------------

class TestIndexingPolicy:
    def test_noindex_should_index(self):
        pages = [{
            "url": "https://example.com/big-page",
            "status_code": 200,
            "is_noindex": True,
            "internal_links_count": 10,
            "word_count": 500,
        }]
        issues = check_indexing_policy(pages)
        types = {i["issue_type"] for i in issues}
        assert "noindex_should_index" in types

    def test_noindex_thin_page_no_issue(self):
        pages = [{
            "url": "https://example.com/thin",
            "status_code": 200,
            "is_noindex": True,
            "internal_links_count": 1,
            "word_count": 10,
        }]
        issues = check_indexing_policy(pages)
        types = {i["issue_type"] for i in issues}
        assert "noindex_should_index" not in types

    def test_robots_noindex_conflict(self):
        pages = [{
            "url": "https://example.com/conflict",
            "status_code": 200,
            "robots_txt_allowed": False,
            "is_noindex": True,
        }]
        issues = check_indexing_policy(pages)
        types = {i["issue_type"] for i in issues}
        assert "robots_noindex_conflict" in types


# ---------------------------------------------------------------------------
# Enhanced On-page: H1 length, H1 matches title, heading hierarchy
# ---------------------------------------------------------------------------

class TestOnPageEnhanced:
    def test_h1_too_short(self):
        pages = [{
            "url": "https://example.com/short-h1",
            "status_code": 200, "is_indexable": True,
            "title": "A proper title for this page",
            "title_length": 30,
            "h1_text": "Hi",
            "h1_count": 1,
            "word_count": 300,
            "canonical_url": "https://example.com/short-h1",
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "h1_too_short" in types

    def test_h1_too_long(self):
        pages = [{
            "url": "https://example.com/long-h1",
            "status_code": 200, "is_indexable": True,
            "title": "A proper title",
            "title_length": 14,
            "h1_text": "A" * 80,
            "h1_count": 1,
            "word_count": 300,
            "canonical_url": "https://example.com/long-h1",
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "h1_too_long" in types

    def test_h1_matches_title(self):
        pages = [{
            "url": "https://example.com/same",
            "status_code": 200, "is_indexable": True,
            "title": "Exactly The Same Heading",
            "title_length": 24,
            "h1_text": "Exactly The Same Heading",
            "h1_count": 1,
            "word_count": 300,
            "canonical_url": "https://example.com/same",
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "h1_matches_title" in types

    def test_h1_different_from_title_no_issue(self):
        pages = [{
            "url": "https://example.com/diff",
            "status_code": 200, "is_indexable": True,
            "title": "SEO Title for the Page",
            "title_length": 22,
            "h1_text": "Welcome to Our Page",
            "h1_count": 1,
            "word_count": 300,
            "canonical_url": "https://example.com/diff",
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "h1_matches_title" not in types

    def test_heading_hierarchy_gap(self):
        pages = [{
            "url": "https://example.com/gaps",
            "status_code": 200, "is_indexable": True,
            "title": "Page with gaps",
            "title_length": 14,
            "h1_text": "Main heading here",
            "h1_count": 1,
            "word_count": 300,
            "canonical_url": "https://example.com/gaps",
            "heading_hierarchy_gaps": [{"from_level": 1, "to_level": 3, "skipped": [2]}],
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "heading_hierarchy_gap" in types

    def test_no_heading_hierarchy_gap(self):
        pages = [{
            "url": "https://example.com/clean",
            "status_code": 200, "is_indexable": True,
            "title": "Clean Page Title Here",
            "title_length": 21,
            "h1_text": "Different from title heading",
            "h1_count": 1,
            "word_count": 300,
            "canonical_url": "https://example.com/clean",
            "heading_hierarchy_gaps": [],
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "heading_hierarchy_gap" not in types

    def test_meta_desc_too_short(self):
        pages = [{
            "url": "https://example.com/short-desc",
            "status_code": 200, "is_indexable": True,
            "title": "Proper title for short desc",
            "title_length": 27,
            "h1_text": "A good enough heading text",
            "h1_count": 1,
            "meta_description": "Too short.",
            "meta_description_length": 10,
            "word_count": 300,
            "canonical_url": "https://example.com/short-desc",
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "meta_desc_too_short" in types

    def test_meta_desc_too_long(self):
        pages = [{
            "url": "https://example.com/long-desc",
            "status_code": 200, "is_indexable": True,
            "title": "Proper title for long desc",
            "title_length": 26,
            "h1_text": "A good enough heading text",
            "h1_count": 1,
            "meta_description": "A" * 170,
            "meta_description_length": 170,
            "word_count": 300,
            "canonical_url": "https://example.com/long-desc",
        }]
        issues = check_on_page(pages)
        types = {i["issue_type"] for i in issues}
        assert "meta_desc_too_long" in types


# ---------------------------------------------------------------------------
# Structured data enhanced
# ---------------------------------------------------------------------------

class TestStructuredDataEnhanced:
    def test_invalid_jsonld(self):
        pages = [{
            "url": "https://example.com/bad-sd",
            "status_code": 200, "is_indexable": True,
            "structured_data": [{"_error": "Invalid JSON-LD"}],
        }]
        issues = check_structured_data(pages)
        types = {i["issue_type"] for i in issues}
        assert "structured_data_invalid" in types

    def test_missing_structured_data_on_content_page(self):
        pages = [{
            "url": "https://example.com/content",
            "status_code": 200, "is_indexable": True,
            "word_count": 500,
            "structured_data": [],
        }]
        issues = check_structured_data(pages)
        types = {i["issue_type"] for i in issues}
        assert "structured_data_missing" in types

    def test_structured_data_present_no_missing_issue(self):
        pages = [{
            "url": "https://example.com/has-sd",
            "status_code": 200, "is_indexable": True,
            "word_count": 500,
            "structured_data": [{"@type": "Article", "headline": "Test", "author": "A", "datePublished": "2024-01-01"}],
        }]
        issues = check_structured_data(pages)
        types = {i["issue_type"] for i in issues}
        assert "structured_data_missing" not in types

    def test_missing_required_fields(self):
        pages = [{
            "url": "https://example.com/product",
            "status_code": 200, "is_indexable": True,
            "structured_data": [{"@type": "Product"}],  # missing name, image, offers
        }]
        issues = check_structured_data(pages)
        types = {i["issue_type"] for i in issues}
        assert "structured_data_missing_fields" in types

    def test_complete_product_no_missing_fields(self):
        pages = [{
            "url": "https://example.com/product-ok",
            "status_code": 200, "is_indexable": True,
            "structured_data": [{
                "@type": "Product",
                "name": "Widget",
                "image": "https://example.com/img.jpg",
                "offers": {"price": "9.99"},
            }],
        }]
        issues = check_structured_data(pages)
        types = {i["issue_type"] for i in issues}
        assert "structured_data_missing_fields" not in types

    def test_article_missing_fields(self):
        pages = [{
            "url": "https://example.com/article",
            "status_code": 200, "is_indexable": True,
            "structured_data": [{"@type": "Article", "headline": "Test"}],  # missing author, datePublished
        }]
        issues = check_structured_data(pages)
        types = {i["issue_type"] for i in issues}
        assert "structured_data_missing_fields" in types


# ---------------------------------------------------------------------------
# Links: broken, orphans, depth
# ---------------------------------------------------------------------------

class TestLinksEnhanced:
    def test_broken_internal_link(self):
        pages = [
            {"url": "https://example.com/", "url_normalized": "https://example.com/", "status_code": 200, "is_indexable": True, "depth": 0},
            {"url": "https://example.com/404", "url_normalized": "https://example.com/404", "status_code": 404, "is_indexable": False},
        ]
        links = [
            {"source_url": "https://example.com/", "dest_url": "https://example.com/404", "dest_url_normalized": "https://example.com/404", "is_internal": True},
        ]
        issues = check_links(pages, links)
        types = {i["issue_type"] for i in issues}
        assert "broken_internal_link" in types

    def test_orphan_page_detected(self):
        pages = [
            {"url": "https://example.com/", "url_normalized": "https://example.com/", "status_code": 200, "is_indexable": True, "depth": 0},
            {"url": "https://example.com/orphan", "url_normalized": "https://example.com/orphan", "status_code": 200, "is_indexable": True, "depth": 1},
        ]
        links = []  # no links pointing to orphan
        issues = check_links(pages, links)
        types = {i["issue_type"] for i in issues}
        assert "orphan_page" in types

    def test_high_click_depth(self):
        pages = [{
            "url": "https://example.com/deep",
            "status_code": 200, "is_indexable": True, "depth": 7,
        }]
        issues = check_links(pages, [])
        types = {i["issue_type"] for i in issues}
        assert "high_click_depth" in types

    def test_no_issues_well_linked(self):
        pages = [
            {"url": "https://example.com/", "url_normalized": "https://example.com/", "status_code": 200, "is_indexable": True, "depth": 0},
            {"url": "https://example.com/about", "url_normalized": "https://example.com/about", "status_code": 200, "is_indexable": True, "depth": 1},
        ]
        links = [
            {"source_url": "https://example.com/", "dest_url": "https://example.com/about", "dest_url_normalized": "https://example.com/about", "is_internal": True},
        ]
        issues = check_links(pages, links)
        types = {i["issue_type"] for i in issues}
        assert "broken_internal_link" not in types
        assert "orphan_page" not in types


# ---------------------------------------------------------------------------
# Images enhanced
# ---------------------------------------------------------------------------

class TestImagesEnhanced:
    def test_img_missing_alt(self):
        pages = [{"url": "https://example.com/", "img_missing_alt": 3}]
        issues = check_images(pages)
        types = {i["issue_type"] for i in issues}
        assert "img_missing_alt" in types

    def test_img_missing_dimensions(self):
        pages = [{"url": "https://example.com/", "img_missing_dimensions": 5}]
        issues = check_images(pages)
        types = {i["issue_type"] for i in issues}
        assert "img_missing_dimensions" in types

    def test_no_image_issues(self):
        pages = [{"url": "https://example.com/", "img_missing_alt": 0, "img_missing_dimensions": 0}]
        issues = check_images(pages)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Hreflang enhanced
# ---------------------------------------------------------------------------

class TestHreflangEnhanced:
    def test_invalid_language_code(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "en", "href": "https://example.com/en"},
                {"lang": "xx", "href": "https://example.com/xx"},  # invalid
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_invalid_lang" in types

    def test_valid_language_codes_no_issue(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "en", "href": "https://example.com/en"},
                {"lang": "de", "href": "https://example.com/de"},
                {"lang": "x-default", "href": "https://example.com/"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_invalid_lang" not in types

    def test_x_default_missing(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "en", "href": "https://example.com/en"},
                {"lang": "de", "href": "https://example.com/de"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_x_default_missing" in types

    def test_x_default_present(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "en", "href": "https://example.com/en"},
                {"lang": "x-default", "href": "https://example.com/"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_x_default_missing" not in types

    def test_hreflang_to_error_page(self):
        pages = [
            {
                "url": "https://example.com/en",
                "hreflang_tags": [
                    {"lang": "en", "href": "https://example.com/en"},
                    {"lang": "de", "href": "https://example.com/de"},
                ],
            },
            {
                "url": "https://example.com/de",
                "status_code": 404,
                "hreflang_tags": [],
            },
        ]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_to_error" in types

    def test_regional_language_codes_valid(self):
        pages = [{
            "url": "https://example.com/en",
            "hreflang_tags": [
                {"lang": "en-us", "href": "https://example.com/en"},
                {"lang": "pt-br", "href": "https://example.com/pt"},
                {"lang": "x-default", "href": "https://example.com/"},
            ],
        }]
        issues = check_hreflang(pages)
        types = {i["issue_type"] for i in issues}
        assert "hreflang_invalid_lang" not in types


# ---------------------------------------------------------------------------
# Meta tags
# ---------------------------------------------------------------------------

class TestMetaTags:
    def test_og_tags_missing(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200, "is_indexable": True,
            "og_title": None,
        }]
        issues = check_meta_tags(pages)
        types = {i["issue_type"] for i in issues}
        assert "og_tags_missing" in types

    def test_og_tags_present(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200, "is_indexable": True,
            "og_title": "My Page",
            "twitter_card": "summary",
            "has_viewport": True,
            "charset_declared": "utf-8",
        }]
        issues = check_meta_tags(pages)
        types = {i["issue_type"] for i in issues}
        assert "og_tags_missing" not in types

    def test_twitter_card_missing(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200, "is_indexable": True,
            "og_title": "Title",
            "twitter_card": None,
        }]
        issues = check_meta_tags(pages)
        types = {i["issue_type"] for i in issues}
        assert "twitter_card_missing" in types

    def test_viewport_missing(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "has_viewport": False,
        }]
        issues = check_meta_tags(pages)
        types = {i["issue_type"] for i in issues}
        assert "viewport_missing" in types

    def test_charset_missing(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "charset_declared": None,
        }]
        issues = check_meta_tags(pages)
        types = {i["issue_type"] for i in issues}
        assert "charset_missing" in types

    def test_all_meta_present_no_issues(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200, "is_indexable": True,
            "og_title": "Title",
            "twitter_card": "summary_large_image",
            "has_viewport": True,
            "charset_declared": "utf-8",
        }]
        issues = check_meta_tags(pages)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Content quality
# ---------------------------------------------------------------------------

class TestContentQuality:
    def test_keyword_stuffing(self):
        # Create text where a word appears > 5% of total
        words = ["seo"] * 20 + ["other", "words", "here", "more"] * 25
        text = " ".join(words)
        pages = [{
            "url": "https://example.com/stuffed",
            "status_code": 200, "is_indexable": True,
            "main_text": text,
            "word_count": len(words),
            "structured_data": [],
        }]
        issues = check_content_quality(pages)
        types = {i["issue_type"] for i in issues}
        assert "keyword_stuffing" in types

    def test_no_keyword_stuffing(self):
        words = [f"word{i}" for i in range(200)]
        text = " ".join(words)
        pages = [{
            "url": "https://example.com/clean",
            "status_code": 200, "is_indexable": True,
            "main_text": text,
            "word_count": 200,
            "structured_data": [],
        }]
        issues = check_content_quality(pages)
        types = {i["issue_type"] for i in issues}
        assert "keyword_stuffing" not in types

    def test_stale_content(self):
        pages = [{
            "url": "https://example.com/old",
            "status_code": 200, "is_indexable": True,
            "structured_data": [{"@type": "Article", "datePublished": "2020-01-01"}],
        }]
        issues = check_content_quality(pages)
        types = {i["issue_type"] for i in issues}
        assert "stale_content" in types

    def test_fresh_content_no_stale_issue(self):
        pages = [{
            "url": "https://example.com/fresh",
            "status_code": 200, "is_indexable": True,
            "structured_data": [{"@type": "Article", "datePublished": "2026-01-01"}],
        }]
        issues = check_content_quality(pages)
        types = {i["issue_type"] for i in issues}
        assert "stale_content" not in types


# ---------------------------------------------------------------------------
# Performance hints
# ---------------------------------------------------------------------------

class TestPerformanceHints:
    def test_cls_risk(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "img_missing_dimensions": 5,
        }]
        issues = check_performance_hints(pages)
        types = {i["issue_type"] for i in issues}
        assert "cls_risk" in types

    def test_no_cls_risk(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "img_missing_dimensions": 0,
        }]
        issues = check_performance_hints(pages)
        types = {i["issue_type"] for i in issues}
        assert "cls_risk" not in types

    def test_render_blocking_resource(self):
        pages = [{
            "url": "https://example.com/heavy",
            "status_code": 200,
            "response_bytes": 200000,
        }]
        issues = check_performance_hints(pages)
        types = {i["issue_type"] for i in issues}
        assert "render_blocking_resource" in types

    def test_medium_ttfb(self):
        """Test the new medium-severity TTFB tier (600-2000ms)."""
        pages = [{"url": "https://example.com/med", "status_code": 200, "ttfb_ms": 1000}]
        issues = check_performance(pages)
        types = {i["issue_type"] for i in issues}
        assert "slow_ttfb" in types


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

class TestSecurity:
    def test_mixed_content(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "has_mixed_content": True,
        }]
        issues = check_security(pages)
        types = {i["issue_type"] for i in issues}
        assert "mixed_content" in types

    def test_no_mixed_content_on_http(self):
        """HTTP pages don't trigger mixed content warnings."""
        pages = [{
            "url": "http://example.com/",
            "status_code": 200,
            "has_mixed_content": True,
        }]
        issues = check_security(pages)
        types = {i["issue_type"] for i in issues}
        assert "mixed_content" not in types

    def test_missing_hsts(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "headers": {"Content-Type": "text/html"},
        }]
        issues = check_security(pages)
        types = {i["issue_type"] for i in issues}
        assert "missing_hsts" in types

    def test_hsts_present(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "headers": {"Strict-Transport-Security": "max-age=31536000"},
        }]
        issues = check_security(pages)
        types = {i["issue_type"] for i in issues}
        assert "missing_hsts" not in types

    def test_insecure_form_action(self):
        pages = [{
            "url": "https://example.com/form",
            "status_code": 200,
            "form_actions": ["http://example.com/submit"],
        }]
        issues = check_security(pages)
        types = {i["issue_type"] for i in issues}
        assert "insecure_form_action" in types

    def test_secure_form_action(self):
        pages = [{
            "url": "https://example.com/form",
            "status_code": 200,
            "form_actions": ["https://example.com/submit"],
        }]
        issues = check_security(pages)
        types = {i["issue_type"] for i in issues}
        assert "insecure_form_action" not in types


# ---------------------------------------------------------------------------
# Accessibility
# ---------------------------------------------------------------------------

class TestAccessibility:
    def test_missing_html_lang(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "html_lang": None,
        }]
        issues = check_accessibility(pages)
        types = {i["issue_type"] for i in issues}
        assert "missing_html_lang" in types

    def test_html_lang_present(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "html_lang": "en",
            "empty_link_count": 0,
            "form_inputs_without_label": 0,
            "has_skip_nav": True,
        }]
        issues = check_accessibility(pages)
        types = {i["issue_type"] for i in issues}
        assert "missing_html_lang" not in types

    def test_empty_link_text(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "html_lang": "en",
            "empty_link_count": 5,
            "has_skip_nav": True,
        }]
        issues = check_accessibility(pages)
        types = {i["issue_type"] for i in issues}
        assert "empty_link_text" in types

    def test_missing_form_label(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "html_lang": "en",
            "empty_link_count": 0,
            "form_inputs_without_label": 3,
            "has_skip_nav": True,
        }]
        issues = check_accessibility(pages)
        types = {i["issue_type"] for i in issues}
        assert "missing_form_label" in types

    def test_missing_skip_nav(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "html_lang": "en",
            "empty_link_count": 0,
            "form_inputs_without_label": 0,
            "has_skip_nav": False,
        }]
        issues = check_accessibility(pages)
        types = {i["issue_type"] for i in issues}
        assert "missing_skip_nav" in types

    def test_fully_accessible_page(self):
        pages = [{
            "url": "https://example.com/",
            "status_code": 200,
            "html_lang": "en",
            "empty_link_count": 0,
            "form_inputs_without_label": 0,
            "has_skip_nav": True,
        }]
        issues = check_accessibility(pages)
        assert len(issues) == 0


# ---------------------------------------------------------------------------
# Duplicate content enhanced (near-duplicates)
# ---------------------------------------------------------------------------

class TestDuplicateContentEnhanced:
    def test_parameter_duplicates(self):
        pages = [
            {"url": "https://example.com/page?color=red", "status_code": 200, "is_indexable": True, "content_hash": "same"},
            {"url": "https://example.com/page?color=blue", "status_code": 200, "is_indexable": True, "content_hash": "same"},
        ]
        issues = check_duplicate_content(pages)
        types = {i["issue_type"] for i in issues}
        # Should detect these as duplicate_content (exact hash match) AND/OR param_duplicate
        assert "duplicate_content" in types or "param_duplicate" in types


# ---------------------------------------------------------------------------
# JS parity
# ---------------------------------------------------------------------------

class TestJsParity:
    def test_js_render_errors(self):
        pages = [{
            "url": "https://example.com/",
            "was_rendered": True,
            "console_errors": ["TypeError: Cannot read properties of null"],
        }]
        issues = check_js_parity(pages)
        types = {i["issue_type"] for i in issues}
        assert "js_render_errors" in types

    def test_js_content_parity(self):
        pages = [{
            "url": "https://example.com/",
            "was_rendered": True,
            "raw_vs_rendered_diff": {"h1_changed": True},
        }]
        issues = check_js_parity(pages)
        types = {i["issue_type"] for i in issues}
        assert "js_content_parity" in types

    def test_no_js_issues_unrendered(self, healthy_page):
        issues = check_js_parity([healthy_page])
        assert len(issues) == 0
