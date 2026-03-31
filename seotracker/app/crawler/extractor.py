"""
HTML content extractor for SEO-relevant data.

Responsibilities:
  - Extract title, meta description, meta robots, canonical, hreflang
  - Extract heading outline (H1–H6)
  - Extract internal/external links with anchor text and context
  - Extract images with alt text, lazy-load patterns
  - Extract JSON-LD structured data
  - Compute content hash and word count
  - Classify link context (nav, footer, content, sidebar)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Comment, Tag

logger = logging.getLogger(__name__)


@dataclass
class ExtractedLink:
    """A link extracted from a page."""
    href: str
    href_resolved: str  # absolute URL
    anchor_text: str = ""
    is_internal: bool = True
    is_follow: bool = True
    context: str = "content"  # "nav", "footer", "sidebar", "header", "content"
    rel: str = ""


@dataclass
class ExtractedImage:
    """An image extracted from a page."""
    src: str
    alt: Optional[str] = None
    has_alt: bool = False
    loading: Optional[str] = None  # "lazy", "eager", None
    is_lazy_broken: bool = False
    width: Optional[str] = None
    height: Optional[str] = None
    has_srcset: bool = False


@dataclass
class HeadingItem:
    """A heading in the document outline."""
    level: int  # 1–6
    text: str


@dataclass
class StructuredDataBlock:
    """A JSON-LD block from the page."""
    raw: dict
    sd_type: str = ""
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)


@dataclass
class PageExtraction:
    """All SEO-relevant data extracted from a single page."""
    url: str

    # Meta
    title: Optional[str] = None
    title_length: int = 0
    meta_description: Optional[str] = None
    meta_description_length: int = 0
    meta_robots: Optional[str] = None  # raw content of <meta name="robots">
    canonical_url: Optional[str] = None
    canonical_count: int = 0  # detect multiple canonicals
    hreflang_tags: list[dict] = field(default_factory=list)

    # Headings
    h1_text: Optional[str] = None
    h1_count: int = 0
    heading_outline: list[dict] = field(default_factory=list)

    # Content
    word_count: int = 0
    content_hash: str = ""
    main_text: str = ""

    # Links
    links: list[ExtractedLink] = field(default_factory=list)
    internal_links_count: int = 0
    external_links_count: int = 0
    internal_nofollow_count: int = 0

    # Images
    images: list[ExtractedImage] = field(default_factory=list)
    img_count: int = 0
    img_missing_alt: int = 0
    img_lazy_broken: int = 0

    # Structured data
    structured_data: list[dict] = field(default_factory=list)
    structured_data_types: list[str] = field(default_factory=list)

    # Indexability signals
    is_noindex: bool = False
    is_nofollow: bool = False
    robots_directives: list[str] = field(default_factory=list)

    # OG tags
    og_title: Optional[str] = None
    og_description: Optional[str] = None
    og_image: Optional[str] = None
    og_url: Optional[str] = None

    # Twitter Card
    twitter_card: Optional[str] = None
    twitter_title: Optional[str] = None
    twitter_description: Optional[str] = None

    # Viewport & charset
    has_viewport: bool = False
    viewport_content: Optional[str] = None
    charset_declared: Optional[str] = None

    # Pagination
    has_pagination: bool = False
    pagination_next: Optional[str] = None
    pagination_prev: Optional[str] = None

    # Heading hierarchy
    heading_hierarchy_gaps: list[dict] = field(default_factory=list)

    # HTML lang
    html_lang: Optional[str] = None

    # SPA / JS signals
    spa_framework: Optional[str] = None
    has_noscript_fallback: bool = False
    lazy_load_indicators: int = 0

    # Security-related extraction
    has_mixed_content: bool = False
    form_actions: list[str] = field(default_factory=list)

    # Accessibility-related extraction
    empty_link_count: int = 0
    form_inputs_without_label: int = 0
    has_skip_nav: bool = False

    # Image dimensions
    img_missing_dimensions: int = 0


# Navigation/footer landmark selectors
NAV_SELECTORS = ["nav", "[role=navigation]", ".nav", ".navbar", ".menu", ".navigation"]
FOOTER_SELECTORS = ["footer", "[role=contentinfo]", ".footer", "#footer"]
SIDEBAR_SELECTORS = ["aside", "[role=complementary]", ".sidebar", "#sidebar"]
HEADER_SELECTORS = ["header", "[role=banner]", ".header", "#header"]


class HTMLExtractor:
    """
    Extract SEO-relevant data from HTML content.

    Usage:
        extractor = HTMLExtractor(base_url="https://example.com/page")
        result = extractor.extract(html_string)
    """

    def __init__(self, base_url: str, is_internal_fn=None):
        self._base_url = base_url
        self._is_internal = is_internal_fn or (lambda url: True)

    def extract(self, html: str) -> PageExtraction:
        """Extract all SEO data from HTML string."""
        result = PageExtraction(url=self._base_url)

        if not html or not html.strip():
            return result

        soup = BeautifulSoup(html, "lxml")

        self._extract_title(soup, result)
        self._extract_meta(soup, result)
        self._extract_canonical(soup, result)
        self._extract_hreflang(soup, result)
        self._extract_headings(soup, result)
        self._extract_content(soup, result)
        self._extract_links(soup, result)
        self._extract_images(soup, result)
        self._extract_structured_data(soup, result)
        self._extract_robots_directives(soup, result)
        self._extract_og_tags(soup, result)
        self._extract_twitter_card(soup, result)
        self._extract_viewport(soup, result)
        self._extract_charset(soup, result)
        self._extract_pagination(soup, result)
        self._extract_html_lang(soup, result)
        self._extract_spa_signals(soup, result)
        self._extract_noscript(soup, result)
        self._extract_security_signals(soup, result)
        self._extract_accessibility_signals(soup, result)

        return result

    def _extract_title(self, soup: BeautifulSoup, result: PageExtraction):
        title_tag = soup.find("title")
        if title_tag:
            result.title = title_tag.get_text(strip=True)
            result.title_length = len(result.title) if result.title else 0

    def _extract_meta(self, soup: BeautifulSoup, result: PageExtraction):
        # Meta description
        desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        if desc_tag and desc_tag.get("content"):
            result.meta_description = desc_tag["content"].strip()
            result.meta_description_length = len(result.meta_description)

        # Meta robots
        robots_tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        if robots_tag and robots_tag.get("content"):
            result.meta_robots = robots_tag["content"].strip()

    def _extract_canonical(self, soup: BeautifulSoup, result: PageExtraction):
        canonical_tags = soup.find_all("link", attrs={"rel": "canonical"})
        result.canonical_count = len(canonical_tags)
        if canonical_tags:
            href = canonical_tags[0].get("href", "").strip()
            if href:
                result.canonical_url = urljoin(self._base_url, href)

    def _extract_hreflang(self, soup: BeautifulSoup, result: PageExtraction):
        hreflang_tags = soup.find_all("link", attrs={"rel": "alternate", "hreflang": True})
        for tag in hreflang_tags:
            lang = tag.get("hreflang", "").strip()
            href = tag.get("href", "").strip()
            if lang and href:
                result.hreflang_tags.append({
                    "lang": lang,
                    "href": urljoin(self._base_url, href),
                })

    def _extract_headings(self, soup: BeautifulSoup, result: PageExtraction):
        h1s = soup.find_all("h1")
        result.h1_count = len(h1s)
        if h1s:
            result.h1_text = h1s[0].get_text(strip=True)

        outline = []
        for level in range(1, 7):
            for tag in soup.find_all(f"h{level}"):
                text = tag.get_text(strip=True)
                if text:
                    outline.append({"level": level, "text": text[:200]})
        result.heading_outline = outline

        # Detect hierarchy gaps
        if outline:
            levels_in_order = [h["level"] for h in outline]
            gaps = []
            for i in range(1, len(levels_in_order)):
                prev_level = levels_in_order[i - 1]
                curr_level = levels_in_order[i]
                if curr_level > prev_level + 1:
                    gaps.append({
                        "from_level": prev_level,
                        "to_level": curr_level,
                        "skipped": list(range(prev_level + 1, curr_level)),
                    })
            result.heading_hierarchy_gaps = gaps

    def _extract_content(self, soup: BeautifulSoup, result: PageExtraction):
        # Remove script, style, nav, footer for main content extraction
        content_soup = BeautifulSoup(str(soup), "lxml")
        for tag_name in ["script", "style", "nav", "footer", "header", "aside", "noscript"]:
            for tag in content_soup.find_all(tag_name):
                tag.decompose()
        for comment in content_soup.find_all(string=lambda t: isinstance(t, Comment)):
            comment.extract()

        text = content_soup.get_text(separator=" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()

        result.main_text = text[:50000]  # cap at 50k chars
        result.word_count = len(text.split()) if text else 0
        result.content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""

    def _extract_links(self, soup: BeautifulSoup, result: PageExtraction):
        # Pre-classify elements by context
        nav_elements = set()
        footer_elements = set()
        sidebar_elements = set()
        header_elements = set()

        for selector in NAV_SELECTORS:
            for el in soup.select(selector):
                nav_elements.add(id(el))
                for child in el.descendants:
                    if isinstance(child, Tag):
                        nav_elements.add(id(child))

        for selector in FOOTER_SELECTORS:
            for el in soup.select(selector):
                footer_elements.add(id(el))
                for child in el.descendants:
                    if isinstance(child, Tag):
                        footer_elements.add(id(child))

        for selector in SIDEBAR_SELECTORS:
            for el in soup.select(selector):
                sidebar_elements.add(id(el))
                for child in el.descendants:
                    if isinstance(child, Tag):
                        sidebar_elements.add(id(child))

        for selector in HEADER_SELECTORS:
            for el in soup.select(selector):
                header_elements.add(id(el))
                for child in el.descendants:
                    if isinstance(child, Tag):
                        header_elements.add(id(child))

        links = []
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            # Skip empty href after strip
            if not href:
                continue
            # Skip non-followable URLs
            if href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            # Handle protocol-relative URLs
            if href.startswith("//"):
                # Ensure urljoin handles protocol-relative URLs correctly
                # by prepending the scheme from the base URL
                parsed_base = urlparse(self._base_url)
                href = f"{parsed_base.scheme}:{href}"

            resolved = urljoin(self._base_url, href)
            anchor = a_tag.get_text(strip=True)[:500]
            rel = a_tag.get("rel", [])
            if isinstance(rel, list):
                rel = " ".join(rel)
            is_follow = "nofollow" not in rel.lower()
            is_internal = self._is_internal(resolved)

            # Classify context
            a_id = id(a_tag)
            if a_id in nav_elements:
                context = "nav"
            elif a_id in footer_elements:
                context = "footer"
            elif a_id in sidebar_elements:
                context = "sidebar"
            elif a_id in header_elements:
                context = "header"
            else:
                context = "content"

            links.append(ExtractedLink(
                href=href,
                href_resolved=resolved,
                anchor_text=anchor,
                is_internal=is_internal,
                is_follow=is_follow,
                context=context,
                rel=rel,
            ))

        result.links = links
        result.internal_links_count = sum(1 for l in links if l.is_internal)
        result.external_links_count = sum(1 for l in links if not l.is_internal)
        result.internal_nofollow_count = sum(1 for l in links if l.is_internal and not l.is_follow)

    def _extract_images(self, soup: BeautifulSoup, result: PageExtraction):
        images = []
        for img in soup.find_all("img"):
            src = img.get("src", "") or img.get("data-src", "") or ""
            alt = img.get("alt")
            loading = img.get("loading")

            has_alt = alt is not None and alt.strip() != ""

            # Detect broken lazy loading: has data-src but no src or empty src
            is_lazy_broken = False
            actual_src = img.get("src", "")
            data_src = img.get("data-src", "")
            if data_src and (not actual_src or actual_src.startswith("data:image")):
                # Could be lazy but check if noscript fallback exists
                noscript = img.find_parent("noscript")
                if not noscript:
                    is_lazy_broken = True

            width = img.get("width")
            height = img.get("height")
            has_srcset = bool(img.get("srcset"))

            images.append(ExtractedImage(
                src=src,
                alt=alt,
                has_alt=has_alt,
                loading=loading,
                is_lazy_broken=is_lazy_broken,
                width=width,
                height=height,
                has_srcset=has_srcset,
            ))

        result.images = images
        result.img_count = len(images)
        result.img_missing_alt = sum(1 for i in images if not i.has_alt)
        result.img_lazy_broken = sum(1 for i in images if i.is_lazy_broken)
        result.img_missing_dimensions = sum(
            1 for i in images if not i.width or not i.height
        )

    def _extract_structured_data(self, soup: BeautifulSoup, result: PageExtraction):
        sd_blocks = []
        sd_types = []

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            raw_text = script.string or script.get_text()
            if not raw_text or not raw_text.strip():
                continue
            try:
                data = json.loads(raw_text)
                sd_blocks.append(data)
                # Extract @type
                if isinstance(data, dict):
                    t = data.get("@type", "")
                    if isinstance(t, list):
                        sd_types.extend(t)
                    elif t:
                        sd_types.append(t)
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict):
                            t = item.get("@type", "")
                            if t:
                                sd_types.append(t if isinstance(t, str) else str(t))
            except json.JSONDecodeError:
                sd_blocks.append({"_error": "Invalid JSON-LD", "_raw": raw_text[:500]})

        result.structured_data = sd_blocks
        result.structured_data_types = list(set(sd_types))

    def _extract_robots_directives(self, soup: BeautifulSoup, result: PageExtraction):
        directives = []

        # <meta name="robots">
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"^(robots|googlebot)$", re.I)}):
            content = meta.get("content", "").strip()
            if content:
                directives.extend([d.strip().lower() for d in content.split(",")])

        result.robots_directives = list(set(directives))
        result.is_noindex = "noindex" in result.robots_directives
        result.is_nofollow = "nofollow" in result.robots_directives

    def _extract_og_tags(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract Open Graph meta tags."""
        og_map = {"og:title": "og_title", "og:description": "og_description",
                  "og:image": "og_image", "og:url": "og_url"}
        for prop, attr in og_map.items():
            tag = soup.find("meta", attrs={"property": prop})
            if tag and tag.get("content"):
                setattr(result, attr, tag["content"].strip())

    def _extract_twitter_card(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract Twitter Card meta tags."""
        tc_map = {"twitter:card": "twitter_card", "twitter:title": "twitter_title",
                  "twitter:description": "twitter_description"}
        for name, attr in tc_map.items():
            tag = soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                setattr(result, attr, tag["content"].strip())

    def _extract_viewport(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract viewport meta tag."""
        tag = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        if tag and tag.get("content"):
            result.has_viewport = True
            result.viewport_content = tag["content"].strip()

    def _extract_charset(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract charset declaration."""
        # <meta charset="utf-8">
        tag = soup.find("meta", attrs={"charset": True})
        if tag:
            result.charset_declared = tag["charset"].strip()
            return
        # <meta http-equiv="Content-Type" content="text/html; charset=utf-8">
        tag = soup.find("meta", attrs={"http-equiv": re.compile(r"^content-type$", re.I)})
        if tag and tag.get("content"):
            content = tag["content"]
            if "charset=" in content.lower():
                charset = content.lower().split("charset=")[-1].strip().rstrip(";")
                result.charset_declared = charset

    def _extract_pagination(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract rel=next/prev pagination links."""
        next_tag = soup.find("link", attrs={"rel": "next"})
        prev_tag = soup.find("link", attrs={"rel": "prev"})
        if next_tag and next_tag.get("href"):
            result.pagination_next = urljoin(self._base_url, next_tag["href"].strip())
            result.has_pagination = True
        if prev_tag and prev_tag.get("href"):
            result.pagination_prev = urljoin(self._base_url, prev_tag["href"].strip())
            result.has_pagination = True

    def _extract_html_lang(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract lang attribute from <html> tag."""
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            result.html_lang = html_tag["lang"].strip()

    def _extract_spa_signals(self, soup: BeautifulSoup, result: PageExtraction):
        """Detect SPA framework signals."""
        html_str = str(soup).lower()

        # React
        if soup.find(id="root") or soup.find(attrs={"data-reactroot": True}):
            result.spa_framework = "react"
        # Next.js
        elif soup.find(id="__next") or "__next_data__" in html_str:
            result.spa_framework = "next"
        # Vue
        elif soup.find(attrs={"data-v-": True}) or any(
            tag.get("data-v-") is not None for tag in soup.find_all(True, limit=50)
            if hasattr(tag, 'get')
        ):
            result.spa_framework = "vue"
        # Nuxt
        elif soup.find(id="__nuxt") or "__nuxt" in html_str:
            result.spa_framework = "nuxt"
        # Angular
        elif soup.find(attrs={"ng-app": True}) or soup.find("app-root") or "ng-version" in html_str:
            result.spa_framework = "angular"

    def _extract_noscript(self, soup: BeautifulSoup, result: PageExtraction):
        """Check for meaningful noscript fallback content."""
        noscript_tags = soup.find_all("noscript")
        for ns in noscript_tags:
            text = ns.get_text(strip=True)
            if len(text) > 50:
                result.has_noscript_fallback = True
                break

    def _extract_security_signals(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract security-related signals."""
        page_is_https = self._base_url.startswith("https://")

        if page_is_https:
            # Check for mixed content in images and scripts
            for tag_name, attr in [("img", "src"), ("script", "src"), ("link", "href")]:
                for tag in soup.find_all(tag_name):
                    val = tag.get(attr, "")
                    if val.startswith("http://"):
                        result.has_mixed_content = True
                        break
                if result.has_mixed_content:
                    break

        # Extract form actions
        for form in soup.find_all("form"):
            action = form.get("action", "").strip()
            if action:
                result.form_actions.append(action)

    def _extract_accessibility_signals(self, soup: BeautifulSoup, result: PageExtraction):
        """Extract accessibility-related signals."""
        # Count links with empty text
        empty_links = 0
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True)
            aria = a_tag.get("aria-label", "").strip()
            title = a_tag.get("title", "").strip()
            img_alt = ""
            img = a_tag.find("img")
            if img:
                img_alt = (img.get("alt") or "").strip()
            if not text and not aria and not title and not img_alt:
                empty_links += 1
        result.empty_link_count = empty_links

        # Count form inputs without labels
        inputs_without_label = 0
        label_fors = {label.get("for", "") for label in soup.find_all("label") if label.get("for")}
        for inp in soup.find_all(["input", "select", "textarea"]):
            inp_type = (inp.get("type") or "").lower()
            if inp_type in ("hidden", "submit", "button", "reset", "image"):
                continue
            inp_id = inp.get("id", "")
            aria_label = inp.get("aria-label", "").strip()
            aria_labelledby = inp.get("aria-labelledby", "").strip()
            # Check if wrapped in label
            parent_label = inp.find_parent("label")
            if aria_label or aria_labelledby or parent_label:
                continue
            if not inp_id or inp_id not in label_fors:
                inputs_without_label += 1
        result.form_inputs_without_label = inputs_without_label

        # Check for skip navigation
        first_links = soup.find_all("a", href=True, limit=3)
        for a in first_links:
            href = a.get("href", "")
            if href.startswith("#") and any(kw in href.lower() for kw in ["main", "content", "skip"]):
                result.has_skip_nav = True
                break
