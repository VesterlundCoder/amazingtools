"""Pydantic schemas for API request/response validation."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------

class TenantCreate(BaseModel):
    name: str
    slug: str
    contact_email: Optional[str] = None


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    contact_email: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CrawlPolicy
# ---------------------------------------------------------------------------

class CrawlPolicyUpdate(BaseModel):
    max_pages: Optional[int] = None
    max_depth: Optional[int] = None
    max_concurrency: Optional[int] = None
    rate_limit_rps: Optional[float] = None
    render_mode: Optional[str] = None
    render_cap: Optional[int] = None
    user_agent: Optional[str] = None
    mobile_parity_check: Optional[bool] = None
    respect_robots: Optional[bool] = None
    include_subdomains: Optional[bool] = None
    subdomain_allowlist: Optional[list[str]] = None
    drop_tracking_params: Optional[bool] = None
    param_allowlist: Optional[list[str]] = None
    param_denylist: Optional[list[str]] = None
    important_patterns: Optional[list[str]] = None
    noindex_patterns: Optional[list[str]] = None
    schedule_cron: Optional[str] = None


class CrawlPolicyOut(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    max_pages: int
    max_depth: int
    max_concurrency: int
    rate_limit_rps: float
    render_mode: str
    render_cap: int
    respect_robots: bool
    mobile_parity_check: bool
    drop_tracking_params: bool

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Site
# ---------------------------------------------------------------------------

class SiteCreate(BaseModel):
    name: str
    domain: str
    start_urls: list[str] = Field(default_factory=list)


class SiteOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    domain: str
    start_urls: list[str]
    is_active: bool
    created_at: datetime
    crawl_policy: Optional[CrawlPolicyOut] = None

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# CrawlRun
# ---------------------------------------------------------------------------

class CrawlRunOut(BaseModel):
    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    pages_crawled: int
    pages_rendered: int
    pages_indexable: int
    errors_count: int
    issue_counts: dict[str, int]
    created_at: datetime

    model_config = {"from_attributes": True}


class RunTriggerResponse(BaseModel):
    run_id: uuid.UUID
    status: str
    message: str


# ---------------------------------------------------------------------------
# Issue
# ---------------------------------------------------------------------------

class IssueOut(BaseModel):
    id: uuid.UUID
    issue_type: str
    severity: str
    confidence: float
    affected_url: Optional[str]
    affected_urls_count: int
    affected_urls_sample: list[str]
    detail: dict[str, Any]
    how_to_fix: Optional[str]
    why_it_matters: Optional[str]
    is_new: bool
    is_regression: bool

    model_config = {"from_attributes": True}


class IssueSummary(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    total: int = 0


class RunReport(BaseModel):
    run: CrawlRunOut
    issue_summary: IssueSummary
    top_issues: list[IssueOut]


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

class TrendPoint(BaseModel):
    run_id: uuid.UUID
    date: datetime
    pages_crawled: int
    pages_indexable: int
    errors_count: int
    issue_counts: dict[str, int]


class TrendResponse(BaseModel):
    site_id: uuid.UUID
    period_months: int
    data_points: list[TrendPoint]
