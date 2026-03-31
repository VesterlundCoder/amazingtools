"""Tests for HTML extractor module."""

import pytest
from app.crawler.extractor import HTMLExtractor


def _is_internal(url):
    return "example.com" in url and "external" not in url


@pytest.fixture
def extractor():
    return HTMLExtractor(base_url="https://example.com/page", is_internal_fn=_is_internal)


BASIC_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Test Page Title</title>
    <meta name="description" content="A test meta description for this page.">
    <link rel="canonical" href="https://example.com/page">
    <meta name="robots" content="index, follow">
    <link rel="alternate" hreflang="en" href="https://example.com/page">
    <link rel="alternate" hreflang="de" href="https://example.com/de/page">
</head>
<body>
    <h1>Main Heading</h1>
    <p>Some body text with enough words to not be considered thin content.</p>
    <h2>Section One</h2>
    <p>More text here for the first section of the page.</p>
    <a href="/about">About Us</a>
    <a href="https://external.com/link">External</a>
    <img src="/img/photo.jpg" alt="A photo">
    <img src="/img/logo.png">
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Article", "name": "Test"}
    </script>
</body>
</html>
"""

MINIMAL_HTML = """
<html><body><p>Hello</p></body></html>
"""

NOINDEX_HTML = """
<html>
<head>
    <meta name="robots" content="noindex, nofollow">
    <title>Hidden Page</title>
</head>
<body><h1>No Index</h1></body>
</html>
"""

MULTI_H1_HTML = """
<html>
<head><title>Multi H1</title></head>
<body>
    <h1>First H1</h1>
    <h1>Second H1</h1>
    <h2>An H2</h2>
