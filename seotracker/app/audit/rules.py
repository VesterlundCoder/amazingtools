"""
Audit rules engine for technical SEO + on-page checks.

Each rule function takes crawl data (pages, links, robots, sitemaps)
and returns a list of Issue dicts.

Issue dict format:
{
    "issue_type": str (IssueType enum value),
    "severity": str (critical/high/medium/low),
    "confidence": float (0-1),
    "affected_url": str,
    "affected_urls_count": int,
    "affected_urls_sample": list[str],
    "detail": dict,
    "how_to_fix": str,
    "why_it_matters": str,
}
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _issue(
    issue_type: str,
    severity: str,
    affected_urls: list[str],
    detail: dict | None = None,
    how_to_fix: str = "",
    why_it_matters: str = "",
    confidence: float = 1.0,
) -> dict:
    return {
        "issue_type": issue_type,
        "severity": severity,
        "confidence": confidence,
        "affected_url": affected_urls[0] if affected_urls else None,
        "affected_urls_count": len(affected_urls),
        "affected_urls_sample": affected_urls[:10],
        "detail": detail or {},
        "how_to_fix": how_to_fix,
        "why_it_matters": why_it_matters,
    }


# ---------------------------------------------------------------------------
# 2D.1  Crawlability & Discovery
# ---------------------------------------------------------------------------

def check_robots_txt(robots_data: dict, pages: list[dict]) -> list[dict]:
    """Check robots.txt availability and configuration."""
    issues = []

    if not robots_data.get("exists"):
        status = robots_data.get("status_code")
        if status and status >= 500:
            issues.append(_issue(
                "robots_txt_error", "high", [],
                detail={"status_code": status},
                how_to_fix="Fix the server error on /robots.txt so search engines can access it.",
                why_it_matters="A 5xx on robots.txt may cause Google to temporarily stop crawling the site.",
            ))
        else:
            issues.append(_issue(
                "robots_txt_missing", "medium", [],
                how_to_fix="Create a /robots.txt file with appropriate directives and a Sitemap: directive.",
                why_it_matters="robots.txt helps search engines crawl efficiently and discover your sitemap.",
            ))

    if robots_data.get("parse_error"):
        issues.append(_issue(
            "robots_txt_error", "medium", [],
            detail={"error": robots_data["parse_error"]},
            how_to_fix="Fix the syntax of your robots.txt file.",
            why_it_matters="Parse errors may cause search engines to misinterpret your crawl directives.",
        ))

    # Check if robots blocks important pages
    blocked = [p["url"] for p in pages if not p.get("robots_txt_allowed", True)]
    if blocked:
        issues.append(_issue(
            "robots_blocks_important", "high", blocked,
            how_to_fix="Review robots.txt Disallow rules and ensure important pages are not blocked.",
            why_it_matters="Pages blocked by robots.txt cannot be crawled or indexed by search engines.",
        ))

    # Check if sitemap directive is missing
    if robots_data.get("exists") and not robots_data.get("sitemap_urls"):
        issues.append(_issue(
            "sitemap_missing", "low", [],
            how_to_fix="Add a Sitemap: directive to your robots.txt pointing to your XML sitemap.",
            why_it_matters="Sitemap directives help search engines discover your sitemap faster.",
            confidence=0.8,
        ))

    return issues


def check_sitemap_health(
    sitemap_urls_count: int,
    pages: list[dict],
) -> list[dict]:
    """Check sitemap vs crawled pages consistency."""
    issues = []

    if sitemap_urls_count == 0:
        issues.append(_issue(
            "sitemap_missing", "medium", [],
            how_to_fix="Create an XML sitemap and submit it via robots.txt or Search Console.",
            why_it_matters="Sitemaps help search engines discover and prioritize your pages.",
        ))

    # Sitemap URLs that returned errors
    sitemap_sourced = [p for p in pages if p.get("source") == "sitemap"]
    error_urls = [p["url"] for p in sitemap_sourced if (p.get("status_code") or 200) >= 400]
    if error_urls:
        issues.append(_issue(
            "sitemap_url_error", "high", error_urls,
            how_to_fix="Remove error URLs from your sitemap or fix the pages.",
            why_it_matters="Sitemaps should only contain valid, indexable URLs.",
        ))

    # Sitemap URL is noindex
    noindex_in_sitemap = [
        p["url"] for p in sitemap_sourced
        if p.get("is_noindex")
    ]
    if noindex_in_sitemap:
        issues.append(_issue(
            "sitemap_robots_conflict", "high", noindex_in_sitemap,
            detail={"conflict": "URL in sitemap but has noindex"},
            how_to_fix="Remove noindex pages from the sitemap, or remove the noindex directive.",
            why_it_matters="Including noindex URLs in sitemaps sends conflicting signals to search engines.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.2  Status codes
# ---------------------------------------------------------------------------

def check_status_codes(pages: list[dict]) -> list[dict]:
    issues = []

    pages_4xx = [p["url"] for p in pages if 400 <= (p.get("status_code") or 0) < 500]
    pages_5xx = [p["url"] for p in pages if (p.get("status_code") or 0) >= 500]

    if pages_4xx:
        issues.append(_issue(
            "http_4xx", "high", pages_4xx,
            how_to_fix="Fix or redirect 4xx pages. Remove internal links pointing to them.",
            why_it_matters="4xx errors waste crawl budget and create poor user experience.",
        ))

    if pages_5xx:
        issues.append(_issue(
            "http_5xx", "critical", pages_5xx,
            how_to_fix="Investigate and fix server errors. Check logs for root cause.",
            why_it_matters="5xx errors indicate server problems that prevent indexing.",
        ))

    # Soft 404 heuristic
    soft_404s = []
    for p in pages:
        if p.get("status_code") == 200 and p.get("word_count", 999) < 50:
            title = (p.get("title") or "").lower()
            if any(kw in title for kw in ["not found", "404", "page not found", "error"]):
                soft_404s.append(p["url"])
    if soft_404s:
        issues.append(_issue(
            "soft_404", "medium", soft_404s,
            confidence=0.7,
            how_to_fix="Return proper 404 status codes for pages that don't exist.",
            why_it_matters="Soft 404s waste crawl budget and may dilute site quality signals.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.3  Redirects
# ---------------------------------------------------------------------------

def check_redirects(pages: list[dict]) -> list[dict]:
    issues = []

    chains = [
        p["url"] for p in pages
        if len(p.get("redirect_chain") or []) > 1
    ]
    if chains:
        issues.append(_issue(
            "redirect_chain", "medium", chains,
            how_to_fix="Update redirects to point directly to the final destination (single hop).",
            why_it_matters="Redirect chains slow down crawling and may lose link equity.",
        ))

    loops = [p["url"] for p in pages if p.get("is_redirect_loop")]
    if loops:
        issues.append(_issue(
            "redirect_loop", "critical", loops,
            how_to_fix="Break the redirect loop by fixing the redirect target.",
            why_it_matters="Redirect loops make pages completely inaccessible.",
        ))

    # Redirect to 4xx/5xx
    redirect_to_error = []
    for p in pages:
        chain = p.get("redirect_chain") or []
        if chain and (p.get("status_code") or 200) >= 400:
            redirect_to_error.append(p["url"])
    if redirect_to_error:
        issues.append(_issue(
            "redirect_to_error", "high", redirect_to_error,
            how_to_fix="Update redirects to point to valid pages.",
            why_it_matters="Redirecting to error pages wastes crawl budget and breaks user journeys.",
        ))

    # Mixed redirect chains (301 + 302)
    mixed = []
    for p in pages:
        chain = p.get("redirect_chain") or []
        if len(chain) > 1:
            codes = {hop.get("status_code") for hop in chain}
            if 301 in codes and 302 in codes:
                mixed.append(p["url"])
    if mixed:
        issues.append(_issue(
            "mixed_redirect_chain", "medium", mixed,
            how_to_fix="Use consistent redirect types (prefer 301 for permanent moves).",
            why_it_matters="Mixed redirect chains can confuse search engines about canonical signals.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.4  Canonicalization
# ---------------------------------------------------------------------------

def check_canonicals(pages: list[dict]) -> list[dict]:
    issues = []

    indexable = [p for p in pages if p.get("is_indexable", True) and (p.get("status_code") or 0) == 200]

    missing_canonical = [p["url"] for p in indexable if not p.get("canonical_url")]
    if missing_canonical:
        issues.append(_issue(
            "canonical_missing", "medium", missing_canonical,
            how_to_fix="Add a self-referencing rel=canonical to every indexable page.",
            why_it_matters="Missing canonicals make it harder for search engines to consolidate duplicate signals.",
        ))

    multiple_canonical = [p["url"] for p in pages if (p.get("canonical_count") or 0) > 1]
    if multiple_canonical:
        issues.append(_issue(
            "canonical_multiple", "high", multiple_canonical,
            how_to_fix="Ensure each page has exactly one rel=canonical tag.",
            why_it_matters="Multiple canonicals create ambiguity; search engines may ignore them.",
        ))

    # Canonical vs final URL mismatch
    mismatch = []
    for p in indexable:
        canonical = p.get("canonical_url")
        final = p.get("final_url") or p.get("url")
        if canonical and final and canonical.rstrip("/") != final.rstrip("/"):
            mismatch.append(p["url"])
    if mismatch:
        issues.append(_issue(
            "canonical_mismatch", "medium", mismatch,
            how_to_fix="Align the canonical URL with the final (post-redirect) URL of the page.",
            why_it_matters="Canonical mismatches send mixed signals about which URL should be indexed.",
            confidence=0.8,
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.5  Meta robots / indexing
# ---------------------------------------------------------------------------

def check_indexing_policy(pages: list[dict], noindex_patterns: list[str] = None) -> list[dict]:
    issues = []

    noindex_pages = [p for p in pages if p.get("is_noindex") and (p.get("status_code") or 0) == 200]
    if noindex_pages:
        # Check if noindex is on pages that should be indexed
        suspicious = [
            p["url"] for p in noindex_pages
            if p.get("internal_links_count", 0) > 5 and p.get("word_count", 0) > 200
        ]
        if suspicious:
            issues.append(_issue(
                "noindex_should_index", "critical", suspicious,
                confidence=0.7,
                how_to_fix="Review noindex directives on these content-rich pages.",
                why_it_matters="Noindexing pages with substantial content prevents them from appearing in search.",
            ))

    # Robots blocked + noindex conflict
    conflicts = [
        p["url"] for p in pages
        if not p.get("robots_txt_allowed", True) and p.get("is_noindex")
    ]
    if conflicts:
        issues.append(_issue(
            "robots_noindex_conflict", "high", conflicts,
            how_to_fix="If you want to noindex, remove the robots.txt block so search engines can see the noindex tag.",
            why_it_matters="If robots.txt blocks crawling, search engines can't see the noindex directive.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.7  On-page: titles, descriptions, headings
# ---------------------------------------------------------------------------

def check_on_page(pages: list[dict]) -> list[dict]:
    issues = []
    indexable = [p for p in pages if p.get("is_indexable", True) and (p.get("status_code") or 0) == 200]

    # Titles
    missing_title = [p["url"] for p in indexable if not p.get("title")]
    if missing_title:
        issues.append(_issue(
            "title_missing", "high", missing_title,
            how_to_fix="Add a unique, descriptive <title> tag to each page.",
            why_it_matters="Title tags are a primary ranking factor and the main text in search results.",
        ))

    short_title = [p["url"] for p in indexable if p.get("title") and (p.get("title_length") or 0) < 15]
    if short_title:
        issues.append(_issue(
            "title_too_short", "medium", short_title,
            how_to_fix="Write more descriptive titles (30-60 characters recommended).",
            why_it_matters="Very short titles miss opportunities to target keywords and attract clicks.",
        ))

    long_title = [p["url"] for p in indexable if (p.get("title_length") or 0) > 70]
    if long_title:
        issues.append(_issue(
            "title_too_long", "low", long_title,
            how_to_fix="Shorten titles to under 60-65 characters to prevent truncation in SERPs.",
            why_it_matters="Truncated titles may lose important keywords and reduce CTR.",
        ))

    # Duplicate titles
    title_map: dict[str, list[str]] = defaultdict(list)
    for p in indexable:
        if p.get("title"):
            title_map[p["title"].strip().lower()].append(p["url"])
    dup_titles = [urls for urls in title_map.values() if len(urls) > 1]
    if dup_titles:
        all_dup_urls = [url for group in dup_titles for url in group]
        issues.append(_issue(
            "title_duplicate", "medium", all_dup_urls,
            detail={"duplicate_groups": len(dup_titles)},
            how_to_fix="Write unique titles for each page.",
            why_it_matters="Duplicate titles make it harder for search engines to differentiate pages.",
        ))

    # Meta descriptions
    missing_desc = [p["url"] for p in indexable if not p.get("meta_description")]
    if missing_desc:
        issues.append(_issue(
            "meta_desc_missing", "low", missing_desc,
            how_to_fix="Add a unique meta description (120-155 chars) to each page.",
            why_it_matters="Meta descriptions influence click-through rates from search results.",
        ))

    desc_map: dict[str, list[str]] = defaultdict(list)
    for p in indexable:
        if p.get("meta_description"):
            desc_map[p["meta_description"].strip().lower()].append(p["url"])
    dup_descs = [urls for urls in desc_map.values() if len(urls) > 1]
    if dup_descs:
        all_dup_urls = [url for group in dup_descs for url in group]
        issues.append(_issue(
            "meta_desc_duplicate", "low", all_dup_urls,
            detail={"duplicate_groups": len(dup_descs)},
            how_to_fix="Write unique meta descriptions for each page.",
            why_it_matters="Duplicate descriptions reduce their effectiveness as SERP snippets.",
        ))

    # Meta description too short
    desc_short = [
        p["url"] for p in indexable
        if p.get("meta_description") and (p.get("meta_description_length") or 0) < 70
    ]
    if desc_short:
        issues.append(_issue(
            "meta_desc_too_short", "low", desc_short,
            how_to_fix="Write meta descriptions of at least 70 characters for better SERP coverage.",
            why_it_matters="Short meta descriptions may not adequately describe the page content.",
        ))

    # Meta description too long
    desc_long = [
        p["url"] for p in indexable
        if (p.get("meta_description_length") or 0) > 160
    ]
    if desc_long:
        issues.append(_issue(
            "meta_desc_too_long", "low", desc_long,
            how_to_fix="Keep meta descriptions under 155-160 characters to avoid truncation.",
            why_it_matters="Truncated descriptions may lose important messaging in search results.",
        ))

    # H1
    missing_h1 = [p["url"] for p in indexable if (p.get("h1_count") or 0) == 0]
    if missing_h1:
        issues.append(_issue(
            "h1_missing", "high", missing_h1,
            how_to_fix="Add a single, descriptive H1 heading to each page.",
            why_it_matters="H1 headings help search engines and users understand the page topic.",
        ))

    multiple_h1 = [p["url"] for p in indexable if (p.get("h1_count") or 0) > 1]
    if multiple_h1:
        issues.append(_issue(
            "h1_multiple", "low", multiple_h1,
            how_to_fix="Use only one H1 per page. Use H2-H6 for subheadings.",
            why_it_matters="Multiple H1s can dilute the main topic signal.",
        ))

    # H1 too short
    h1_short = [p["url"] for p in indexable if p.get("h1_text") and len(p["h1_text"].strip()) < 10]
    if h1_short:
        issues.append(_issue(
            "h1_too_short", "low", h1_short,
            how_to_fix="Write a more descriptive H1 heading (at least 10 characters).",
            why_it_matters="Very short H1s miss opportunities to describe the page topic clearly.",
        ))

    # H1 too long
    h1_long = [p["url"] for p in indexable if p.get("h1_text") and len(p["h1_text"].strip()) > 70]
    if h1_long:
        issues.append(_issue(
            "h1_too_long", "low", h1_long,
            how_to_fix="Keep H1 headings under 70 characters for clarity and display purposes.",
            why_it_matters="Excessively long H1s may be truncated and lose visual impact.",
        ))

    # H1 matches title exactly
    h1_title_match = [
        p["url"] for p in indexable
        if p.get("h1_text") and p.get("title")
        and p["h1_text"].strip().lower() == p["title"].strip().lower()
    ]
    if h1_title_match:
        issues.append(_issue(
            "h1_matches_title", "low", h1_title_match,
            confidence=0.6,
            how_to_fix="Differentiate H1 from title tag — use the H1 for on-page topic and title for SERP display.",
            why_it_matters="Identical H1 and title is a missed opportunity to target additional keywords.",
        ))

    # Heading hierarchy gaps
    hierarchy_gap_pages = [
        p["url"] for p in indexable
        if p.get("heading_hierarchy_gaps") and len(p.get("heading_hierarchy_gaps")) > 0
    ]
    if hierarchy_gap_pages:
        issues.append(_issue(
            "heading_hierarchy_gap", "low", hierarchy_gap_pages,
            how_to_fix="Ensure heading levels are sequential (H1→H2→H3, not H1→H3).",
            why_it_matters="Skipping heading levels hurts document outline and accessibility.",
        ))

    # Thin content
    thin = [p["url"] for p in indexable if (p.get("word_count") or 0) < 100]
    if thin:
        issues.append(_issue(
            "thin_content", "medium", thin,
            confidence=0.6,
            how_to_fix="Add more substantive content or consider consolidating thin pages.",
            why_it_matters="Thin content pages may be seen as low quality and rank poorly.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.8  Links: broken, orphans, depth
# ---------------------------------------------------------------------------

def check_links(pages: list[dict], links: list[dict]) -> list[dict]:
    issues = []

    # Build link graph
    page_urls = {p.get("url_normalized") or p["url"] for p in pages}
    inlinks: dict[str, int] = Counter()
    for link in links:
        if link.get("is_internal"):
            dest = link.get("dest_url_normalized") or link["dest_url"]
            inlinks[dest] += 1

    # Broken internal links
    broken = []
    status_map = {(p.get("url_normalized") or p["url"]): p.get("status_code") for p in pages}
    for link in links:
        if link.get("is_internal"):
            dest = link.get("dest_url_normalized") or link["dest_url"]
            status = status_map.get(dest)
            if status and status >= 400:
                broken.append(link["source_url"])
    broken = list(set(broken))
    if broken:
        issues.append(_issue(
            "broken_internal_link", "high", broken,
            how_to_fix="Fix or remove internal links pointing to 4xx/5xx pages.",
            why_it_matters="Broken internal links waste crawl budget and hurt user experience.",
        ))

    # Orphan pages (no inlinks from crawl)
    orphans = [
        p["url"] for p in pages
        if p.get("is_indexable", True)
        and (p.get("status_code") or 0) == 200
        and inlinks.get(p.get("url_normalized") or p["url"], 0) == 0
        and p.get("depth", 0) > 0  # exclude seed
    ]
    if orphans:
        issues.append(_issue(
            "orphan_page", "medium", orphans,
            how_to_fix="Add internal links to these pages from relevant content.",
            why_it_matters="Orphan pages are hard for search engines to discover and may not get indexed.",
        ))

    # High click depth
    deep = [p["url"] for p in pages if (p.get("depth") or 0) > 5 and p.get("is_indexable", True)]
    if deep:
        issues.append(_issue(
            "high_click_depth", "low", deep,
            detail={"threshold": 5},
            how_to_fix="Restructure navigation to reduce click depth for important pages.",
            why_it_matters="Pages buried deep in site structure get less crawl priority and link equity.",
        ))

    # Internal nofollow
    nofollow_internal = [
        p["url"] for p in pages
        if (p.get("internal_nofollow_count") or 0) > 0
    ]
    if nofollow_internal:
        issues.append(_issue(
            "internal_nofollow", "low", nofollow_internal,
            how_to_fix="Remove nofollow from internal links unless there's a specific reason.",
            why_it_matters="Internal nofollow prevents link equity flow within your site.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.9  Images
# ---------------------------------------------------------------------------

def check_images(pages: list[dict]) -> list[dict]:
    issues = []

    missing_alt = [p["url"] for p in pages if (p.get("img_missing_alt") or 0) > 0]
    if missing_alt:
        total_missing = sum(p.get("img_missing_alt", 0) for p in pages)
        issues.append(_issue(
            "img_missing_alt", "medium", missing_alt,
            detail={"total_images_missing_alt": total_missing},
            how_to_fix="Add descriptive alt attributes to all meaningful images.",
            why_it_matters="Alt text helps search engines understand images and improves accessibility.",
        ))

    lazy_broken = [p["url"] for p in pages if (p.get("img_lazy_broken") or 0) > 0]
    if lazy_broken:
        issues.append(_issue(
            "img_lazy_broken", "medium", lazy_broken,
            how_to_fix="Use native loading='lazy' or ensure lazy-load JS provides proper fallbacks.",
            why_it_matters="Broken lazy loading means search engines may not see your images.",
        ))

    # Images missing dimensions (CLS risk)
    missing_dims = [p["url"] for p in pages if (p.get("img_missing_dimensions") or 0) > 0]
    if missing_dims:
        total_missing_dims = sum(p.get("img_missing_dimensions", 0) for p in pages)
        issues.append(_issue(
            "img_missing_dimensions", "medium", missing_dims,
            detail={"total_images_missing_dimensions": total_missing_dims},
            how_to_fix="Add explicit width and height attributes to all <img> tags.",
            why_it_matters="Missing image dimensions cause layout shifts (CLS), hurting Core Web Vitals.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.10  Structured data
# ---------------------------------------------------------------------------

def check_structured_data(pages: list[dict]) -> list[dict]:
    """Check structured data validity and completeness."""
    issues = []

    invalid = []
    for p in pages:
        for sd in (p.get("structured_data") or []):
            if isinstance(sd, dict) and sd.get("_error"):
                invalid.append(p["url"])
                break
    if invalid:
        issues.append(_issue(
            "structured_data_invalid", "medium", invalid,
            how_to_fix="Fix JSON-LD syntax errors in your structured data markup.",
            why_it_matters="Invalid structured data won't generate rich results in search.",
        ))

    # Missing structured data on content pages
    indexable_content = [
        p for p in pages
        if p.get("is_indexable", True)
        and (p.get("status_code") or 0) == 200
        and (p.get("word_count") or 0) > 200
    ]
    missing_sd = [
        p["url"] for p in indexable_content
        if not p.get("structured_data") or len(p.get("structured_data", [])) == 0
    ]
    if missing_sd:
        issues.append(_issue(
            "structured_data_missing", "low", missing_sd,
            confidence=0.5,
            how_to_fix="Add JSON-LD structured data (Article, Product, FAQPage, etc.) to content pages.",
            why_it_matters="Structured data enables rich results in search and improves click-through rates.",
        ))

    # Required property checks per @type
    REQUIRED_PROPERTIES = {
        "Product": ["name", "image", "offers"],
        "Article": ["headline", "author", "datePublished"],
        "NewsArticle": ["headline", "author", "datePublished"],
        "BlogPosting": ["headline", "author", "datePublished"],
        "FAQPage": ["mainEntity"],
        "LocalBusiness": ["name", "address"],
        "Organization": ["name", "url"],
        "BreadcrumbList": ["itemListElement"],
    }

    missing_fields_pages = []
    for p in pages:
        for sd in (p.get("structured_data") or []):
            if not isinstance(sd, dict) or sd.get("_error"):
                continue
            sd_type = sd.get("@type", "")
            if isinstance(sd_type, list):
                sd_type = sd_type[0] if sd_type else ""
            required = REQUIRED_PROPERTIES.get(sd_type, [])
            missing = [f for f in required if f not in sd]
            if missing:
                missing_fields_pages.append(p["url"])
                break

    if missing_fields_pages:
        issues.append(_issue(
            "structured_data_missing_fields", "medium", list(set(missing_fields_pages)),
            how_to_fix="Add required properties to your structured data (e.g., Product needs name, image, offers).",
            why_it_matters="Incomplete structured data may not qualify for rich results.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.11  JS render parity
# ---------------------------------------------------------------------------

def check_js_parity(pages: list[dict]) -> list[dict]:
    issues = []

    rendered_pages = [p for p in pages if p.get("was_rendered")]

    # Console errors
    js_errors = [p["url"] for p in rendered_pages if p.get("console_errors")]
    if js_errors:
        issues.append(_issue(
            "js_render_errors", "medium", js_errors,
            how_to_fix="Fix JavaScript console errors that may prevent proper rendering.",
            why_it_matters="JS errors can prevent content from rendering for search engines.",
        ))

    # Content parity (raw vs rendered)
    content_parity = []
    link_parity = []
    for p in rendered_pages:
        diff = p.get("raw_vs_rendered_diff") or {}
        if diff.get("h1_changed") or diff.get("title_changed"):
            content_parity.append(p["url"])
        if diff.get("links_added", 0) > 10:
            link_parity.append(p["url"])

    if content_parity:
        issues.append(_issue(
            "js_content_parity", "high", content_parity,
            how_to_fix="Ensure critical content (title, H1) is in the initial HTML, not JS-dependent.",
            why_it_matters="Content that requires JS to render may not be indexed correctly.",
        ))

    if link_parity:
        issues.append(_issue(
            "js_link_parity", "medium", link_parity,
            how_to_fix="Include important internal links in the HTML source, not just via JavaScript.",
            why_it_matters="JS-only links may not be discovered during crawling.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.12  Performance
# ---------------------------------------------------------------------------

def check_performance(pages: list[dict]) -> list[dict]:
    issues = []

    very_slow = [p["url"] for p in pages if (p.get("ttfb_ms") or 0) > 2000]
    slow = [p["url"] for p in pages if 600 < (p.get("ttfb_ms") or 0) <= 2000]

    if very_slow:
        issues.append(_issue(
            "slow_ttfb", "high", very_slow,
            detail={"threshold_ms": 2000},
            how_to_fix="Optimize server response time (caching, DB queries, CDN).",
            why_it_matters="Very slow TTFB severely impacts crawl efficiency and Core Web Vitals.",
        ))
    if slow:
        issues.append(_issue(
            "slow_ttfb", "medium", slow,
            detail={"threshold_ms": 600},
            how_to_fix="Optimize server response time to under 600ms (caching, CDN, edge computing).",
            why_it_matters="Slow TTFB impacts crawl efficiency and Core Web Vitals.",
        ))

    large = [p["url"] for p in pages if (p.get("response_bytes") or 0) > 3_000_000]
    if large:
        issues.append(_issue(
            "large_page", "low", large,
            detail={"threshold_bytes": 3_000_000},
            how_to_fix="Reduce page size by optimizing images, minifying code, and removing unused resources.",
            why_it_matters="Large pages are slower to download and render.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.6  Hreflang & internationalization
# ---------------------------------------------------------------------------

def check_hreflang(pages: list[dict]) -> list[dict]:
    """Check hreflang implementation: self-refs, reciprocity, canonical conflicts."""
    issues = []

    # Build hreflang map: url → set of (lang, href) pairs
    hreflang_map: dict[str, list[dict]] = {}
    for p in pages:
        tags = p.get("hreflang_tags") or []
        if tags:
            hreflang_map[p["url"]] = tags

    if not hreflang_map:
        return issues

    # Check self-referencing
    missing_self = []
    for url, tags in hreflang_map.items():
        hrefs = {t.get("href", "").rstrip("/") for t in tags}
        if url.rstrip("/") not in hrefs:
            missing_self.append(url)
    if missing_self:
        issues.append(_issue(
            "hreflang_missing_self", "medium", missing_self,
            how_to_fix="Add a self-referencing hreflang tag on every page that has hreflang annotations.",
            why_it_matters="Missing self-referencing hreflang can cause search engines to ignore the entire set.",
        ))

    # Check reciprocal return tags
    # Build reverse map: target_url → set of pages pointing to it
    target_sources: dict[str, set[str]] = defaultdict(set)
    for url, tags in hreflang_map.items():
        for t in tags:
            href = t.get("href", "").rstrip("/")
            if href:
                target_sources[href].add(url.rstrip("/"))

    missing_return = []
    for url, tags in hreflang_map.items():
        for t in tags:
            target = t.get("href", "").rstrip("/")
            if target and target != url.rstrip("/"):
                # Check if target points back to us
                target_tags = hreflang_map.get(target) or hreflang_map.get(target + "/") or []
                target_hrefs = {tt.get("href", "").rstrip("/") for tt in target_tags}
                if url.rstrip("/") not in target_hrefs:
                    missing_return.append(url)
                    break  # one missing return per page is enough
    if missing_return:
        issues.append(_issue(
            "hreflang_missing_return", "high", missing_return,
            how_to_fix="Ensure every hreflang target page has a reciprocal hreflang tag pointing back.",
            why_it_matters="Without reciprocal tags, search engines may ignore the hreflang relationship.",
        ))

    # Hreflang–canonical conflict
    hreflang_canonical_conflict = []
    for p in pages:
        tags = p.get("hreflang_tags") or []
        canonical = (p.get("canonical_url") or "").rstrip("/")
        url = p["url"].rstrip("/")
        if tags and canonical and canonical != url:
            hreflang_canonical_conflict.append(p["url"])
    if hreflang_canonical_conflict:
        issues.append(_issue(
            "hreflang_canonical_conflict", "high", hreflang_canonical_conflict,
            how_to_fix="Align canonical and hreflang — a page's canonical should point to itself if it has hreflang tags.",
            why_it_matters="Canonical pointing elsewhere contradicts hreflang and may cause wrong page to be indexed.",
        ))

    # Invalid language codes
    VALID_LANG_CODES = {
        "aa", "ab", "af", "ak", "am", "an", "ar", "as", "av", "ay", "az",
        "ba", "be", "bg", "bh", "bi", "bm", "bn", "bo", "br", "bs",
        "ca", "ce", "ch", "co", "cr", "cs", "cu", "cv", "cy",
        "da", "de", "dv", "dz",
        "ee", "el", "en", "eo", "es", "et", "eu",
        "fa", "ff", "fi", "fj", "fo", "fr", "fy",
        "ga", "gd", "gl", "gn", "gu", "gv",
        "ha", "he", "hi", "ho", "hr", "ht", "hu", "hy", "hz",
        "ia", "id", "ie", "ig", "ii", "ik", "io", "is", "it", "iu",
        "ja", "jv",
        "ka", "kg", "ki", "kj", "kk", "kl", "km", "kn", "ko", "kr", "ks", "ku", "kv", "kw", "ky",
        "la", "lb", "lg", "li", "ln", "lo", "lt", "lu", "lv",
        "mg", "mh", "mi", "mk", "ml", "mn", "mr", "ms", "mt", "my",
        "na", "nb", "nd", "ne", "ng", "nl", "nn", "no", "nr", "nv", "ny",
        "oc", "oj", "om", "or", "os",
        "pa", "pi", "pl", "ps", "pt",
        "qu",
        "rm", "rn", "ro", "ru", "rw",
        "sa", "sc", "sd", "se", "sg", "si", "sk", "sl", "sm", "sn", "so", "sq", "sr", "ss", "st", "su", "sv", "sw",
        "ta", "te", "tg", "th", "ti", "tk", "tl", "tn", "to", "tr", "ts", "tt", "tw", "ty",
        "ug", "uk", "ur", "uz",
        "ve", "vi", "vo",
        "wa", "wo",
        "xh",
        "yi", "yo",
        "za", "zh", "zu",
    }

    invalid_lang_pages = []
    for url, tags in hreflang_map.items():
        for t in tags:
            lang = t.get("lang", "").strip().lower()
            if lang == "x-default":
                continue
            # Extract base language from region code (e.g., "en-us" → "en")
            base_lang = lang.split("-")[0]
            if base_lang not in VALID_LANG_CODES:
                invalid_lang_pages.append(url)
                break
    if invalid_lang_pages:
        issues.append(_issue(
            "hreflang_invalid_lang", "medium", invalid_lang_pages,
            how_to_fix="Use valid ISO 639-1 language codes in hreflang tags (e.g., 'en', 'de', 'fr').",
            why_it_matters="Invalid language codes cause search engines to ignore hreflang annotations.",
        ))

    # x-default missing
    has_x_default = set()
    for url, tags in hreflang_map.items():
        for t in tags:
            if t.get("lang", "").strip().lower() == "x-default":
                has_x_default.add(url)
                break
    missing_x_default = [url for url in hreflang_map if url not in has_x_default]
    if missing_x_default:
        issues.append(_issue(
            "hreflang_x_default_missing", "low", missing_x_default,
            how_to_fix="Add an x-default hreflang tag to specify the default/fallback page.",
            why_it_matters="x-default helps search engines serve the right page when no language matches.",
        ))

    # Hreflang pointing to non-200 pages
    page_status = {p["url"].rstrip("/"): p.get("status_code", 200) for p in pages}
    hreflang_error_pages = []
    for url, tags in hreflang_map.items():
        for t in tags:
            href = t.get("href", "").rstrip("/")
            status = page_status.get(href)
            if status and status != 200:
                hreflang_error_pages.append(url)
                break
    if hreflang_error_pages:
        issues.append(_issue(
            "hreflang_to_error", "high", hreflang_error_pages,
            how_to_fix="Update hreflang tags to point only to pages that return 200 status.",
            why_it_matters="Hreflang tags pointing to error pages waste crawl budget and confuse search engines.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.4  Duplicate content clustering
# ---------------------------------------------------------------------------

def _simhash(text: str, n: int = 3) -> int:
    """Compute simhash of text using character n-grams."""
    if not text or len(text) < n:
        return 0
    text = text.lower()
    tokens = [text[i:i+n] for i in range(len(text) - n + 1)]
    v = [0] * 64
    for token in tokens:
        h = hash(token) & ((1 << 64) - 1)
        for i in range(64):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1
    return sum(1 << i for i in range(64) if v[i] > 0)


def _hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two integers."""
    return bin(a ^ b).count('1')


