"""
Database persistence layer: saves crawl + audit results to Postgres.

Handles:
  - Creating/updating CrawlRun records
  - Bulk-inserting Page, Link, and Issue rows
  - Computing and storing RunMetric aggregates
  - Regression detection (comparing issues to previous run)
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    CrawlRun, Page, Link, Issue, RunMetric,
    RunStatus, IssueSeverity, IssueType,
    Site, CrawlPolicy,
)

logger = logging.getLogger(__name__)

# Max rows per bulk insert to avoid memory pressure
BULK_INSERT_BATCH = 500


class CrawlPersistence:
    """
    Persists crawl orchestrator output to the database.

    Usage:
        async with get_session() as session:
            persistence = CrawlPersistence(session)
            run_id = await persistence.create_run(site_id)
            await persistence.save_results(run_id, crawl_result, issues)
            await persistence.finalize_run(run_id)
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def load_site_config(self, site_id: str) -> dict:
        """Load site + crawl policy config for the orchestrator."""
        result = await self._session.execute(
            select(Site).where(Site.id == site_id)
        )
        site = result.scalar_one_or_none()
        if not site:
            raise ValueError(f"Site {site_id} not found")

        result = await self._session.execute(
            select(CrawlPolicy).where(CrawlPolicy.site_id == site_id)
        )
        policy = result.scalar_one_or_none()

        config = {
            "site_id": str(site.id),
            "domain": site.domain,
            "start_urls": site.start_urls or [f"https://{site.domain}/"],
            "tenant_id": str(site.tenant_id),
        }

        if policy:
            config.update({
                "max_pages": policy.max_pages or 10000,
                "max_depth": policy.max_depth or 50,
                "max_concurrency": policy.max_concurrency or 5,
                "rate_limit_rps": policy.rate_limit_rps or 2.0,
                "render_mode": policy.render_mode or "targeted",
                "render_cap": policy.render_cap or 500,
                "user_agent": policy.user_agent or "SEOCrawler/1.0",
                "respect_robots": policy.respect_robots if policy.respect_robots is not None else True,
                "mobile_parity_check": policy.mobile_parity_check or False,
                "include_subdomains": policy.include_subdomains or False,
                "subdomain_allowlist": policy.subdomain_allowlist or [],
                "drop_tracking_params": policy.drop_tracking_params if policy.drop_tracking_params is not None else True,
                "param_allowlist": policy.param_allowlist or [],
                "param_denylist": policy.param_denylist or [],
                "noindex_patterns": policy.noindex_patterns or [],
            })

        return config

    async def create_run(self, site_id: str) -> str:
        """Create a new CrawlRun in pending state. Returns run_id."""
        run = CrawlRun(
            id=uuid.uuid4(),
            site_id=site_id,
            status=RunStatus.pending,
        )
        self._session.add(run)
        await self._session.flush()
        logger.info("Created crawl run %s for site %s", run.id, site_id)
        return str(run.id)

    async def mark_running(self, run_id: str):
        """Mark a run as running."""
        result = await self._session.execute(
            select(CrawlRun).where(CrawlRun.id == run_id)
        )
        run = result.scalar_one()
        run.status = RunStatus.running
        run.started_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def save_results(
        self,
        run_id: str,
        crawl_result: dict,
        issues: list[dict],
    ):
        """
        Persist all crawl results: pages, links, issues, and metrics.

        Args:
            run_id: The CrawlRun UUID
            crawl_result: Output from CrawlOrchestrator.run()
            issues: Output from run_all_checks()
        """
        pages = crawl_result.get("pages", [])
        links = crawl_result.get("links", [])
        stats = crawl_result.get("stats", {})

        # Save pages in batches
        await self._save_pages(run_id, pages)
        logger.info("Saved %d pages for run %s", len(pages), run_id)

        # Save links in batches
        await self._save_links(run_id, links)
        logger.info("Saved %d links for run %s", len(links), run_id)

        # Save issues with regression detection
        prev_issue_types = await self._get_previous_issue_types(run_id)
        await self._save_issues(run_id, issues, prev_issue_types)
        logger.info("Saved %d issues for run %s", len(issues), run_id)

        # Save aggregate metrics
        await self._save_metrics(run_id, pages, links, issues, stats)

    async def finalize_run(
        self,
        run_id: str,
        status: RunStatus = RunStatus.completed,
        error_message: str | None = None,
    ):
        """Mark run as completed/failed and set final counts."""
        result = await self._session.execute(
            select(CrawlRun).where(CrawlRun.id == run_id)
        )
        run = result.scalar_one()

        run.status = status
        run.completed_at = datetime.now(timezone.utc)

        # Count pages
        page_count = await self._session.execute(
            select(func.count()).where(Page.crawl_run_id == run_id)
        )
        run.pages_crawled = page_count.scalar() or 0

        # Count indexable
        indexable_count = await self._session.execute(
            select(func.count()).where(
                and_(Page.crawl_run_id == run_id, Page.is_indexable == True)
            )
        )
        run.pages_indexable = indexable_count.scalar() or 0

        # Count rendered
        rendered_count = await self._session.execute(
            select(func.count()).where(
                and_(Page.crawl_run_id == run_id, Page.was_rendered == True)
            )
        )
        run.pages_rendered = rendered_count.scalar() or 0

        # Issue severity counts
        severity_counts = {}
        for sev in IssueSeverity:
            count_result = await self._session.execute(
                select(func.count()).where(
                    and_(Issue.crawl_run_id == run_id, Issue.severity == sev)
                )
            )
            severity_counts[sev.value] = count_result.scalar() or 0
        run.issue_counts = severity_counts

        if error_message:
            run.meta = {**(run.meta or {}), "error": error_message}

        await self._session.flush()
        logger.info("Finalized run %s: status=%s, pages=%d, indexable=%d",
                     run_id, status.value, run.pages_crawled, run.pages_indexable)

    # -----------------------------------------------------------------------
    # Internal: bulk insert helpers
    # -----------------------------------------------------------------------

    async def _save_pages(self, run_id: str, pages: list[dict]):
        """Bulk insert page records."""
        for i in range(0, len(pages), BULK_INSERT_BATCH):
            batch = pages[i:i + BULK_INSERT_BATCH]
            page_objects = []
            for p in batch:
                page_objects.append(Page(
                    crawl_run_id=run_id,
                    url=p.get("url", ""),
                    url_normalized=p.get("url_normalized", p.get("url", "")),
                    final_url=p.get("final_url"),
                    canonical_url=p.get("canonical_url"),
                    crawl_depth=p.get("depth", 0),
                    parent_urls=p.get("parent_urls"),
                    status_code=p.get("status_code"),
                    content_type=p.get("content_type"),
                    charset=p.get("charset"),
                    response_bytes=p.get("response_bytes"),
                    ttfb_ms=p.get("ttfb_ms"),
                    download_time_ms=p.get("download_time_ms"),
                    redirect_chain=p.get("redirect_chain"),
                    cache_headers=p.get("cache_headers"),
                    x_robots_tag=p.get("x_robots_tag"),
                    hreflang_header=p.get("hreflang_header"),
                    robots_txt_allowed=p.get("robots_txt_allowed", True),
                    meta_robots=p.get("meta_robots"),
                    is_indexable=p.get("is_indexable", True),
                    indexability_reason=p.get("indexability_reason"),
                    title=p.get("title"),
                    title_length=p.get("title_length"),
                    meta_description=p.get("meta_description"),
                    meta_description_length=p.get("meta_description_length"),
                    h1_text=p.get("h1_text"),
                    h1_count=p.get("h1_count", 0),
                    heading_outline=p.get("heading_outline"),
                    word_count=p.get("word_count", 0),
                    content_hash=p.get("content_hash"),
                    hreflang_tags=p.get("hreflang_tags"),
                    structured_data=p.get("structured_data"),
                    structured_data_types=p.get("structured_data_types"),
                    img_count=p.get("img_count", 0),
                    img_missing_alt=p.get("img_missing_alt", 0),
                    img_lazy_broken=p.get("img_lazy_broken", 0),
                    internal_links_count=p.get("internal_links_count", 0),
                    external_links_count=p.get("external_links_count", 0),
                    internal_nofollow_count=p.get("internal_nofollow_count", 0),
                    was_rendered=p.get("was_rendered", False),
                    render_time_ms=p.get("render_time_ms"),
                    console_errors=p.get("console_errors"),
                    raw_vs_rendered_diff=p.get("raw_vs_rendered_diff"),
                    mobile_checked=p.get("mobile_checked", False),
                    mobile_diff=p.get("mobile_diff"),
                ))
            self._session.add_all(page_objects)
            await self._session.flush()

    async def _save_links(self, run_id: str, links: list[dict]):
        """Bulk insert link records."""
        for i in range(0, len(links), BULK_INSERT_BATCH):
            batch = links[i:i + BULK_INSERT_BATCH]
            link_objects = []
            for lnk in batch:
                link_objects.append(Link(
                    crawl_run_id=run_id,
                    source_url=lnk.get("source_url", ""),
                    dest_url=lnk.get("dest_url", ""),
                    dest_url_normalized=lnk.get("dest_url_normalized", lnk.get("dest_url", "")),
                    anchor_text=lnk.get("anchor_text"),
                    is_internal=lnk.get("is_internal", True),
                    is_follow=lnk.get("is_follow", True),
                    link_context=lnk.get("link_context"),
                ))
            self._session.add_all(link_objects)
            await self._session.flush()

    async def _save_issues(
        self,
        run_id: str,
        issues: list[dict],
        prev_issue_types: set[str],
    ):
        """Bulk insert issue records with regression detection."""
        issue_objects = []
        for iss in issues:
            issue_type_str = iss.get("issue_type", "")

            # Try to match enum; skip if unknown type
            try:
                issue_type_enum = IssueType(issue_type_str)
            except ValueError:
                logger.warning("Unknown issue type: %s — skipping", issue_type_str)
                continue

            severity_str = iss.get("severity", "low")
            try:
                severity_enum = IssueSeverity(severity_str)
            except ValueError:
                severity_enum = IssueSeverity.low

            is_new = issue_type_str not in prev_issue_types
            is_regression = not is_new  # existed before, still exists

            issue_objects.append(Issue(
                crawl_run_id=run_id,
                issue_type=issue_type_enum,
                severity=severity_enum,
                confidence=iss.get("confidence", 1.0),
                affected_url=iss.get("affected_url"),
                affected_urls_count=iss.get("affected_urls_count", 0),
                affected_urls_sample=iss.get("affected_urls_sample"),
                detail=iss.get("detail"),
                how_to_fix=iss.get("how_to_fix"),
                why_it_matters=iss.get("why_it_matters"),
                is_new=is_new,
                is_regression=is_regression,
            ))

        if issue_objects:
            self._session.add_all(issue_objects)
            await self._session.flush()

    async def _get_previous_issue_types(self, run_id: str) -> set[str]:
        """Get issue types from the most recent completed run of the same site."""
        # Find site_id for this run
        run_result = await self._session.execute(
            select(CrawlRun.site_id).where(CrawlRun.id == run_id)
        )
        site_id = run_result.scalar_one_or_none()
        if not site_id:
            return set()

        # Find most recent completed run for this site (excluding current)
        prev_run_result = await self._session.execute(
            select(CrawlRun.id)
            .where(
                and_(
                    CrawlRun.site_id == site_id,
                    CrawlRun.status == RunStatus.completed,
                    CrawlRun.id != run_id,
                )
            )
            .order_by(CrawlRun.completed_at.desc())
            .limit(1)
        )
        prev_run_id = prev_run_result.scalar_one_or_none()
        if not prev_run_id:
            return set()

        # Get issue types from previous run
        prev_issues_result = await self._session.execute(
            select(Issue.issue_type).where(Issue.crawl_run_id == prev_run_id).distinct()
        )
        return {row[0].value for row in prev_issues_result.all()}

    async def _save_metrics(
        self,
        run_id: str,
        pages: list[dict],
        links: list[dict],
        issues: list[dict],
        stats: dict,
    ):
        """Compute and save aggregate RunMetric rows for trend charts."""
        metrics = []

        # Basic counts
        metrics.append(("pages_crawled", len(pages)))
        metrics.append(("pages_indexable", sum(1 for p in pages if p.get("is_indexable"))))
        metrics.append(("pages_noindex", sum(1 for p in pages if p.get("is_noindex"))))
        metrics.append(("pages_4xx", sum(1 for p in pages if 400 <= (p.get("status_code") or 0) < 500)))
        metrics.append(("pages_5xx", sum(1 for p in pages if (p.get("status_code") or 0) >= 500)))
        metrics.append(("pages_redirected", sum(1 for p in pages if (p.get("redirect_chain") or []))))
        metrics.append(("links_internal", sum(1 for l in links if l.get("is_internal"))))
        metrics.append(("links_external", sum(1 for l in links if not l.get("is_internal"))))

        # Issue counts by severity
        sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for iss in issues:
            sev = iss.get("severity", "low")
            sev_counts[sev] = sev_counts.get(sev, 0) + 1
        for sev, count in sev_counts.items():
            metrics.append((f"issues_{sev}", count))
        metrics.append(("issues_total", len(issues)))

        # Performance averages
        ttfbs = [p.get("ttfb_ms") for p in pages if p.get("ttfb_ms")]
        if ttfbs:
            metrics.append(("avg_ttfb_ms", sum(ttfbs) / len(ttfbs)))
            metrics.append(("p90_ttfb_ms", sorted(ttfbs)[int(len(ttfbs) * 0.9)]))

        sizes = [p.get("response_bytes") for p in pages if p.get("response_bytes")]
        if sizes:
            metrics.append(("avg_page_bytes", sum(sizes) / len(sizes)))

        word_counts = [p.get("word_count") for p in pages if p.get("word_count")]
        if word_counts:
            metrics.append(("avg_word_count", sum(word_counts) / len(word_counts)))

        # Content quality
        titles_present = sum(1 for p in pages if p.get("title"))
        metrics.append(("pages_with_title", titles_present))
        h1_present = sum(1 for p in pages if (p.get("h1_count") or 0) > 0)
        metrics.append(("pages_with_h1", h1_present))

        # Crawl performance
        metrics.append(("elapsed_seconds", stats.get("elapsed_seconds", 0)))
        metrics.append(("pages_per_second", stats.get("pages_per_second", 0)))

        # Save all metrics
        metric_objects = [
            RunMetric(
                crawl_run_id=run_id,
                metric_name=name,
                metric_value=float(value),
            )
            for name, value in metrics
        ]
        self._session.add_all(metric_objects)
        await self._session.flush()
        logger.info("Saved %d metrics for run %s", len(metric_objects), run_id)