</body>
</html>
"""


class TestBasicExtraction:
    def test_title(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.title == "Test Page Title"
        assert result.title_length == len("Test Page Title")

    def test_meta_description(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.meta_description == "A test meta description for this page."

    def test_canonical(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.canonical_url == "https://example.com/page"

    def test_h1(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.h1_text == "Main Heading"
        assert result.h1_count == 1

    def test_heading_outline(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert len(result.heading_outline) >= 2
        assert result.heading_outline[0]["level"] == 1
        assert result.heading_outline[0]["text"] == "Main Heading"

    def test_word_count(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.word_count > 10

    def test_content_hash(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.content_hash is not None
        assert len(result.content_hash) == 64  # sha256 hex

    def test_meta_robots(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert "index" in result.meta_robots
        assert result.is_noindex is False
        assert result.is_nofollow is False


class TestLinks:
    def test_internal_links(self, extractor):
        result = extractor.extract(BASIC_HTML)
        internal = [l for l in result.links if l.is_internal]
        assert len(internal) >= 1
        assert any("/about" in l.href for l in internal)

    def test_external_links(self, extractor):
        result = extractor.extract(BASIC_HTML)
        external = [l for l in result.links if not l.is_internal]
        assert len(external) >= 1
        assert any("external.com" in l.href_resolved for l in external)


class TestImages:
    def test_img_count(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.img_count == 2

    def test_img_missing_alt(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.img_missing_alt == 1  # logo.png has no alt

    def test_img_with_alt(self, extractor):
        result = extractor.extract(BASIC_HTML)
        with_alt = [i for i in result.images if i.alt]
        assert len(with_alt) == 1
        assert with_alt[0].alt == "A photo"


class TestHreflang:
    def test_hreflang_tags(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert len(result.hreflang_tags) == 2
        langs = {t["lang"] for t in result.hreflang_tags}
        assert "en" in langs
        assert "de" in langs


class TestStructuredData:
    def test_jsonld_extraction(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert len(result.structured_data) >= 1
        assert result.structured_data[0].get("@type") == "Article"

    def test_structured_data_types(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert "Article" in result.structured_data_types


class TestNoindex:
    def test_noindex_detected(self, extractor):
        result = extractor.extract(NOINDEX_HTML)
        assert result.is_noindex is True
        assert result.is_nofollow is True


class TestMultiH1:
    def test_multiple_h1s(self, extractor):
        result = extractor.extract(MULTI_H1_HTML)
        assert result.h1_count == 2
        assert result.h1_text == "First H1"


class TestMinimalHtml:
    def test_missing_title(self, extractor):
        result = extractor.extract(MINIMAL_HTML)
        assert result.title is None or result.title == ""

    def test_missing_meta_desc(self, extractor):
        result = extractor.extract(MINIMAL_HTML)
        assert result.meta_description is None or result.meta_description == ""

    def test_missing_canonical(self, extractor):
        result = extractor.extract(MINIMAL_HTML)
        assert result.canonical_url is None or result.canonical_url == ""


class TestLinkEdgeCases:
    def test_empty_href_skipped(self, extractor):
        html = '<html><body><a href="">Empty</a><a href="/valid">Valid</a></body></html>'
        result = extractor.extract(html)
        assert len(result.links) == 1
        assert result.links[0].href == "/valid"

    def test_javascript_href_skipped(self, extractor):
        html = '<html><body><a href="javascript:void(0)">JS</a></body></html>'
        result = extractor.extract(html)
        assert len(result.links) == 0

    def test_protocol_relative_url(self, extractor):
        html = '<html><body><a href="//example.com/page">Proto Relative</a></body></html>'
        result = extractor.extract(html)
        assert len(result.links) == 1
        assert result.links[0].href_resolved.startswith("http")

    def test_whitespace_only_href_skipped(self, extractor):
        html = '<html><body><a href="   ">Whitespace</a><a href="/ok">OK</a></body></html>'
        result = extractor.extract(html)
        hrefs = [l.href for l in result.links]
        assert "/ok" in hrefs

    def test_nofollow_link(self, extractor):
        html = '<html><body><a href="/page" rel="nofollow">Link</a></body></html>'
        result = extractor.extract(html)
        assert len(result.links) == 1
        assert result.links[0].is_follow is False

    def test_many_links_all_extracted(self, extractor):
        links_html = ''.join(f'<a href="/page{i}">Link {i}</a>' for i in range(50))
        html = f'<html><body>{links_html}</body></html>'
        result = extractor.extract(html)
        assert len(result.links) == 50


# ---------------------------------------------------------------------------
# OG tags
# ---------------------------------------------------------------------------

class TestOGTags:
    def test_og_tags_extracted(self, extractor):
        html = """
        <html><head>
            <meta property="og:title" content="OG Title">
            <meta property="og:description" content="OG Description">
            <meta property="og:image" content="https://example.com/img.jpg">
            <meta property="og:url" content="https://example.com/page">
        </head><body></body></html>
        """
        result = extractor.extract(html)
        assert result.og_title == "OG Title"
        assert result.og_description == "OG Description"
        assert result.og_image == "https://example.com/img.jpg"
        assert result.og_url == "https://example.com/page"

    def test_missing_og_tags(self, extractor):
        html = "<html><head></head><body></body></html>"
        result = extractor.extract(html)
        assert result.og_title is None
        assert result.og_description is None
        assert result.og_image is None
        assert result.og_url is None


# ---------------------------------------------------------------------------
# Twitter Card
# ---------------------------------------------------------------------------

class TestTwitterCard:
    def test_twitter_card_extracted(self, extractor):
        html = """
        <html><head>
            <meta name="twitter:card" content="summary_large_image">
            <meta name="twitter:title" content="Tweet Title">
            <meta name="twitter:description" content="Tweet Desc">
        </head><body></body></html>
        """
        result = extractor.extract(html)
        assert result.twitter_card == "summary_large_image"
        assert result.twitter_title == "Tweet Title"
        assert result.twitter_description == "Tweet Desc"

    def test_missing_twitter_card(self, extractor):
        html = "<html><head></head><body></body></html>"
        result = extractor.extract(html)
        assert result.twitter_card is None
        assert result.twitter_title is None


# ---------------------------------------------------------------------------
# Viewport
# ---------------------------------------------------------------------------

class TestViewport:
    def test_viewport_detected(self, extractor):
        html = """
        <html><head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
        </head><body></body></html>
        """
        result = extractor.extract(html)
        assert result.has_viewport is True
        assert "width=device-width" in result.viewport_content

    def test_missing_viewport(self, extractor):
        html = "<html><head></head><body></body></html>"
        result = extractor.extract(html)
        assert result.has_viewport is False
        assert result.viewport_content is None


# ---------------------------------------------------------------------------
# Charset
# ---------------------------------------------------------------------------

class TestCharset:
    def test_charset_meta_tag(self, extractor):
        html = '<html><head><meta charset="utf-8"></head><body></body></html>'
        result = extractor.extract(html)
        assert result.charset_declared == "utf-8"

    def test_charset_content_type(self, extractor):
        html = """
        <html><head>
            <meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">
        </head><body></body></html>
        """
        result = extractor.extract(html)
        assert result.charset_declared is not None
        assert "iso-8859-1" in result.charset_declared

    def test_missing_charset(self, extractor):
        html = "<html><head></head><body></body></html>"
        result = extractor.extract(html)
        assert result.charset_declared is None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_pagination_next_prev(self, extractor):
        html = """
        <html><head>
            <link rel="next" href="/page/3">
            <link rel="prev" href="/page/1">
        </head><body></body></html>
        """
        result = extractor.extract(html)
        assert result.has_pagination is True
        assert result.pagination_next is not None
        assert result.pagination_prev is not None

    def test_no_pagination(self, extractor):
        html = "<html><head></head><body></body></html>"
        result = extractor.extract(html)
        assert result.has_pagination is False
        assert result.pagination_next is None
        assert result.pagination_prev is None


# ---------------------------------------------------------------------------
# HTML lang
# ---------------------------------------------------------------------------

class TestHtmlLang:
    def test_html_lang_extracted(self, extractor):
        result = extractor.extract(BASIC_HTML)
        assert result.html_lang == "en"

    def test_missing_html_lang(self, extractor):
        html = "<html><head></head><body></body></html>"
        result = extractor.extract(html)
        assert result.html_lang is None


# ---------------------------------------------------------------------------
# Heading hierarchy gaps
# ---------------------------------------------------------------------------

class TestHeadingHierarchy:
    def test_no_gaps_sequential(self, extractor):
        html = """
        <html><body>
            <h1>Title</h1>
            <h2>Section</h2>
            <h3>Subsection</h3>
        </body></html>
        """
        result = extractor.extract(html)
        assert result.heading_hierarchy_gaps == []

    def test_gap_h1_to_h3(self, extractor):
        html = """
        <html><body>
            <h1>Title</h1>
            <h3>Subsection (skipped H2)</h3>
        </body></html>
        """
        result = extractor.extract(html)
        assert len(result.heading_hierarchy_gaps) >= 1
        assert result.heading_hierarchy_gaps[0]["from_level"] == 1
        assert result.heading_hierarchy_gaps[0]["to_level"] == 3
        assert 2 in result.heading_hierarchy_gaps[0]["skipped"]

    def test_gap_h2_to_h4(self, extractor):
        html = """
        <html><body>
            <h1>Title</h1>
            <h2>Section</h2>
            <h4>Deep section (skipped H3)</h4>
        </body></html>
        """
        result = extractor.extract(html)
        assert len(result.heading_hierarchy_gaps) >= 1
        gap = result.heading_hierarchy_gaps[0]
        assert gap["from_level"] == 2
        assert gap["to_level"] == 4


# ---------------------------------------------------------------------------
# Image dimensions
# ---------------------------------------------------------------------------

class TestImageDimensions:
    def test_img_with_dimensions(self, extractor):
        html = '<html><body><img src="/img.jpg" alt="test" width="100" height="50"></body></html>'
        result = extractor.extract(html)
        assert result.img_count == 1
        assert result.images[0].width == "100"
        assert result.images[0].height == "50"
        assert result.img_missing_dimensions == 0

    def test_img_missing_dimensions(self, extractor):
        html = '<html><body><img src="/img.jpg" alt="test"></body></html>'
        result = extractor.extract(html)
        assert result.img_missing_dimensions == 1

    def test_img_srcset(self, extractor):
        html = '<html><body><img src="/img.jpg" alt="test" srcset="/img-2x.jpg 2x"></body></html>'
        result = extractor.extract(html)
        assert result.images[0].has_srcset is True

    def test_img_no_srcset(self, extractor):
        html = '<html><body><img src="/img.jpg" alt="test"></body></html>'
        result = extractor.extract(html)
        assert result.images[0].has_srcset is False


# ---------------------------------------------------------------------------
# SPA framework detection
# ---------------------------------------------------------------------------

class TestSPADetection:
    def test_react_root(self, extractor):
        html = '<html><body><div id="root"></div></body></html>'
        result = extractor.extract(html)
        assert result.spa_framework == "react"

    def test_next_js(self, extractor):
        html = '<html><body><div id="__next"></div></body></html>'
        result = extractor.extract(html)
        assert result.spa_framework == "next"

    def test_vue_nuxt(self, extractor):
        html = '<html><body><div id="__nuxt"></div></body></html>'
        result = extractor.extract(html)
        assert result.spa_framework == "nuxt"

    def test_angular(self, extractor):
        html = '<html><body><div ng-app="myApp"></div></body></html>'
        result = extractor.extract(html)
        assert result.spa_framework == "angular"

    def test_no_spa(self, extractor):
        html = "<html><body><p>Plain HTML</p></body></html>"
        result = extractor.extract(html)
        assert result.spa_framework is None


# ---------------------------------------------------------------------------
# Noscript fallback
# ---------------------------------------------------------------------------

class TestNoscript:
    def test_meaningful_noscript(self, extractor):
        content = "A" * 60
        html = f'<html><body><noscript>{content}</noscript></body></html>'
        result = extractor.extract(html)
        assert result.has_noscript_fallback is True

    def test_short_noscript(self, extractor):
        html = '<html><body><noscript>Enable JS</noscript></body></html>'
        result = extractor.extract(html)
        assert result.has_noscript_fallback is False

    def test_no_noscript(self, extractor):
        html = "<html><body><p>Normal page</p></body></html>"
        result = extractor.extract(html)
        assert result.has_noscript_fallback is False


# ---------------------------------------------------------------------------
# Security signals
# ---------------------------------------------------------------------------

class TestSecuritySignals:
    def test_mixed_content_detected(self):
        extractor = HTMLExtractor(base_url="https://example.com/page", is_internal_fn=_is_internal)
        html = '<html><body><img src="http://insecure.com/img.jpg"></body></html>'
        result = extractor.extract(html)
        assert result.has_mixed_content is True

    def test_no_mixed_content_on_https(self):
        extractor = HTMLExtractor(base_url="https://example.com/page", is_internal_fn=_is_internal)
        html = '<html><body><img src="https://secure.com/img.jpg"></body></html>'
        result = extractor.extract(html)
        assert result.has_mixed_content is False

    def test_no_mixed_content_on_http_page(self):
        extractor = HTMLExtractor(base_url="http://example.com/page", is_internal_fn=_is_internal)
        html = '<html><body><img src="http://other.com/img.jpg"></body></html>'
        result = extractor.extract(html)
        assert result.has_mixed_content is False

    def test_form_actions_extracted(self):
        extractor = HTMLExtractor(base_url="https://example.com/page", is_internal_fn=_is_internal)
        html = '<html><body><form action="https://example.com/submit"><input type="text"></form></body></html>'
        result = extractor.extract(html)
        assert "https://example.com/submit" in result.form_actions


# ---------------------------------------------------------------------------
# Accessibility signals
# ---------------------------------------------------------------------------

class TestAccessibilitySignals:
    def test_empty_link_counted(self, extractor):
        html = '<html><body><a href="/page"></a><a href="/other">Has text</a></body></html>'
        result = extractor.extract(html)
        assert result.empty_link_count == 1

    def test_link_with_aria_label_not_empty(self, extractor):
        html = '<html><body><a href="/page" aria-label="Click here"></a></body></html>'
        result = extractor.extract(html)
        assert result.empty_link_count == 0

    def test_link_with_img_alt_not_empty(self, extractor):
        html = '<html><body><a href="/page"><img src="/icon.png" alt="Icon"></a></body></html>'
        result = extractor.extract(html)
        assert result.empty_link_count == 0

    def test_form_input_without_label(self, extractor):
        html = '<html><body><form><input type="text"></form></body></html>'
        result = extractor.extract(html)
        assert result.form_inputs_without_label >= 1

    def test_form_input_with_label(self, extractor):
        html = """
        <html><body><form>
            <label for="name">Name</label>
            <input type="text" id="name">
        </form></body></html>
        """
        result = extractor.extract(html)
        assert result.form_inputs_without_label == 0

    def test_form_input_with_aria_label(self, extractor):
        html = '<html><body><form><input type="text" aria-label="Search"></form></body></html>'
        result = extractor.extract(html)
        assert result.form_inputs_without_label == 0

    def test_skip_nav_detected(self, extractor):
        html = '<html><body><a href="#main-content">Skip to main content</a><div id="main-content">Content</div></body></html>'
        result = extractor.extract(html)
        assert result.has_skip_nav is True

    def test_no_skip_nav(self, extractor):
        html = '<html><body><a href="/page">Regular link</a></body></html>'
        result = extractor.extract(html)
        assert result.has_skip_nav is False
