"""FastAPI route definitions for the SEO Crawler API."""

from __future__ import annotations

import csv
import io
import json
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func as sa_func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db, async_session_factory
from app.db.models import (
    Tenant, Site, CrawlPolicy, CrawlRun, Issue, RunStatus,
    IssueSeverity, Page, RunMetric,
)
from app.db.persistence import CrawlPersistence
from app.crawler.tasks import schedule_crawl, cancel_run, is_run_active, get_active_run_ids
from app.middleware.quota import check_site_quota
from app.api.schemas import (
    TenantCreate, TenantOut,
    SiteCreate, SiteOut,
    CrawlPolicyUpdate, CrawlPolicyOut,
    CrawlRunOut, RunTriggerResponse,
    IssueOut, IssueSummary, RunReport,
    TrendPoint, TrendResponse,
)

router = APIRouter(prefix="/api/v1")


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

@router.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    tenant = Tenant(name=body.name, slug=body.slug, contact_email=body.contact_email)
    db.add(tenant)
    await db.flush()
    await db.refresh(tenant)
    return tenant


@router.get("/tenants", response_model=list[TenantOut])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Tenant).order_by(Tenant.name))
    return result.scalars().all()


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    return tenant


@router.get("/tenants/{tenant_id}/quota")
async def get_tenant_quota(tenant_id: uuid.UUID):
    """Get current quota usage for a tenant."""
    return await check_site_quota(str(tenant_id))


# ---------------------------------------------------------------------------
# Sites
# ---------------------------------------------------------------------------

@router.post("/tenants/{tenant_id}/sites", response_model=SiteOut, status_code=201)
async def create_site(
    tenant_id: uuid.UUID,
    body: SiteCreate,
    db: AsyncSession = Depends(get_db),
):
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    site = Site(
        tenant_id=tenant_id,
        name=body.name,
        domain=body.domain,
        start_urls=body.start_urls or [f"https://{body.domain}/"],
    )
    db.add(site)
    await db.flush()

    # Create default crawl policy
    policy = CrawlPolicy(site_id=site.id)
    db.add(policy)
    await db.flush()

    await db.refresh(site, ["crawl_policy"])
    return site


@router.get("/tenants/{tenant_id}/sites", response_model=list[SiteOut])
async def list_sites(tenant_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Site)
        .where(Site.tenant_id == tenant_id)
        .options(selectinload(Site.crawl_policy))
        .order_by(Site.name)
    )
    return result.scalars().all()


@router.get("/sites/{site_id}", response_model=SiteOut)
async def get_site(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Site).where(Site.id == site_id).options(selectinload(Site.crawl_policy))
    )
    site = result.scalar_one_or_none()
    if not site:
        raise HTTPException(404, "Site not found")
    return site


# ---------------------------------------------------------------------------
# Crawl Policy
# ---------------------------------------------------------------------------

@router.patch("/sites/{site_id}/policy", response_model=CrawlPolicyOut)
async def update_crawl_policy(
    site_id: uuid.UUID,
    body: CrawlPolicyUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CrawlPolicy).where(CrawlPolicy.site_id == site_id)
    )
    policy = result.scalar_one_or_none()
    if not policy:
        raise HTTPException(404, "Policy not found for this site")

    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(policy, key, value)

    await db.flush()
    await db.refresh(policy)
    return policy


# ---------------------------------------------------------------------------
# Crawl Runs
# ---------------------------------------------------------------------------

