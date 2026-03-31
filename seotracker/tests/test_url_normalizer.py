"""Tests for URL normalizer module."""

import pytest
from app.crawler.url_normalizer import URLNormalizer


@pytest.fixture
def normalizer():
    return URLNormalizer(
        base_domain="example.com",
        drop_tracking_params=True,
        param_allowlist=None,
        param_denylist=None,
        include_subdomains=False,
    )


@pytest.fixture
def normalizer_subdomains():
    return URLNormalizer(
        base_domain="example.com",
        include_subdomains=True,
        subdomain_allowlist=["blog", "shop"],
    )


class TestNormalize:
    def test_basic_url(self, normalizer):
        result = normalizer.normalize("https://example.com/page")
        assert result == "https://example.com/page"

    def test_removes_fragment(self, normalizer):
        result = normalizer.normalize("https://example.com/page#section")
        assert result == "https://example.com/page"

    def test_preserves_trailing_slash(self, normalizer):
        result = normalizer.normalize("https://example.com/page/")
        assert result == "https://example.com/page/"

    def test_keeps_root_slash(self, normalizer):
        result = normalizer.normalize("https://example.com/")
        assert result == "https://example.com/"

    def test_lowercases_scheme_and_host(self, normalizer):
        result = normalizer.normalize("HTTPS://EXAMPLE.COM/Page")
        assert result == "https://example.com/Page"

    def test_removes_default_port(self, normalizer):
        result = normalizer.normalize("https://example.com:443/page")
        assert result == "https://example.com/page"

    def test_keeps_non_default_port(self, normalizer):
        result = normalizer.normalize("https://example.com:8080/page")
        assert result == "https://example.com:8080/page"

    def test_drops_tracking_params(self, normalizer):
        result = normalizer.normalize("https://example.com/page?utm_source=google&id=123")
        assert "utm_source" not in result
        assert "id=123" in result

    def test_drops_fbclid(self, normalizer):
        result = normalizer.normalize("https://example.com/page?fbclid=abc123")
        assert "fbclid" not in result

    def test_sorts_query_params(self, normalizer):
        result = normalizer.normalize("https://example.com/page?z=1&a=2")
        assert result == "https://example.com/page?a=2&z=1"

    def test_empty_url_returns_none(self, normalizer):
        assert normalizer.normalize("") is None

    def test_invalid_url_returns_none(self, normalizer):
        assert normalizer.normalize("not-a-url") is None

    def test_javascript_url_returns_none(self, normalizer):
        assert normalizer.normalize("javascript:void(0)") is None

    def test_mailto_returns_none(self, normalizer):
        assert normalizer.normalize("mailto:test@example.com") is None


class TestIsInternal:
    def test_same_domain_is_internal(self, normalizer):
        assert normalizer.is_internal("https://example.com/page") is True

    def test_different_domain_is_external(self, normalizer):
        assert normalizer.is_internal("https://other.com/page") is False

    def test_subdomain_not_internal_by_default(self, normalizer):
        assert normalizer.is_internal("https://blog.example.com/page") is False

    def test_subdomain_internal_when_allowed(self, normalizer_subdomains):
        assert normalizer_subdomains.is_internal("https://blog.example.com/page") is True
        assert normalizer_subdomains.is_internal("https://shop.example.com/page") is True

    def test_subdomain_not_in_allowlist_without_include(self):
        norm = URLNormalizer(
            base_domain="example.com",
            include_subdomains=False,
            subdomain_allowlist=["blog"],
        )
        assert norm.is_internal("https://api.example.com/page") is False
        assert norm.is_internal("https://blog.example.com/page") is True

    def test_www_requires_allowlist(self):
        norm_no_www = URLNormalizer(
            base_domain="example.com",
            include_subdomains=False,
        )
        # www is a subdomain; without allowlist or include_subdomains it's external
        assert norm_no_www.is_internal("https://www.example.com/page") is False

        norm_with_www = URLNormalizer(
            base_domain="www.example.com",
            include_subdomains=False,
        )
        assert norm_with_www.is_internal("https://www.example.com/page") is True


class TestIsResourceUrl:
    def test_image_is_resource(self, normalizer):
        assert normalizer.is_resource_url("https://example.com/img.jpg") is True
        assert normalizer.is_resource_url("https://example.com/img.png") is True
        assert normalizer.is_resource_url("https://example.com/img.webp") is True

    def test_css_is_resource(self, normalizer):
        assert normalizer.is_resource_url("https://example.com/style.css") is True

    def test_js_is_resource(self, normalizer):
        assert normalizer.is_resource_url("https://example.com/app.js") is True

    def test_html_is_not_resource(self, normalizer):
        assert normalizer.is_resource_url("https://example.com/page.html") is False

    def test_no_extension_is_not_resource(self, normalizer):
        assert normalizer.is_resource_url("https://example.com/page") is False


class TestParamDenylist:
    def test_denylist_removes_params(self):
        norm = URLNormalizer(
            base_domain="example.com",
            param_denylist=["session_id", "debug"],
        )
        result = norm.normalize("https://example.com/page?session_id=abc&color=red")
        assert "session_id" not in result
        assert "color=red" in result

    def test_allowlist_keeps_only_allowed(self):
        norm = URLNormalizer(
            base_domain="example.com",
            param_allowlist=["page", "sort"],
        )
        result = norm.normalize("https://example.com/list?page=2&sort=date&ref=nav")
        assert "page=2" in result
        assert "sort=date" in result
        assert "ref" not in result
