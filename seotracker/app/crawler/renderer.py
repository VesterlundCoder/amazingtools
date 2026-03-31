"""
Playwright-based JS render pool with raw-vs-rendered diff.

Responsibilities:
  - Pool of Playwright browser contexts (desktop + mobile)
  - Render pages that need JS (CSR/SPA detection)
  - Compare raw HTML vs rendered DOM for critical SEO elements
  - Capture console errors, DOM mutations, timing
  - Configurable timeouts and resource blocking
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Mobile viewport matching Googlebot smartphone
MOBILE_VIEWPORT = {"width": 412, "height": 915}
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36"
)

DESKTOP_VIEWPORT = {"width": 1920, "height": 1080}
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# Resource types to block during render (speeds things up)
BLOCKED_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


@dataclass
class RenderResult:
    """Result of rendering a page with Playwright."""
    url: str
    rendered_html: str = ""
    profile: str = "desktop"  # "desktop" or "mobile"
    render_time_ms: float = 0.0
    dom_content_loaded_ms: float = 0.0

    # Console output
    console_errors: list[str] = field(default_factory=list)
    console_warnings: list[str] = field(default_factory=list)

    # DOM signals
    dom_mutations_count: int = 0

    # Extracted from rendered DOM
    rendered_title: Optional[str] = None
    rendered_h1: Optional[str] = None
    rendered_h1_count: int = 0
    rendered_canonical: Optional[str] = None
    rendered_meta_robots: Optional[str] = None
    rendered_internal_links_count: int = 0
    rendered_word_count: int = 0

    # Diff vs raw HTML
    parity_diff: dict = field(default_factory=dict)

    error: Optional[str] = None


@dataclass
class ParityDiff:
    """Diff between raw HTML and rendered DOM."""
    title_changed: bool = False
    h1_changed: bool = False
    h1_count_raw: int = 0
    h1_count_rendered: int = 0
    canonical_changed: bool = False
    meta_robots_changed: bool = False
    internal_links_raw: int = 0
    internal_links_rendered: int = 0
    links_added: int = 0
    word_count_raw: int = 0
    word_count_rendered: int = 0
    has_significant_diff: bool = False


class PlaywrightPool:
    """
    Pool of Playwright browser contexts for JS rendering.

    Usage:
        pool = PlaywrightPool(max_workers=3, timeout_ms=30000)
        await pool.start()

        result = await pool.render("https://example.com/page", profile="desktop")

        await pool.stop()
    """

    def __init__(
        self,
        max_workers: int = 3,
        timeout_ms: int = 30000,
        block_resources: bool = True,
    ):
        self._max_workers = max_workers
        self._timeout_ms = timeout_ms
        self._block_resources = block_resources
        self._semaphore = asyncio.Semaphore(max_workers)
        self._playwright = None
        self._browser = None
        self._started = False

    async def start(self):
        """Start the Playwright browser."""
        if self._started:
            return

        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            self._started = True
            logger.info("Playwright pool started with %d max workers", self._max_workers)
        except Exception as e:
            logger.error("Failed to start Playwright: %s", e)
            raise

    async def stop(self):
        """Stop the Playwright browser."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._started = False
        logger.info("Playwright pool stopped")

    async def render(
        self,
        url: str,
        profile: str = "desktop",
        wait_until: str = "networkidle",
    ) -> RenderResult:
        """
        Render a URL with Playwright.

        Args:
            url: URL to render
            profile: "desktop" or "mobile"
            wait_until: Playwright wait condition
        """
        if not self._started:
            await self.start()

        result = RenderResult(url=url, profile=profile)

        async with self._semaphore:
            context = None
            page = None
            try:
                # Create context with appropriate viewport/UA
                if profile == "mobile":
                    viewport = MOBILE_VIEWPORT
                    ua = MOBILE_UA
                else:
                    viewport = DESKTOP_VIEWPORT
                    ua = DESKTOP_UA

                context = await self._browser.new_context(
                    viewport=viewport,
                    user_agent=ua,
                    java_script_enabled=True,
                )
                page = await context.new_page()

                # Block heavy resources if configured
                if self._block_resources:
                    await page.route(
                        "**/*",
                        lambda route: (
                            route.abort()
                            if route.request.resource_type in BLOCKED_RESOURCE_TYPES
                            else route.continue_()
                        ),
                    )

                # Capture console messages
                console_errors = []
                console_warnings = []

                def on_console(msg):
                    if msg.type == "error":
                        console_errors.append(msg.text[:500])
                    elif msg.type == "warning":
                        console_warnings.append(msg.text[:500])

                page.on("console", on_console)

                # Navigate and render
                t_start = time.monotonic()

                response = await page.goto(
                    url,
                    wait_until=wait_until,
                    timeout=self._timeout_ms,
                )

                # Wait a bit more for dynamic content
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass  # timeout is ok, page might have long-polling

                t_end = time.monotonic()
                result.render_time_ms = (t_end - t_start) * 1000

                # Get rendered HTML
                result.rendered_html = await page.content()

                # Extract key SEO elements from rendered DOM via JS
                seo_data = await page.evaluate("""() => {
                    const title = document.title || '';
                    const h1s = Array.from(document.querySelectorAll('h1')).map(h => h.textContent.trim());
                    const canonical = document.querySelector('link[rel="canonical"]');
                    const metaRobots = document.querySelector('meta[name="robots"]');
                    const internalLinks = Array.from(document.querySelectorAll('a[href]'))
                        .filter(a => {
                            try {
                                const url = new URL(a.href, location.origin);
                                return url.origin === location.origin;
                            } catch { return false; }
                        });
                    const bodyText = document.body ? document.body.innerText : '';
                    
                    return {
                        title: title,
                        h1s: h1s.slice(0, 10),
                        h1_count: h1s.length,
                        canonical: canonical ? canonical.href : null,
                        meta_robots: metaRobots ? metaRobots.content : null,
                        internal_links_count: internalLinks.length,
                        word_count: bodyText.split(/\\s+/).filter(w => w.length > 0).length,
                    };
                }""")

                result.rendered_title = seo_data.get("title")
                result.rendered_h1 = seo_data["h1s"][0] if seo_data.get("h1s") else None
                result.rendered_h1_count = seo_data.get("h1_count", 0)
                result.rendered_canonical = seo_data.get("canonical")
                result.rendered_meta_robots = seo_data.get("meta_robots")
                result.rendered_internal_links_count = seo_data.get("internal_links_count", 0)
                result.rendered_word_count = seo_data.get("word_count", 0)

                result.console_errors = console_errors
                result.console_warnings = console_warnings

            except Exception as e:
                result.error = str(e)
                logger.warning("Render error for %s: %s", url, e)
            finally:
                if page:
                    await page.close()
                if context:
                    await context.close()

        return result

    @staticmethod
    def compute_parity_diff(
        raw_title: str | None,
        raw_h1: str | None,
        raw_h1_count: int,
        raw_canonical: str | None,
        raw_meta_robots: str | None,
        raw_internal_links: int,
        raw_word_count: int,
        render_result: RenderResult,
    ) -> dict:
        """
        Compare raw HTML extraction vs rendered DOM extraction.
        Returns a dict describing the differences.
        """
        diff = {}

        diff["title_changed"] = (
            (raw_title or "").strip() != (render_result.rendered_title or "").strip()
        )
        diff["h1_changed"] = (
            (raw_h1 or "").strip() != (render_result.rendered_h1 or "").strip()
        )
        diff["h1_count_raw"] = raw_h1_count
        diff["h1_count_rendered"] = render_result.rendered_h1_count
        diff["canonical_changed"] = (
            (raw_canonical or "").strip() != (render_result.rendered_canonical or "").strip()
        )
        diff["meta_robots_changed"] = (
            (raw_meta_robots or "").strip() != (render_result.rendered_meta_robots or "").strip()
        )
        diff["internal_links_raw"] = raw_internal_links
        diff["internal_links_rendered"] = render_result.rendered_internal_links_count
        diff["links_added"] = max(0, render_result.rendered_internal_links_count - raw_internal_links)
        diff["word_count_raw"] = raw_word_count
        diff["word_count_rendered"] = render_result.rendered_word_count

        # Determine if the diff is significant
        diff["has_significant_diff"] = any([
            diff["title_changed"],
            diff["h1_changed"],
            diff["canonical_changed"],
            diff["meta_robots_changed"],
            diff["links_added"] > 5,
            abs(render_result.rendered_word_count - raw_word_count) > 100,
        ])

        return diff

    @staticmethod
    def should_render(html: str, extraction=None) -> bool:
        """
        Heuristic: decide whether a page needs JS rendering.

        Returns True if:
          - HTML is very short (likely SPA shell)
          - No H1 found in raw HTML
          - Very few internal links in raw HTML
          - Heavy JS indicators present
        """
        if not html:
            return True

        # Very short HTML body → likely SPA
        if len(html) < 2000:
            return True

        html_lower = html.lower()

        # Common SPA frameworks
        spa_indicators = [
            "id=\"root\"", "id=\"app\"", "id=\"__next\"", "id=\"__nuxt\"",
            "ng-app", "data-reactroot", "data-v-",
        ]
        if any(indicator in html_lower for indicator in spa_indicators):
            # Check if body seems empty
            import re
            body_match = re.search(r"<body[^>]*>(.*?)</body>", html_lower, re.DOTALL)
            if body_match:
                body_content = body_match.group(1).strip()
                # Remove script/style tags
                body_clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body_content, flags=re.DOTALL)
                body_clean = re.sub(r"<[^>]+>", "", body_clean).strip()
                if len(body_clean) < 100:
                    return True

        # Detect noscript with meaningful fallback (strong JS signal)
        if "<noscript>" in html_lower:
            import re as _re
            noscript_match = _re.search(r"<noscript[^>]*>(.*?)</noscript>", html_lower, _re.DOTALL)
            if noscript_match and len(noscript_match.group(1).strip()) > 100:
                return True

        # If extraction provided, check for missing critical elements
        if extraction:
            if not extraction.h1_text and not extraction.title:
                return True
            if extraction.internal_links_count == 0:
                return True
            if extraction.word_count < 50:
                return True
            # Check if SPA framework detected
            if hasattr(extraction, 'spa_framework') and extraction.spa_framework:
                return True

        return False
