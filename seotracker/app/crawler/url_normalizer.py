"""
URL normalization and parameter policy.

Responsibilities:
  - Normalize URLs to a canonical form (scheme, host, path, query)
  - Drop tracking parameters (utm_*, gclid, fbclid, etc.)
  - Apply allow/deny list for query parameters
  - Sort query parameters for consistent dedup
  - Classify URLs (internal/external, resource type)
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import (
    parse_qs,
    quote,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)

import tldextract

# Common tracking parameters to strip
DEFAULT_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "gclid", "gclsrc", "dclid", "gbraid", "wbraid",
    "fbclid", "fb_action_ids", "fb_action_types", "fb_source", "fb_ref",
    "msclkid",
    "mc_cid", "mc_eid",
    "yclid",
    "twclid",
    "_ga", "_gl", "_gid",
    "ref", "ref_src",
    "s_cid", "s_kwcid",
    "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad", "hsa_src", "hsa_tgt",
    "hsa_kw", "hsa_mt", "hsa_net", "hsa_ver", "hsa_la", "hsa_ol",
})

# URL schemes to skip
SKIP_SCHEMES = frozenset({"mailto", "tel", "javascript", "data", "ftp"})


class URLNormalizer:
    """
    Normalize URLs with configurable parameter policies.

    Usage:
        normalizer = URLNormalizer(
            base_domain="example.com",
            drop_tracking_params=True,
        )
        normalized = normalizer.normalize("https://Example.COM/path?utm_source=x&b=2&a=1")
        # → "https://example.com/path?a=1&b=2"
    """

    def __init__(
        self,
        base_domain: str,
        drop_tracking_params: bool = True,
        param_allowlist: list[str] | None = None,
        param_denylist: list[str] | None = None,
        include_subdomains: bool = False,
        subdomain_allowlist: list[str] | None = None,
    ):
        self._base_domain = base_domain.lower()
        self._base_extract = tldextract.extract(base_domain)
        self._drop_tracking = drop_tracking_params
        self._param_allowlist = set(param_allowlist) if param_allowlist else None
        self._param_denylist = set(param_denylist or [])
        self._include_subdomains = include_subdomains
        self._subdomain_allowlist = set(s.lower() for s in (subdomain_allowlist or []))

    def normalize(self, url: str) -> Optional[str]:
        """
        Normalize a URL. Returns None if the URL should be skipped.
        """
        url = url.strip()
        if not url:
            return None

        # Skip non-HTTP schemes
        parsed = urlparse(url)
        if parsed.scheme.lower() in SKIP_SCHEMES or not parsed.scheme:
            return None

        # Force lowercase scheme + host
        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            return None

        host = parsed.hostname
        if not host:
            return None
        host = host.lower()

        # Remove default ports
        port = parsed.port
        if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
            port = None
        netloc = host if not port else f"{host}:{port}"

        # Normalize path
        path = self._normalize_path(parsed.path)

        # Normalize query parameters
        query = self._normalize_query(parsed.query)

        # Drop fragment
        normalized = urlunparse((scheme, netloc, path, "", query, ""))
        return normalized

    def _normalize_path(self, path: str) -> str:
        """Normalize URL path: decode, re-encode, resolve dots, ensure leading /."""
        if not path:
            return "/"

        # Decode then re-encode (normalize %XX casing)
        path = unquote(path)
        # Remove double slashes
        path = re.sub(r"/+", "/", path)
        # Re-encode special chars but keep / and common safe chars
        path = quote(path, safe="/:@!$&'()*+,;=-._~")

        if not path.startswith("/"):
            path = "/" + path

        return path

    def _normalize_query(self, query: str) -> str:
        """Normalize query string: sort params, drop tracking, apply policies."""
        if not query:
            return ""

        params = parse_qs(query, keep_blank_values=True)
        filtered: dict[str, list[str]] = {}

        for key, values in params.items():
            key_lower = key.lower()

            # Drop tracking params
            if self._drop_tracking and key_lower in DEFAULT_TRACKING_PARAMS:
                continue

            # Apply denylist
            if key_lower in self._param_denylist:
                continue

            # Apply allowlist (if set, only keep allowed params)
            if self._param_allowlist is not None and key_lower not in self._param_allowlist:
                continue

            filtered[key] = values

        if not filtered:
            return ""

        # Sort by key for consistency
        sorted_params = sorted(filtered.items())
        return urlencode(sorted_params, doseq=True)

    def is_internal(self, url: str) -> bool:
        """Check if a URL belongs to the same registrable domain."""
        try:
            ext = tldextract.extract(url)
        except Exception:
            return False

        # Same registered domain?
        if ext.registered_domain.lower() != self._base_extract.registered_domain.lower():
            return False

        # Subdomain check
        if ext.subdomain and ext.subdomain != self._base_extract.subdomain:
            if not self._include_subdomains:
                # Check allowlist
                if ext.subdomain.lower() not in self._subdomain_allowlist:
                    return False

        return True

    def should_crawl(self, url: str) -> bool:
        """
        Quick check: is this URL internal and has an HTTP(S) scheme?
        Does NOT check robots.txt (that's a separate layer).
        """
        normalized = self.normalize(url)
        if not normalized:
            return False
        return self.is_internal(normalized)

    @staticmethod
    def is_resource_url(url: str) -> bool:
        """Check if URL points to a non-HTML resource (image, CSS, JS, etc.)."""
        parsed = urlparse(url)
        path_lower = parsed.path.lower()
        resource_exts = {
            ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".bmp",
            ".css", ".js", ".json", ".xml",
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".zip", ".tar", ".gz", ".rar",
            ".mp3", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm",
            ".woff", ".woff2", ".ttf", ".eot", ".otf",
        }
        for ext in resource_exts:
            if path_lower.endswith(ext):
                return True
        return False
