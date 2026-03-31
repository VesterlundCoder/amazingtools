"""
Background task runner: bridges API endpoints to the crawl orchestrator.

Uses asyncio background tasks (FastAPI BackgroundTasks) for simplicity.
Can be swapped for Celery/ARQ/Redis-based queue later.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timezone

from app.crawler.orchestrator import CrawlOrchestrator
from app.audit.rules import run_all_checks
from app.export.excel_report import generate_excel_report
from app.db.persistence import CrawlPersistence
from app.db.models import RunStatus

logger = logging.getLogger(__name__)

# Track active runs to prevent duplicate triggers
_active_runs: dict[str, asyncio.Task] = {}


async def run_crawl_task(
    site_id: str,
    run_id: str,
    config: dict,
    session_factory,
):
    """
    Execute a full crawl + audit + persist pipeline as a background task.

    Args:
        site_id: UUID of the site
        run_id: UUID of the CrawlRun
        config: Site config dict from CrawlPersistence.load_site_config()
        session_factory: Async session factory callable
    """
    logger.info("Background crawl task started: site=%s run=%s", site_id, run_id)

    async with session_factory() as session:
        persistence = CrawlPersistence(session)

        try:
            # Mark as running
            await persistence.mark_running(run_id)
            await session.commit()

            # Build orchestrator from config
            orchestrator = CrawlOrchestrator(
                site_id=config["site_id"],
                domain=config["domain"],
                start_urls=config.get("start_urls", [f"https://{config['domain']}/"]),
                max_pages=config.get("max_pages", 10000),
                max_depth=config.get("max_depth", 50),
                max_concurrency=config.get("max_concurrency", 5),
                rate_limit_rps=config.get("rate_limit_rps", 2.0),
                render_mode=config.get("render_mode", "targeted"),
                render_cap=config.get("render_cap", 500),
                user_agent=config.get("user_agent", "SEOCrawler/1.0"),
                respect_robots=config.get("respect_robots", True),
                drop_tracking_params=config.get("drop_tracking_params", True),
                param_allowlist=config.get("param_allowlist"),
                param_denylist=config.get("param_denylist"),
                include_subdomains=config.get("include_subdomains", False),
                subdomain_allowlist=config.get("subdomain_allowlist"),
                mobile_parity_check=config.get("mobile_parity_check", False),
            )

            # Run crawl
            crawl_result = await orchestrator.run()

            # Run audit
            issues = run_all_checks(
                pages=crawl_result.get("pages", []),
                links=crawl_result.get("links", []),
                robots_data=crawl_result.get("robots", {}),
                sitemap_urls_count=crawl_result.get("sitemap_urls_count", 0),
                noindex_patterns=config.get("noindex_patterns"),
            )

            # Persist results to database
            await persistence.save_results(run_id, crawl_result, issues)
            await persistence.finalize_run(run_id, status=RunStatus.completed)
            await session.commit()

            stats = crawl_result.get("stats", {})
            logger.info(
                "Crawl task completed: site=%s run=%s pages=%d issues=%d",
                site_id, run_id,
                stats.get("pages_crawled", 0),
                len(issues),
            )

        except asyncio.CancelledError:
            logger.warning("Crawl task cancelled: site=%s run=%s", site_id, run_id)
            await persistence.finalize_run(run_id, status=RunStatus.partial, error_message="Cancelled")
            await session.commit()

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e}"
            logger.error("Crawl task failed: site=%s run=%s error=%s", site_id, run_id, error_msg)
            logger.debug(traceback.format_exc())
            try:
                await persistence.finalize_run(
                    run_id, status=RunStatus.failed, error_message=error_msg
                )
                await session.commit()
            except Exception:
                logger.error("Failed to update run status after error")

        finally:
            _active_runs.pop(run_id, None)


def is_run_active(run_id: str) -> bool:
    """Check if a run is currently executing."""
    task = _active_runs.get(run_id)
    return task is not None and not task.done()


def cancel_run(run_id: str) -> bool:
    """Cancel an active run. Returns True if cancelled."""
    task = _active_runs.get(run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def get_active_run_ids() -> list[str]:
    """List all currently active run IDs."""
    return [rid for rid, task in _active_runs.items() if not task.done()]


async def schedule_crawl(
    site_id: str,
    run_id: str,
    config: dict,
    session_factory,
) -> str:
    """
    Schedule a crawl as an asyncio background task.
    Returns the run_id.
    """
    if run_id in _active_runs:
        task = _active_runs[run_id]
        if not task.done():
            raise RuntimeError(f"Run {run_id} is already active")

    task = asyncio.create_task(
        run_crawl_task(site_id, run_id, config, session_factory)
    )
    _active_runs[run_id] = task
    logger.info("Scheduled crawl: run=%s site=%s", run_id, site_id)
    return run_id