@router.post("/sites/{site_id}/runs", response_model=RunTriggerResponse, status_code=202)
async def trigger_run(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    site = await db.get(Site, site_id)
    if not site:
        raise HTTPException(404, "Site not found")

    # Check no run is already in progress
    result = await db.execute(
        select(CrawlRun).where(
            CrawlRun.site_id == site_id,
            CrawlRun.status.in_([RunStatus.pending, RunStatus.running]),
        )
    )
    active = result.scalar_one_or_none()
    if active:
        raise HTTPException(409, f"Run {active.id} is already {active.status.value}")

    # Load site config for the orchestrator
    persistence = CrawlPersistence(db)
    config = await persistence.load_site_config(str(site_id))

    # Create run record
    run_id = await persistence.create_run(str(site_id))
    await db.commit()

    # Schedule background crawl task
    await schedule_crawl(
        site_id=str(site_id),
        run_id=run_id,
        config=config,
        session_factory=async_session_factory,
    )

    return RunTriggerResponse(
        run_id=uuid.UUID(run_id),
        status="pending",
        message="Crawl started. Monitor progress via GET /sites/{site_id}/runs.",
    )


@router.post("/runs/{run_id}/cancel")
async def cancel_crawl_run(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    run = await db.get(CrawlRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in (RunStatus.pending, RunStatus.running):
        raise HTTPException(400, f"Run is already {run.status.value}")
    cancelled = cancel_run(str(run_id))
    if cancelled:
        return {"message": "Cancellation requested", "run_id": str(run_id)}
    else:
        raise HTTPException(400, "Run is not currently active")


@router.get("/runs/active")
async def list_active_runs():
    return {"active_run_ids": get_active_run_ids()}


@router.get("/sites/{site_id}/runs", response_model=list[CrawlRunOut])
async def list_runs(
    site_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CrawlRun)
        .where(CrawlRun.site_id == site_id)
        .order_by(desc(CrawlRun.created_at))
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/sites/{site_id}/runs/latest", response_model=RunReport)
async def get_latest_run_report(site_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Get latest completed run
    result = await db.execute(
        select(CrawlRun)
        .where(CrawlRun.site_id == site_id, CrawlRun.status == RunStatus.completed)
        .order_by(desc(CrawlRun.created_at))
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "No completed runs found")

    # Issue summary
    severity_counts = await db.execute(
        select(Issue.severity, sa_func.count())
        .where(Issue.crawl_run_id == run.id)
        .group_by(Issue.severity)
    )
    counts = {row[0].value: row[1] for row in severity_counts}
    summary = IssueSummary(
        critical=counts.get("critical", 0),
        high=counts.get("high", 0),
        medium=counts.get("medium", 0),
        low=counts.get("low", 0),
        total=sum(counts.values()),
    )

    # Top issues (critical + high, limited)
    top_result = await db.execute(
        select(Issue)
        .where(Issue.crawl_run_id == run.id)
        .order_by(Issue.severity, desc(Issue.affected_urls_count))
        .limit(20)
    )
    top_issues = top_result.scalars().all()

    return RunReport(run=run, issue_summary=summary, top_issues=top_issues)


# ---------------------------------------------------------------------------
# Issues
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/issues", response_model=list[IssueOut])
async def list_issues(
    run_id: uuid.UUID,
    severity: Optional[str] = None,
    issue_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    q = select(Issue).where(Issue.crawl_run_id == run_id)
    if severity:
        q = q.where(Issue.severity == severity)
    if issue_type:
        q = q.where(Issue.issue_type == issue_type)
    q = q.order_by(Issue.severity, desc(Issue.affected_urls_count)).offset(offset).limit(limit)

    result = await db.execute(q)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Trends
# ---------------------------------------------------------------------------

@router.get("/sites/{site_id}/trends", response_model=TrendResponse)
async def get_trends(
    site_id: uuid.UUID,
    months: int = Query(6, ge=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    result = await db.execute(
        select(CrawlRun)
        .where(
            CrawlRun.site_id == site_id,
            CrawlRun.status == RunStatus.completed,
            CrawlRun.completed_at >= cutoff,
        )
        .order_by(CrawlRun.completed_at)
    )
    runs = result.scalars().all()

    points = [
        TrendPoint(
            run_id=r.id,
            date=r.completed_at or r.created_at,
            pages_crawled=r.pages_crawled,
            pages_indexable=r.pages_indexable,
            errors_count=r.errors_count,
            issue_counts=r.issue_counts or {},
        )
        for r in runs
    ]

    return TrendResponse(site_id=site_id, period_months=months, data_points=points)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

async def _load_run_data(run_id: uuid.UUID, db: AsyncSession):
    """Load full run data (pages, links, issues) from the database."""
    run = await db.get(CrawlRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.completed:
        raise HTTPException(400, f"Run is {run.status.value}, not completed")

    pages_result = await db.execute(
        select(Page).where(Page.crawl_run_id == run_id)
    )
    pages = pages_result.scalars().all()

    from app.db.models import Link
    links_result = await db.execute(
        select(Link).where(Link.crawl_run_id == run_id)
    )
    links = links_result.scalars().all()

    issues_result = await db.execute(
        select(Issue).where(Issue.crawl_run_id == run_id)
        .order_by(Issue.severity, desc(Issue.affected_urls_count))
    )
    issues = issues_result.scalars().all()

    return run, pages, links, issues


def _page_to_dict(p) -> dict:
    return {
        "url": p.url,
        "status_code": p.status_code,
        "title": p.title,
        "title_length": p.title_length,
        "meta_description": p.meta_description,
        "meta_description_length": p.meta_description_length,
        "h1_text": p.h1_text,
        "h1_count": p.h1_count,
        "word_count": p.word_count,
        "canonical_url": p.canonical_url,
        "is_indexable": p.is_indexable,
        "indexability_reason": p.indexability_reason,
        "depth": p.crawl_depth,
        "internal_links_count": p.internal_links_count,
        "external_links_count": p.external_links_count,
        "img_count": p.img_count,
        "img_missing_alt": p.img_missing_alt,
        "ttfb_ms": p.ttfb_ms,
        "response_bytes": p.response_bytes,
        "was_rendered": p.was_rendered,
        "content_hash": p.content_hash,
        "redirect_chain": p.redirect_chain,
        "meta_robots": p.meta_robots,
        "robots_txt_allowed": p.robots_txt_allowed,
        "hreflang_tags": p.hreflang_tags,
        "structured_data_types": p.structured_data_types,
    }


def _issue_to_dict(i) -> dict:
    return {
        "issue_type": i.issue_type.value if hasattr(i.issue_type, "value") else str(i.issue_type),
        "severity": i.severity.value if hasattr(i.severity, "value") else str(i.severity),
        "confidence": i.confidence,
        "affected_url": i.affected_url,
        "affected_urls_count": i.affected_urls_count,
        "affected_urls_sample": i.affected_urls_sample,
        "how_to_fix": i.how_to_fix,
        "why_it_matters": i.why_it_matters,
        "is_new": i.is_new,
        "is_regression": i.is_regression,
    }


def _link_to_dict(l) -> dict:
    return {
        "source_url": l.source_url,
        "dest_url": l.dest_url,
        "anchor_text": l.anchor_text,
        "is_internal": l.is_internal,
        "is_follow": l.is_follow,
        "link_context": l.link_context,
    }


@router.get("/runs/{run_id}/export/json")
async def export_run_json(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Export complete run data as JSON."""
    run, pages, links, issues = await _load_run_data(run_id, db)

    data = {
        "run_id": str(run.id),
        "site_id": str(run.site_id),
        "status": run.status.value,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "pages_crawled": run.pages_crawled,
        "pages_indexable": run.pages_indexable,
        "pages_rendered": run.pages_rendered,
        "issue_counts": run.issue_counts,
        "pages": [_page_to_dict(p) for p in pages],
        "links": [_link_to_dict(l) for l in links],
        "issues": [_issue_to_dict(i) for i in issues],
    }

    content = json.dumps(data, indent=2, default=str)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=crawl_{run_id}.json"},
    )


@router.get("/runs/{run_id}/export/csv")
async def export_run_csv(
    run_id: uuid.UUID,
    dataset: str = Query("pages", regex="^(pages|issues|links)$"),
    db: AsyncSession = Depends(get_db),
):
    """Export pages, issues, or links as CSV."""
    run, pages, links, issues = await _load_run_data(run_id, db)

    output = io.StringIO()
    writer = csv.writer(output)

    if dataset == "pages":
        headers = [
            "url", "status_code", "title", "title_length", "meta_description_length",
            "h1_text", "h1_count", "word_count", "canonical_url", "is_indexable",
            "indexability_reason", "depth", "internal_links_count", "external_links_count",
            "img_count", "img_missing_alt", "ttfb_ms", "response_bytes", "was_rendered",
        ]
        writer.writerow(headers)
        for p in pages:
            d = _page_to_dict(p)
            writer.writerow([d.get(h, "") for h in headers])
    elif dataset == "issues":
        headers = [
            "severity", "issue_type", "confidence", "affected_urls_count",
            "affected_url", "how_to_fix", "why_it_matters", "is_new", "is_regression",
        ]
        writer.writerow(headers)
        for i in issues:
            d = _issue_to_dict(i)
            writer.writerow([d.get(h, "") for h in headers])
    else:  # links
        headers = [
            "source_url", "dest_url", "anchor_text", "is_internal", "is_follow", "link_context",
        ]
        writer.writerow(headers)
        for l in links:
            d = _link_to_dict(l)
            writer.writerow([d.get(h, "") for h in headers])

    content = output.getvalue()
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=crawl_{run_id}_{dataset}.csv"},
    )


@router.get("/runs/{run_id}/export/xlsx")
async def export_run_xlsx(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Export complete run as multi-sheet Excel workbook."""
    run, pages, links, issues = await _load_run_data(run_id, db)

    # Get site info for the report
    site = await db.get(Site, run.site_id)
    domain = site.domain if site else "unknown"

    pages_dicts = [_page_to_dict(p) for p in pages]
    links_dicts = [_link_to_dict(l) for l in links]
    issues_dicts = [_issue_to_dict(i) for i in issues]

    # Build summary
    sev_counts = run.issue_counts or {}
    summary = {
        "domain": domain,
        "timestamp": (run.completed_at or run.created_at).isoformat() if run.completed_at else "",
        "stats": {
            "pages_crawled": run.pages_crawled or 0,
            "pages_rendered": run.pages_rendered or 0,
            "links_found": len(links_dicts),
        },
        "issue_summary": sev_counts,
    }

    from app.export.excel_report import generate_excel_report

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        generate_excel_report(pages_dicts, links_dicts, issues_dicts, summary, tmp.name)
        tmp.seek(0)
        content = open(tmp.name, "rb").read()

    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=seo_report_{run_id}.xlsx"},
    )
