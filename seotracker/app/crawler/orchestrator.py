"""
Crawl orchestrator: coordinates the full crawl pipeline for a single run.

Responsibilities:
  - Load site config and crawl policy
  - Fetch robots.txt and discover sitemaps
  - Seed the frontier
  - Coordinate async workers (fetch → extract → optional render)
  - Persist PageRecords, Links, and run metrics
  - Respect budgets (max_pages, max_depth, render_cap)
  - Handle graceful shutdown and partial runs
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.crawler.robots import RobotsCache
from app.crawler.sitemap import SitemapDiscovery
from app.crawler.url_normalizer import URLNormalizer
from app.crawler.frontier import CrawlFrontier
from app.crawler.fetcher import HTTPFetcher, FetchResult
from app.crawler.extractor import HTMLExtractor, PageExtraction
from app.crawler.renderer import PlaywrightPool, RenderResult

logger = logging.getLogger(__name__)


class CrawlOrchestrator:
    """
    Orchestrates the full crawl lifecycle for a single site run.

    Usage:
        orchestrator = CrawlOrchestrator(site_config)
        results = await orchestrator.run()
    """

    def __init__(
        self,
        site_id: str,
        domain: str,
        start_urls: list[str],
        # Crawl policy
        max_pages: int = 10000,
        max_depth: int = 50,
        max_concurrency: int = 5,
        rate_limit_rps: float = 2.0,
        render_mode: str = "targeted",  # "none", "targeted", "full"
        render_cap: int = 500,
        user_agent: str = "SEOCrawler/1.0",
        respect_robots: bool = True,
        # URL policy
        drop_tracking_params: bool = True,
        param_allowlist: list[str] | None = None,
        param_denylist: list[str] | None = None,
        include_subdomains: bool = False,
        subdomain_allowlist: list[str] | None = None,
        # Mobile parity
        mobile_parity_check: bool = False,
        mobile_parity_sample: int = 50,
        # Callbacks
        on_page_complete=None,
        on_progress=None,
    ):
        self.site_id = site_id
        self.domain = domain
        self.start_urls = start_urls
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.max_concurrency = max_concurrency
        self.rate_limit_rps = rate_limit_rps
        self.render_mode = render_mode
        self.render_cap = render_cap
        self.user_agent = user_agent
        self.respect_robots = respect_robots
        self.mobile_parity_check = mobile_parity_check
        self.mobile_parity_sample = mobile_parity_sample

        # URL normalizer
        self.normalizer = URLNormalizer(
            base_domain=domain,
            drop_tracking_params=drop_tracking_params,
            param_allowlist=param_allowlist,
            param_denylist=param_denylist,
            include_subdomains=include_subdomains,
            subdomain_allowlist=subdomain_allowlist,
        )

        # Frontier
        self.frontier = CrawlFrontier(
            normalizer=self.normalizer,
            max_pages=max_pages,
            max_depth=max_depth,
        )

        # Callbacks
        self._on_page_complete = on_page_complete
        self._on_progress = on_progress

        # State
        self._pages: list[dict] = []
        self._links: list[dict] = []
        self._render_count = 0
        self._errors: list[dict] = []
        self._robots_cache: Optional[RobotsCache] = None
        self._renderer: Optional[PlaywrightPool] = None
        self._cancelled = False
        self._run_start: Optional[float] = None

    async def run(self) -> dict:
        """
        Execute the full crawl pipeline.
        Returns a summary dict with pages, links, errors, and stats.
        """
        self._run_start = time.monotonic()
        logger.info("Starting crawl for %s (max_pages=%d, concurrency=%d)",
                     self.domain, self.max_pages, self.max_concurrency)

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=self.max_concurrency * 2,
                max_keepalive_connections=self.max_concurrency,
            ),
        ) as client:

            # 1. Robots.txt
            self._robots_cache = RobotsCache(client, user_agent=self.user_agent)
            robots_result = await self._robots_cache.get(self.start_urls[0])
            logger.info("Robots.txt: exists=%s, sitemaps=%d",
                         robots_result.exists, len(robots_result.sitemap_urls))

            # 2. Sitemap discovery
            sitemap_discovery = SitemapDiscovery(client)
            sitemap_urls = await sitemap_discovery.discover_and_parse(
                domain=self.start_urls[0],
                robots_sitemap_urls=robots_result.sitemap_urls,
            )
            logger.info("Sitemap discovery: %d URLs found", len(sitemap_urls))

            # 3. Seed frontier
            self.frontier.seed(self.start_urls)
            self.frontier.add_sitemap_urls(sitemap_urls)
            logger.info("Frontier seeded: %d URLs in queue", self.frontier.queue_size)

            # 4. Start renderer if needed
            if self.render_mode != "none":
                self._renderer = PlaywrightPool(max_workers=2)
                try:
                    await self._renderer.start()
                except Exception as e:
                    logger.warning("Playwright not available, disabling rendering: %s", e)
                    self._renderer = None
                    self.render_mode = "none"

            # 5. Crawl with async workers
            fetcher = HTTPFetcher(
                client=client,
                user_agent=self.user_agent,
                rps=self.rate_limit_rps,
            )

            semaphore = asyncio.Semaphore(self.max_concurrency)
            tasks: set[asyncio.Task] = set()

            while not self._cancelled:
                # Check budget
                if self.frontier.is_budget_exhausted():
                    logger.info("Page budget exhausted (%d pages)", self.frontier.total_done)
                    break

                if self.frontier.is_empty() and not tasks:
                    logger.info("Frontier empty and no pending tasks")
                    break

                # Fill worker slots
                while (
                    not self.frontier.is_empty()
                    and not self.frontier.is_budget_exhausted()
                    and len(tasks) < self.max_concurrency
                ):
                    item = self.frontier.pop()
                    if not item:
                        break

                    task = asyncio.create_task(
                        self._process_url(fetcher, item.url, item.url_normalized,
                                          item.depth, item.parent_url, semaphore)
                    )
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)

                # Wait for at least one task to complete
                if tasks:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in done:
                        if t.exception():
                            logger.error("Worker error: %s", t.exception())
                else:
                    await asyncio.sleep(0.1)

                # Progress callback
                if self._on_progress and self.frontier.total_done % 50 == 0:
                    self._on_progress(self.frontier.stats())

            # Wait for remaining tasks
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # 6. Mobile parity check (sampling)
            if self.mobile_parity_check and self._renderer:
                await self._run_mobile_parity()

            # 7. Stop renderer
            if self._renderer:
                await self._renderer.stop()

        elapsed = time.monotonic() - self._run_start
        stats = {
            "site_id": self.site_id,
            "domain": self.domain,
            "pages_crawled": len(self._pages),
            "pages_rendered": self._render_count,
            "links_found": len(self._links),
            "errors": len(self._errors),
            "elapsed_seconds": round(elapsed, 1),
            "pages_per_second": round(len(self._pages) / elapsed, 2) if elapsed > 0 else 0,
            "frontier_stats": self.frontier.stats(),
        }

        logger.info("Crawl complete: %d pages in %.1fs (%.1f pages/s)",
                     stats["pages_crawled"], elapsed, stats["pages_per_second"])

        return {
            "stats": stats,
            "pages": self._pages,
            "links": self._links,
            "errors": self._errors,
            "robots": {
                "exists": robots_result.exists,
                "status_code": robots_result.status_code,
                "sitemap_urls": robots_result.sitemap_urls,
                "parse_error": robots_result.parse_error,
            },
            "sitemap_urls_count": len(sitemap_urls),
        }

    async def _process_url(
        self,
        fetcher: HTTPFetcher,
        url: str,
        url_normalized: str,
        depth: int,
        parent_url: Optional[str],
        semaphore: asyncio.Semaphore,
    ):
        """Process a single URL: fetch → extract → optional render → store."""
        async with semaphore:
            try:
                # Robots check
                if self.respect_robots and self._robots_cache:
                    robots = await self._robots_cache.get(url)
                    if not robots.is_allowed(url, self.user_agent):
                        self.frontier.mark_done(url_normalized)
                        self._pages.append({
                            "url": url,
                            "url_normalized": url_normalized,
                            "depth": depth,
                            "robots_txt_allowed": False,
                            "is_indexable": False,
                            "indexability_reason": "robots_blocked",
                        })
                        return

                # Fetch
                fetch_result = await fetcher.fetch(url)
                self.frontier.mark_done(url_normalized)

                # Build page record
                page_record = self._build_page_record(
                    url, url_normalized, depth, parent_url, fetch_result
                )

                # Extract HTML content
                extraction = None
                content_type_lower = (fetch_result.content_type or "").lower()
                if fetch_result.html and ("html" in content_type_lower or "xhtml" in content_type_lower):
                    extractor = HTMLExtractor(
                        base_url=fetch_result.final_url or url,
                        is_internal_fn=self.normalizer.is_internal,
                    )
                    extraction = extractor.extract(fetch_result.html)
                    self._apply_extraction(page_record, extraction)

                    # Discover new links
                    new_urls = [
                        link.href_resolved for link in extraction.links
                        if link.is_internal and link.is_follow
                    ]
                    added = self.frontier.add_discovered(new_urls, depth=depth + 1, parent_url=url)

                    # Store link records
                    for link in extraction.links:
                        self._links.append({
                            "source_url": url,
                            "dest_url": link.href_resolved,
                            "dest_url_normalized": self.normalizer.normalize(link.href_resolved) or link.href_resolved,
                            "anchor_text": link.anchor_text,
                            "is_internal": link.is_internal,
                            "is_follow": link.is_follow,
                            "link_context": link.context,
                        })

                    logger.debug("Extracted %d links from %s (%d internal)",
                                 len(extraction.links), url, extraction.internal_links_count)

                # Optional JS render
                if (
                    self._renderer
                    and self.render_mode != "none"
                    and self._render_count < self.render_cap
                ):
                    should_render = (
                        self.render_mode == "full"
                        or (self.render_mode == "targeted"
                            and PlaywrightPool.should_render(fetch_result.html, extraction))
                    )
                    if should_render:
                        render_result = await self._renderer.render(
                            fetch_result.final_url or url,
                            profile="desktop",
                        )
                        self._render_count += 1
                        page_record["was_rendered"] = True
                        page_record["render_time_ms"] = render_result.render_time_ms
                        page_record["console_errors"] = render_result.console_errors

                        if extraction:
                            diff = PlaywrightPool.compute_parity_diff(
                                raw_title=extraction.title,
                                raw_h1=extraction.h1_text,
                                raw_h1_count=extraction.h1_count,
                                raw_canonical=extraction.canonical_url,
                                raw_meta_robots=extraction.meta_robots,
                                raw_internal_links=extraction.internal_links_count,
                                raw_word_count=extraction.word_count,
                                render_result=render_result,
                            )
                            page_record["raw_vs_rendered_diff"] = diff

                self._pages.append(page_record)

                # Callback
                if self._on_page_complete:
                    self._on_page_complete(page_record)

            except Exception as e:
                self.frontier.mark_done(url_normalized)
                self._errors.append({"url": url, "error": str(e)})
                logger.error("Error processing %s: %s", url, e)

    def _build_page_record(
        self,
        url: str,
        url_normalized: str,
        depth: int,
        parent_url: Optional[str],
        fetch: FetchResult,
    ) -> dict:
        """Build a page record dict from fetch result."""
        return {
            "url": url,
            "url_normalized": url_normalized,
            "final_url": fetch.final_url,
            "depth": depth,
            "parent_urls": [parent_url] if parent_url else [],
            "status_code": fetch.status_code,
            "content_type": fetch.content_type,
            "charset": fetch.charset,
            "response_bytes": fetch.response_bytes,
            "ttfb_ms": fetch.ttfb_ms,
            "download_time_ms": fetch.download_time_ms,
            "fetch_timestamp": datetime.now(timezone.utc).isoformat(),
            "redirect_chain": [
                {"url": hop.url, "status_code": hop.status_code}
                for hop in fetch.redirect_chain
            ],
            "redirect_hops": fetch.redirect_hops,
            "is_redirect_loop": fetch.is_redirect_loop,
            "headers": dict(fetch.headers),
            "cache_headers": fetch.cache_headers,
            "x_robots_tag": fetch.x_robots_tag,
            "hreflang_header": fetch.hreflang_header,
            "robots_txt_allowed": True,
            "error": fetch.error,
            # Defaults — overridden by extraction
            "is_indexable": True,
            "indexability_reason": None,
            "was_rendered": False,
            "render_time_ms": None,
            "console_errors": [],
            "raw_vs_rendered_diff": {},
        }

    def _apply_extraction(self, page_record: dict, ext: PageExtraction):
        """Apply HTML extraction results to the page record."""
        page_record["title"] = ext.title
        page_record["title_length"] = ext.title_length
        page_record["meta_description"] = ext.meta_description
        page_record["meta_description_length"] = ext.meta_description_length
        page_record["meta_robots"] = ext.meta_robots
        page_record["canonical_url"] = ext.canonical_url
        page_record["canonical_count"] = ext.canonical_count
        page_record["hreflang_tags"] = ext.hreflang_tags

        page_record["h1_text"] = ext.h1_text
        page_record["h1_count"] = ext.h1_count
        page_record["heading_outline"] = ext.heading_outline

        page_record["word_count"] = ext.word_count
        page_record["content_hash"] = ext.content_hash

        page_record["internal_links_count"] = ext.internal_links_count
        page_record["external_links_count"] = ext.external_links_count
        page_record["internal_nofollow_count"] = ext.internal_nofollow_count

        page_record["img_count"] = ext.img_count
        page_record["img_missing_alt"] = ext.img_missing_alt
        page_record["img_lazy_broken"] = ext.img_lazy_broken

        page_record["structured_data"] = ext.structured_data
        page_record["structured_data_types"] = ext.structured_data_types

        page_record["robots_directives"] = ext.robots_directives
        page_record["is_noindex"] = ext.is_noindex
        page_record["is_nofollow"] = ext.is_nofollow

        # OG tags
        page_record["og_title"] = ext.og_title
        page_record["og_description"] = ext.og_description
        page_record["og_image"] = ext.og_image
        page_record["og_url"] = ext.og_url

        # Twitter Card
        page_record["twitter_card"] = ext.twitter_card
        page_record["twitter_title"] = ext.twitter_title
        page_record["twitter_description"] = ext.twitter_description

        # Viewport & charset
        page_record["has_viewport"] = ext.has_viewport
        page_record["viewport_content"] = ext.viewport_content
        page_record["charset_declared"] = ext.charset_declared

        # Pagination
        page_record["has_pagination"] = ext.has_pagination
        page_record["pagination_next"] = ext.pagination_next
        page_record["pagination_prev"] = ext.pagination_prev

        # Headings enhanced
        page_record["heading_hierarchy_gaps"] = ext.heading_hierarchy_gaps

        # HTML lang
        page_record["html_lang"] = ext.html_lang

        # SPA signals
        page_record["spa_framework"] = ext.spa_framework
        page_record["has_noscript_fallback"] = ext.has_noscript_fallback

        # Image dimensions
        page_record["img_missing_dimensions"] = ext.img_missing_dimensions

        # Security signals
        page_record["has_mixed_content"] = ext.has_mixed_content
        page_record["form_actions"] = ext.form_actions

        # Accessibility signals
        page_record["empty_link_count"] = ext.empty_link_count
        page_record["form_inputs_without_label"] = ext.form_inputs_without_label
        page_record["has_skip_nav"] = ext.has_skip_nav

        # Determine indexability
        if ext.is_noindex:
            page_record["is_indexable"] = False
            page_record["indexability_reason"] = "noindex"
        elif not page_record.get("robots_txt_allowed", True):
            page_record["is_indexable"] = False
            page_record["indexability_reason"] = "robots_blocked"
        elif page_record.get("status_code", 200) >= 400:
            page_record["is_indexable"] = False
            page_record["indexability_reason"] = f"http_{page_record['status_code']}"
        elif ext.canonical_url and ext.canonical_url != page_record.get("url"):
            # Canonical points elsewhere — might not be indexable
            page_record["indexability_reason"] = "canonical_other"

    async def _run_mobile_parity(self):
        """
        Run mobile parity checks on a sample of crawled pages.
        Compares desktop render vs mobile render for content/link parity.
        """
        if not self._renderer:
            return

        # Select sample: top pages by inlinks, plus homepage
        indexable = [
            p for p in self._pages
            if p.get("is_indexable", True)
            and (p.get("status_code") or 0) == 200
            and "html" in (p.get("content_type") or "")
        ]
        sample = indexable[:self.mobile_parity_sample]
        if not sample:
            return

        logger.info("Mobile parity check: sampling %d pages", len(sample))

        for page in sample:
            url = page.get("final_url") or page["url"]
            try:
                mobile_result = await self._renderer.render(url, profile="mobile")
                if mobile_result.error:
                    continue

                page["mobile_checked"] = True
                page["mobile_diff"] = {
                    "desktop_word_count": page.get("word_count", 0),
                    "mobile_word_count": mobile_result.rendered_word_count,
                    "desktop_internal_links": page.get("internal_links_count", 0),
                    "mobile_internal_links": mobile_result.rendered_internal_links_count,
                    "desktop_title": page.get("title", ""),
                    "mobile_title": mobile_result.rendered_title or "",
                    "desktop_h1": page.get("h1_text", ""),
                    "mobile_h1": mobile_result.rendered_h1 or "",
                    "title_changed": (page.get("title") or "") != (mobile_result.rendered_title or ""),
                    "h1_changed": (page.get("h1_text") or "") != (mobile_result.rendered_h1 or ""),
                }
            except Exception as e:
                logger.warning("Mobile parity error for %s: %s", url, e)

        checked = sum(1 for p in self._pages if p.get("mobile_checked"))
        logger.info("Mobile parity complete: %d pages checked", checked)

    def cancel(self):
        """Request graceful cancellation of the crawl."""
        self._cancelled = True
        logger.info("Crawl cancellation requested for %s", self.domain)