def check_duplicate_content(pages: list[dict]) -> list[dict]:
    """Detect duplicate content via content hash and title+H1 fingerprints."""
    issues = []
    indexable = [p for p in pages if p.get("is_indexable", True) and (p.get("status_code") or 0) == 200]

    # Exact duplicate content (same content hash)
    hash_groups: dict[str, list[str]] = defaultdict(list)
    for p in indexable:
        h = p.get("content_hash")
        if h:
            hash_groups[h].append(p["url"])

    dup_content = [urls for urls in hash_groups.values() if len(urls) > 1]
    if dup_content:
        all_dup_urls = [url for group in dup_content for url in group]
        issues.append(_issue(
            "duplicate_content", "high", all_dup_urls,
            detail={"duplicate_clusters": len(dup_content), "total_duplicate_pages": len(all_dup_urls)},
            how_to_fix="Consolidate duplicate pages with canonical tags, redirects, or by differentiating content.",
            why_it_matters="Duplicate content dilutes ranking signals and wastes crawl budget.",
        ))

    # Near-duplicate detection via simhash
    simhash_pages = []
    for p in indexable:
        text = p.get("main_text") or p.get("content_hash", "")
        if (p.get("word_count") or 0) > 50:
            simhash_pages.append((p["url"], _simhash(text), p.get("content_hash")))

    near_dup_urls = set()
    # Compare pairs (O(n^2) but limited to indexable pages, typically <10k)
    for i in range(len(simhash_pages)):
        for j in range(i + 1, min(i + 200, len(simhash_pages))):  # Limit comparisons
            url_a, hash_a, chash_a = simhash_pages[i]
            url_b, hash_b, chash_b = simhash_pages[j]
            if chash_a == chash_b:
                continue  # Already caught as exact duplicate
            if hash_a and hash_b and _hamming_distance(hash_a, hash_b) < 6:  # ~90% similar
                near_dup_urls.add(url_a)
                near_dup_urls.add(url_b)

    if near_dup_urls:
        issues.append(_issue(
            "near_duplicate_content", "medium", list(near_dup_urls),
            confidence=0.7,
            how_to_fix="Consolidate near-duplicate pages with canonical tags or differentiate their content.",
            why_it_matters="Near-duplicate content competes with itself in search results.",
        ))

    # Near-duplicate via title+H1 signature (catches template pages)
    sig_groups: dict[str, list[str]] = defaultdict(list)
    for p in indexable:
        title = (p.get("title") or "").strip().lower()
        h1 = (p.get("h1_text") or "").strip().lower()
        if title or h1:
            sig = f"{title}|||{h1}"
            sig_groups[sig].append(p["url"])

    # Filter to groups that share content hash AND title+H1 (stronger signal)
    # but also check groups where title+H1 match but content differs (template spam)
    template_spam = []
    for sig, urls in sig_groups.items():
        if len(urls) > 3:  # same title+H1 on 4+ pages = suspicious
            # Check if they have different content
            hashes = {p.get("content_hash") for p in indexable if p["url"] in urls}
            if len(hashes) > 1:  # different content but same title+H1
                template_spam.extend(urls)

    if template_spam:
        issues.append(_issue(
            "duplicate_title", "medium", list(set(template_spam)),
            confidence=0.6,
            how_to_fix="Write unique titles and H1 headings for each page instead of using templates.",
            why_it_matters="Identical title+heading patterns across pages look like thin/template content to search engines.",
        ))

    # Parameter duplicate detection (URLs that differ only by query params)
    from urllib.parse import urlparse, parse_qs
    path_groups: dict[str, list[str]] = defaultdict(list)
    for p in indexable:
        parsed = urlparse(p["url"])
        path_key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if parsed.query:
            path_groups[path_key].append(p["url"])

    param_dups = []
    for path_key, urls in path_groups.items():
        if len(urls) > 1:
            # Check if content is similar
            hashes = set()
            for url in urls:
                for p in indexable:
                    if p["url"] == url and p.get("content_hash"):
                        hashes.add(p["content_hash"])
            if len(hashes) <= 1:  # same content, different params
                param_dups.extend(urls)

    if param_dups:
        issues.append(_issue(
            "param_duplicate", "medium", param_dups,
            how_to_fix="Use canonical tags or parameter handling rules to consolidate parameterized URLs.",
            why_it_matters="Multiple URLs with different parameters but identical content waste crawl budget.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.12  Mobile-first parity
# ---------------------------------------------------------------------------

def check_mobile_parity(pages: list[dict]) -> list[dict]:
    """Check mobile vs desktop content/link parity."""
    issues = []

    mobile_checked = [p for p in pages if p.get("mobile_checked")]
    if not mobile_checked:
        return issues

    content_parity = []
    link_parity = []

    for p in mobile_checked:
        diff = p.get("mobile_diff") or {}

        # Content significantly shorter on mobile
        desktop_words = diff.get("desktop_word_count", 0)
        mobile_words = diff.get("mobile_word_count", 0)
        if desktop_words > 100 and mobile_words < desktop_words * 0.7:
            content_parity.append(p["url"])

        # Fewer internal links on mobile
        desktop_links = diff.get("desktop_internal_links", 0)
        mobile_links = diff.get("mobile_internal_links", 0)
        if desktop_links > 10 and mobile_links < desktop_links * 0.5:
            link_parity.append(p["url"])

    if content_parity:
        issues.append(_issue(
            "mobile_content_parity", "high", content_parity,
            how_to_fix="Ensure mobile version contains the same essential content as desktop.",
            why_it_matters="Google uses mobile-first indexing — missing mobile content won't be indexed.",
        ))

    if link_parity:
        issues.append(_issue(
            "mobile_link_parity", "medium", link_parity,
            how_to_fix="Ensure mobile navigation provides access to the same internal pages as desktop.",
            why_it_matters="Missing internal links on mobile reduces discoverability for mobile-first crawling.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.13.5  Content Quality (keyword stuffing, stale content)
# ---------------------------------------------------------------------------

def check_content_quality(pages: list[dict]) -> list[dict]:
    """Check content quality: keyword stuffing, stale content."""
    issues = []
    indexable = [p for p in pages if p.get("is_indexable", True) and (p.get("status_code") or 0) == 200]

    # Keyword stuffing heuristic
    stuffed = []
    for p in indexable:
        text = (p.get("main_text") or "").lower()
        words = text.split()
        if len(words) < 100:
            continue
        word_counts = Counter(words)
        total = len(words)
        for word, count in word_counts.most_common(3):
            if len(word) > 3 and count / total > 0.05:  # >5% density
                stuffed.append(p["url"])
                break

    if stuffed:
        issues.append(_issue(
            "keyword_stuffing", "medium", stuffed,
            confidence=0.5,
            how_to_fix="Reduce keyword density by using synonyms and natural language.",
            why_it_matters="Keyword stuffing can trigger Google's spam filters and hurt rankings.",
        ))

    # Stale content: check structured data for old dates
    from datetime import datetime, timezone
    stale = []
    now = datetime.now(timezone.utc)
    for p in indexable:
        for sd in (p.get("structured_data") or []):
            if not isinstance(sd, dict):
                continue
            date_str = sd.get("dateModified") or sd.get("datePublished")
            if date_str:
                try:
                    # Handle common date formats
                    for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"]:
                        try:
                            dt = datetime.strptime(date_str[:19], fmt[:min(len(fmt), 19)])
                            if (now - dt.replace(tzinfo=timezone.utc)).days > 365:
                                stale.append(p["url"])
                            break
                        except (ValueError, TypeError):
                            continue
                except Exception:
                    pass

    if stale:
        issues.append(_issue(
            "stale_content", "low", list(set(stale)),
            confidence=0.5,
            how_to_fix="Review and update content that hasn't been modified in over 12 months.",
            why_it_matters="Fresh content tends to rank better, especially for time-sensitive topics.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.12.5  Performance hints (Core Web Vitals)
# ---------------------------------------------------------------------------

def check_performance_hints(pages: list[dict]) -> list[dict]:
    """Check for performance issues affecting Core Web Vitals."""
    issues = []

    # CLS risk: images missing dimensions
    cls_risk_pages = [
        p["url"] for p in pages
        if (p.get("img_missing_dimensions") or 0) > 0
        and (p.get("status_code") or 0) == 200
    ]
    if cls_risk_pages:
        issues.append(_issue(
            "cls_risk", "medium", cls_risk_pages,
            how_to_fix="Add explicit width and height to all images to prevent layout shifts.",
            why_it_matters="Cumulative Layout Shift (CLS) is a Core Web Vital that affects rankings.",
        ))

    # Render-blocking resources (heuristic: large pages likely have render-blocking resources)
    # This is a simplified check — ideally would parse <head> for blocking scripts/styles
    render_blocking = [
        p["url"] for p in pages
        if (p.get("response_bytes") or 0) > 100000
        and (p.get("status_code") or 0) == 200
    ]
    if render_blocking:
        issues.append(_issue(
            "render_blocking_resource", "medium", render_blocking,
            confidence=0.4,
            how_to_fix="Add async/defer to scripts and use media queries for non-critical CSS.",
            why_it_matters="Render-blocking resources delay First Contentful Paint.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.13  Meta tags (OG, Twitter Card, viewport, charset)
# ---------------------------------------------------------------------------

def check_meta_tags(pages: list[dict]) -> list[dict]:
    """Check OG tags, Twitter Card, viewport, and charset."""
    issues = []
    indexable = [p for p in pages if p.get("is_indexable", True) and (p.get("status_code") or 0) == 200]

    # Missing OG tags
    og_missing = [p["url"] for p in indexable if not p.get("og_title")]
    if og_missing:
        issues.append(_issue(
            "og_tags_missing", "low", og_missing,
            how_to_fix="Add Open Graph meta tags (og:title, og:description, og:image) for rich social sharing.",
            why_it_matters="OG tags control how your pages appear when shared on social media.",
        ))

    # Missing Twitter Card
    tc_missing = [p["url"] for p in indexable if not p.get("twitter_card")]
    if tc_missing:
        issues.append(_issue(
            "twitter_card_missing", "low", tc_missing,
            how_to_fix="Add Twitter Card meta tags for optimized Twitter/X sharing.",
            why_it_matters="Twitter Cards improve the visual presentation of shared links.",
        ))

    # Missing viewport
    vp_missing = [p["url"] for p in pages if (p.get("status_code") or 0) == 200 and not p.get("has_viewport")]
    if vp_missing:
        issues.append(_issue(
            "viewport_missing", "medium", vp_missing,
            how_to_fix="Add <meta name='viewport' content='width=device-width, initial-scale=1'> to all pages.",
            why_it_matters="Missing viewport meta tag causes poor mobile rendering and fails mobile-friendly test.",
        ))

    # Missing charset
    charset_missing = [p["url"] for p in pages if (p.get("status_code") or 0) == 200 and not p.get("charset_declared")]
    if charset_missing:
        issues.append(_issue(
            "charset_missing", "low", charset_missing,
            how_to_fix="Add <meta charset='utf-8'> to all HTML pages.",
            why_it_matters="Missing charset declaration may cause character encoding issues.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.14  Security
# ---------------------------------------------------------------------------

def check_security(pages: list[dict]) -> list[dict]:
    """Check for security issues affecting SEO."""
    issues = []

    # Mixed content (HTTPS pages loading HTTP resources)
    mixed = [
        p["url"] for p in pages
        if p.get("url", "").startswith("https://")
        and p.get("has_mixed_content")
        and (p.get("status_code") or 0) == 200
    ]
    if mixed:
        issues.append(_issue(
            "mixed_content", "high", mixed,
            how_to_fix="Update all resource URLs to use HTTPS instead of HTTP.",
            why_it_matters="Mixed content triggers browser warnings and may prevent pages from being indexed securely.",
        ))

    # Missing HSTS header
    missing_hsts = []
    for p in pages:
        if not p.get("url", "").startswith("https://"):
            continue
        if (p.get("status_code") or 0) != 200:
            continue
        headers = p.get("headers") or {}
        has_hsts = any(k.lower() == "strict-transport-security" for k in headers)
        if not has_hsts:
            missing_hsts.append(p["url"])
    if missing_hsts:
        issues.append(_issue(
            "missing_hsts", "medium", missing_hsts,
            how_to_fix="Add Strict-Transport-Security header with appropriate max-age.",
            why_it_matters="HSTS ensures browsers always use HTTPS, improving security and SEO trust signals.",
        ))

    # Insecure form actions
    insecure_forms = []
    for p in pages:
        if not p.get("url", "").startswith("https://"):
            continue
        for action in (p.get("form_actions") or []):
            if action.startswith("http://"):
                insecure_forms.append(p["url"])
                break
    if insecure_forms:
        issues.append(_issue(
            "insecure_form_action", "high", insecure_forms,
            how_to_fix="Update form actions to use HTTPS URLs.",
            why_it_matters="Forms submitting to HTTP endpoints expose user data and trigger browser warnings.",
        ))

    return issues


# ---------------------------------------------------------------------------
# 2D.15  Accessibility
# ---------------------------------------------------------------------------

def check_accessibility(pages: list[dict]) -> list[dict]:
    """Check basic accessibility issues that also affect SEO."""
    issues = []
    html_pages = [p for p in pages if (p.get("status_code") or 0) == 200]

    # Missing HTML lang
    missing_lang = [p["url"] for p in html_pages if not p.get("html_lang")]
    if missing_lang:
        issues.append(_issue(
            "missing_html_lang", "medium", missing_lang,
            how_to_fix="Add a lang attribute to the <html> tag (e.g., <html lang='en'>).",
            why_it_matters="The lang attribute helps search engines and screen readers identify the page language.",
        ))

    # Empty link text
    empty_links = [p["url"] for p in html_pages if (p.get("empty_link_count") or 0) > 0]
    if empty_links:
        total_empty = sum(p.get("empty_link_count", 0) for p in html_pages)
        issues.append(_issue(
            "empty_link_text", "medium", empty_links,
            detail={"total_empty_links": total_empty},
            how_to_fix="Add descriptive text or aria-label to all links.",
            why_it_matters="Empty links are unusable for screen readers and provide no anchor text for SEO.",
        ))

    # Missing form labels
    missing_labels = [p["url"] for p in html_pages if (p.get("form_inputs_without_label") or 0) > 0]
    if missing_labels:
        issues.append(_issue(
            "missing_form_label", "low", missing_labels,
            how_to_fix="Associate a <label> with each form input using the 'for' attribute.",
            why_it_matters="Missing labels make forms inaccessible and can hurt user experience signals.",
        ))

    # Missing skip navigation
    missing_skip = [p["url"] for p in html_pages if not p.get("has_skip_nav")]
    if missing_skip:
        issues.append(_issue(
            "missing_skip_nav", "low", missing_skip,
            how_to_fix="Add a 'Skip to main content' link as the first focusable element on each page.",
            why_it_matters="Skip navigation improves keyboard accessibility and is an accessibility best practice.",
        ))

    return issues


# ---------------------------------------------------------------------------
# Master runner
# ---------------------------------------------------------------------------

def run_all_checks(
    pages: list[dict],
    links: list[dict],
    robots_data: dict,
    sitemap_urls_count: int,
    noindex_patterns: list[str] | None = None,
) -> list[dict]:
    """
    Run all audit checks and return a combined list of issues.
    """
    all_issues = []

    checks = [
        ("robots", lambda: check_robots_txt(robots_data, pages)),
        ("sitemap", lambda: check_sitemap_health(sitemap_urls_count, pages)),
        ("status_codes", lambda: check_status_codes(pages)),
        ("redirects", lambda: check_redirects(pages)),
        ("canonicals", lambda: check_canonicals(pages)),
        ("indexing", lambda: check_indexing_policy(pages, noindex_patterns)),
        ("on_page", lambda: check_on_page(pages)),
        ("links", lambda: check_links(pages, links)),
        ("images", lambda: check_images(pages)),
        ("structured_data", lambda: check_structured_data(pages)),
        ("js_parity", lambda: check_js_parity(pages)),
        ("performance", lambda: check_performance(pages)),
        ("hreflang", lambda: check_hreflang(pages)),
        ("duplicate_content", lambda: check_duplicate_content(pages)),
        ("mobile_parity", lambda: check_mobile_parity(pages)),
        ("meta_tags", lambda: check_meta_tags(pages)),
        ("content_quality", lambda: check_content_quality(pages)),
        ("performance_hints", lambda: check_performance_hints(pages)),
        ("security", lambda: check_security(pages)),
        ("accessibility", lambda: check_accessibility(pages)),
    ]

    for name, check_fn in checks:
        try:
            issues = check_fn()
            all_issues.extend(issues)
            logger.info("Audit [%s]: %d issues found", name, len(issues))
        except Exception as e:
            logger.error("Audit [%s] failed: %s", name, e)

    logger.info("Total audit issues: %d", len(all_issues))
    return all_issues
