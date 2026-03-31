"""
Multi-tenant quota enforcement middleware.

Enforces per-tenant limits on:
  - Concurrent crawl runs
  - Monthly crawl budget (total pages)
  - API request rate limiting
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from sqlalchemy import select, func, and_

from app.db.session import async_session_factory
from app.db.models import CrawlRun, RunStatus, Site, Tenant

logger = logging.getLogger(__name__)

# Default quota limits (can be overridden per tenant in DB)
DEFAULT_QUOTAS = {
    "max_concurrent_runs": 2,
    "max_monthly_pages": 100_000,
    "max_sites": 20,
    "api_rate_limit_rpm": 120,  # requests per minute
}

# In-memory rate limiter (per-tenant)
_rate_buckets: dict[str, list[float]] = defaultdict(list)


class QuotaMiddleware(BaseHTTPMiddleware):
    """Enforce tenant quotas on API requests."""

    async def dispatch(self, request: Request, call_next):
        # Only enforce on API routes
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # Extract tenant_id from header or query param
        tenant_id = (
            request.headers.get("X-Tenant-ID")
            or request.query_params.get("tenant_id")
        )

        if not tenant_id:
            # No tenant context — allow through (public endpoints)
            return await call_next(request)

        # Rate limiting check
        if not self._check_rate_limit(tenant_id):
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again shortly.",
                    "tenant_id": tenant_id,
                },
            )

        # For run-triggering endpoints, check crawl quotas
        if request.method == "POST" and "/runs" in path and "/cancel" not in path:
            try:
                await self._check_crawl_quota(tenant_id)
            except HTTPException as e:
                return JSONResponse(
                    status_code=e.status_code,
                    content={"detail": e.detail},
                )

        response = await call_next(request)
        return response

    def _check_rate_limit(self, tenant_id: str) -> bool:
        """Simple sliding-window rate limiter."""
        now = time.time()
        window = 60.0  # 1 minute
        max_rpm = DEFAULT_QUOTAS["api_rate_limit_rpm"]

        # Clean old entries
        bucket = _rate_buckets[tenant_id]
        cutoff = now - window
        _rate_buckets[tenant_id] = [t for t in bucket if t > cutoff]

        if len(_rate_buckets[tenant_id]) >= max_rpm:
            logger.warning("Rate limit hit for tenant %s", tenant_id)
            return False

        _rate_buckets[tenant_id].append(now)
        return True

    async def _check_crawl_quota(self, tenant_id: str):
        """Check concurrent runs and monthly page budget."""
        async with async_session_factory() as session:
            # Check tenant exists
            tenant = await session.execute(
                select(Tenant).where(Tenant.id == tenant_id)
            )
            if not tenant.scalar_one_or_none():
                raise HTTPException(404, f"Tenant {tenant_id} not found")

            # Get tenant's site IDs
            sites_result = await session.execute(
                select(Site.id).where(Site.tenant_id == tenant_id)
            )
            site_ids = [row[0] for row in sites_result.all()]

            if not site_ids:
                return  # No sites, nothing to check

            # Count concurrent active runs
            active_result = await session.execute(
                select(func.count()).where(
                    and_(
                        CrawlRun.site_id.in_(site_ids),
                        CrawlRun.status.in_([RunStatus.pending, RunStatus.running]),
                    )
                )
            )
            active_count = active_result.scalar() or 0

            max_concurrent = DEFAULT_QUOTAS["max_concurrent_runs"]
            if active_count >= max_concurrent:
                raise HTTPException(
                    429,
                    f"Concurrent run limit reached ({active_count}/{max_concurrent}). "
                    f"Wait for current runs to finish.",
                )

            # Check monthly page budget
            month_start = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            monthly_result = await session.execute(
                select(func.coalesce(func.sum(CrawlRun.pages_crawled), 0)).where(
                    and_(
                        CrawlRun.site_id.in_(site_ids),
                        CrawlRun.status == RunStatus.completed,
                        CrawlRun.completed_at >= month_start,
                    )
                )
            )
            monthly_pages = monthly_result.scalar() or 0

            max_monthly = DEFAULT_QUOTAS["max_monthly_pages"]
            if monthly_pages >= max_monthly:
                raise HTTPException(
                    429,
                    f"Monthly page budget exhausted ({monthly_pages:,}/{max_monthly:,}). "
                    f"Resets on the 1st of next month.",
                )


async def check_site_quota(tenant_id: str) -> dict:
    """Get current quota usage for a tenant. Used by status endpoints."""
    async with async_session_factory() as session:
        sites_result = await session.execute(
            select(func.count()).where(Site.tenant_id == tenant_id)
        )
        site_count = sites_result.scalar() or 0

        site_ids_result = await session.execute(
            select(Site.id).where(Site.tenant_id == tenant_id)
        )
        site_ids = [row[0] for row in site_ids_result.all()]

        active_runs = 0
        monthly_pages = 0

        if site_ids:
            active_result = await session.execute(
                select(func.count()).where(
                    and_(
                        CrawlRun.site_id.in_(site_ids),
                        CrawlRun.status.in_([RunStatus.pending, RunStatus.running]),
                    )
                )
            )
            active_runs = active_result.scalar() or 0

            month_start = datetime.now(timezone.utc).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            monthly_result = await session.execute(
                select(func.coalesce(func.sum(CrawlRun.pages_crawled), 0)).where(
                    and_(
                        CrawlRun.site_id.in_(site_ids),
                        CrawlRun.status == RunStatus.completed,
                        CrawlRun.completed_at >= month_start,
                    )
                )
            )
            monthly_pages = monthly_result.scalar() or 0

    return {
        "tenant_id": tenant_id,
        "sites": {"used": site_count, "limit": DEFAULT_QUOTAS["max_sites"]},
        "concurrent_runs": {"used": active_runs, "limit": DEFAULT_QUOTAS["max_concurrent_runs"]},
        "monthly_pages": {"used": monthly_pages, "limit": DEFAULT_QUOTAS["max_monthly_pages"]},
        "api_rate_limit_rpm": DEFAULT_QUOTAS["api_rate_limit_rpm"],
    }
