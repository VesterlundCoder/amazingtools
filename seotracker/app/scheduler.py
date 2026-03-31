"""
Background scheduler for periodic crawl runs.

Uses APScheduler to trigger crawls based on each site's schedule_cron.
Runs as part of the FastAPI startup/shutdown lifecycle.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, and_

from app.db.session import async_session_factory
from app.db.models import Site, CrawlPolicy, CrawlRun, RunStatus
from app.db.persistence import CrawlPersistence
from app.crawler.tasks import schedule_crawl, is_run_active

logger = logging.getLogger(__name__)

# Simple interval-based scheduler (no APScheduler dependency needed)
_scheduler_task: asyncio.Task | None = None
CHECK_INTERVAL_SECONDS = 300  # Check every 5 minutes


async def _check_scheduled_crawls():
    """Check all sites for due crawls and trigger them."""
    async with async_session_factory() as session:
        try:
            # Get all active sites with crawl policies
            result = await session.execute(
                select(Site, CrawlPolicy)
                .join(CrawlPolicy, CrawlPolicy.site_id == Site.id, isouter=True)
                .where(Site.is_active == True)
            )
            rows = result.all()

            for site, policy in rows:
                if not policy or not policy.schedule_cron:
                    continue

                # Check if there's already an active run
                active_result = await session.execute(
                    select(CrawlRun).where(
                        and_(
                            CrawlRun.site_id == site.id,
                            CrawlRun.status.in_([RunStatus.pending, RunStatus.running]),
                        )
                    )
                )
                if active_result.scalar_one_or_none():
                    continue

                # Check if a crawl is due based on last completed run
                last_run_result = await session.execute(
                    select(CrawlRun)
                    .where(
                        and_(
                            CrawlRun.site_id == site.id,
                            CrawlRun.status == RunStatus.completed,
                        )
                    )
                    .order_by(CrawlRun.completed_at.desc())
                    .limit(1)
                )
                last_run = last_run_result.scalar_one_or_none()

                if _is_crawl_due(policy.schedule_cron, last_run):
                    logger.info("Scheduled crawl due for site %s (%s)", site.name, site.domain)

                    persistence = CrawlPersistence(session)
                    config = await persistence.load_site_config(str(site.id))
                    run_id = await persistence.create_run(str(site.id))
                    await session.commit()

                    await schedule_crawl(
                        site_id=str(site.id),
                        run_id=run_id,
                        config=config,
                        session_factory=async_session_factory,
                    )

        except Exception as e:
            logger.error("Scheduler check failed: %s", e)


def _is_crawl_due(cron_expr: str, last_run: CrawlRun | None) -> bool:
    """
    Simple schedule check based on cron expression.
    Supports basic patterns: daily, weekly, monthly.

    For full cron support, install croniter:
        from croniter import croniter
        cron = croniter(cron_expr, last_run.completed_at)
        next_run = cron.get_next(datetime)
        return datetime.now(timezone.utc) >= next_run
    """
    now = datetime.now(timezone.utc)

    if not last_run or not last_run.completed_at:
        return True  # Never run before — due now

    elapsed = now - last_run.completed_at.replace(tzinfo=timezone.utc)

    # Parse simple cron-like intervals
    # "0 2 * * *"  → daily at 2am
    # "0 2 * * 0"  → weekly on Sunday
    # "0 2 1 * *"  → monthly on 1st
    parts = cron_expr.strip().split()
    if len(parts) >= 5:
        day_of_month = parts[2]
        day_of_week = parts[4]

        if day_of_month != "*" and day_of_week == "*":
            # Monthly schedule
            return elapsed.days >= 28
        elif day_of_week != "*":
            # Weekly schedule
            return elapsed.days >= 7
        else:
            # Daily schedule
            return elapsed.days >= 1

    # Default: monthly
    return elapsed.days >= 30


async def _scheduler_loop():
    """Main scheduler loop."""
    logger.info("Scheduler started (checking every %ds)", CHECK_INTERVAL_SECONDS)
    while True:
        try:
            await _check_scheduled_crawls()
        except asyncio.CancelledError:
            logger.info("Scheduler shutting down")
            break
        except Exception as e:
            logger.error("Scheduler loop error: %s", e)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


def start_scheduler():
    """Start the background scheduler. Call from FastAPI startup."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_scheduler_loop())
        logger.info("Background scheduler started")


def stop_scheduler():
    """Stop the background scheduler. Call from FastAPI shutdown."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("Background scheduler stopped")
