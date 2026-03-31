"""
Multi-tenant database models for the SEO Crawler.

Tables:
  tenants          – organisations / customers
  sites            – websites belonging to a tenant
  crawl_policies   – per-site crawl configuration
  crawl_runs       – one execution of a crawl for a site
  pages            – per-URL page record within a run
  links            – edges in the link graph (source → dest)
  issues           – normalised audit findings
  run_metrics      – aggregate KPIs per run (for trend charts)
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RunStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    partial = "partial"


class IssueSeverity(str, enum.Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    low = "low"


class IssueType(str, enum.Enum):
    # Crawlability & Discovery
    robots_txt_missing = "robots_txt_missing"
    robots_txt_error = "robots_txt_error"
    robots_blocks_important = "robots_blocks_important"
    sitemap_missing = "sitemap_missing"
    sitemap_error = "sitemap_error"
    sitemap_url_error = "sitemap_url_error"
    sitemap_robots_conflict = "sitemap_robots_conflict"

    # Status codes
    http_4xx = "http_4xx"
    http_5xx = "http_5xx"
    soft_404 = "soft_404"

    # Redirects
    redirect_chain = "redirect_chain"
    redirect_loop = "redirect_loop"
    redirect_to_error = "redirect_to_error"
    mixed_redirect_chain = "mixed_redirect_chain"
    http_to_https_missing = "http_to_https_missing"
    www_canonicalization = "www_canonicalization"
    trailing_slash_inconsistency = "trailing_slash_inconsistency"

    # Canonical
    canonical_missing = "canonical_missing"
    canonical_multiple = "canonical_multiple"
    canonical_mismatch = "canonical_mismatch"
    canonical_to_redirect = "canonical_to_redirect"
    canonical_to_error = "canonical_to_error"

    # Duplicate content
    duplicate_content = "duplicate_content"
    duplicate_title = "duplicate_title"
    param_duplicate = "param_duplicate"

    # Meta robots / indexing
    noindex_should_index = "noindex_should_index"
    index_should_noindex = "index_should_noindex"
    robots_noindex_conflict = "robots_noindex_conflict"

    # Hreflang
    hreflang_missing_self = "hreflang_missing_self"
    hreflang_missing_return = "hreflang_missing_return"
    hreflang_canonical_conflict = "hreflang_canonical_conflict"

    # On-page
    title_missing = "title_missing"
    title_duplicate = "title_duplicate"
    title_too_short = "title_too_short"
    title_too_long = "title_too_long"
    meta_desc_missing = "meta_desc_missing"
    meta_desc_duplicate = "meta_desc_duplicate"
    h1_missing = "h1_missing"
    h1_multiple = "h1_multiple"
    h1_parity_issue = "h1_parity_issue"
    thin_content = "thin_content"

    # Links
    broken_internal_link = "broken_internal_link"
    orphan_page = "orphan_page"
    high_click_depth = "high_click_depth"
    internal_nofollow = "internal_nofollow"

    # Images
    img_missing_alt = "img_missing_alt"
    img_lazy_broken = "img_lazy_broken"
    img_blocked_robots = "img_blocked_robots"

    # Structured data
    structured_data_invalid = "structured_data_invalid"
    structured_data_missing_fields = "structured_data_missing_fields"

    # JS / Render
    js_render_errors = "js_render_errors"
    js_content_parity = "js_content_parity"
    js_link_parity = "js_link_parity"

    # Mobile parity
    mobile_content_parity = "mobile_content_parity"
    mobile_link_parity = "mobile_link_parity"

    # Performance
    slow_ttfb = "slow_ttfb"
    large_page = "large_page"

    # H1 enhancements
    h1_too_short = "h1_too_short"
    h1_too_long = "h1_too_long"
    h1_matches_title = "h1_matches_title"
    heading_hierarchy_gap = "heading_hierarchy_gap"

    # Meta tags
    meta_desc_too_short = "meta_desc_too_short"
    meta_desc_too_long = "meta_desc_too_long"
    og_tags_missing = "og_tags_missing"
    twitter_card_missing = "twitter_card_missing"
    viewport_missing = "viewport_missing"
    charset_missing = "charset_missing"

    # Structured data enhanced
    structured_data_missing = "structured_data_missing"

    # Images enhanced
    img_oversized = "img_oversized"
    img_missing_dimensions = "img_missing_dimensions"

    # Content quality
    near_duplicate_content = "near_duplicate_content"
    keyword_stuffing = "keyword_stuffing"
    stale_content = "stale_content"

    # URL hygiene
    mixed_case_url = "mixed_case_url"
    excessive_url_depth = "excessive_url_depth"
    url_special_characters = "url_special_characters"
    sitemap_crawl_gap = "sitemap_crawl_gap"

    # Hreflang enhanced
    hreflang_invalid_lang = "hreflang_invalid_lang"
    hreflang_x_default_missing = "hreflang_x_default_missing"
    hreflang_to_error = "hreflang_to_error"

    # Performance enhanced
    render_blocking_resource = "render_blocking_resource"
    font_display_missing = "font_display_missing"
    cls_risk = "cls_risk"

    # Security
    mixed_content = "mixed_content"
    missing_hsts = "missing_hsts"
    insecure_form_action = "insecure_form_action"

    # Accessibility
    missing_html_lang = "missing_html_lang"
    empty_link_text = "empty_link_text"
    missing_form_label = "missing_form_label"
    missing_skip_nav = "missing_skip_nav"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False, unique=True)
    contact_email = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    sites = relationship("Site", back_populates="tenant", cascade="all, delete-orphan")


class Site(Base):
    __tablename__ = "sites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    start_urls = Column(JSONB, nullable=False, default=list)  # ["https://example.com"]
    domain = Column(String(255), nullable=False)  # registrable domain
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tenant = relationship("Tenant", back_populates="sites")
    crawl_policy = relationship("CrawlPolicy", back_populates="site", uselist=False, cascade="all, delete-orphan")
    crawl_runs = relationship("CrawlRun", back_populates="site", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_sites_tenant", "tenant_id"),
    )


class CrawlPolicy(Base):
    """Per-site crawl configuration."""
    __tablename__ = "crawl_policies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, unique=True)

    max_pages = Column(Integer, default=10000)
    max_depth = Column(Integer, default=50)
    max_concurrency = Column(Integer, default=5)
    rate_limit_rps = Column(Float, default=2.0)
    render_mode = Column(String(20), default="targeted")  # "none", "targeted", "full"
    render_cap = Column(Integer, default=500)
    user_agent = Column(Text, default="")
    mobile_parity_check = Column(Boolean, default=False)
    respect_robots = Column(Boolean, default=True)

    # Subdomain policy
    include_subdomains = Column(Boolean, default=False)
    subdomain_allowlist = Column(JSONB, default=list)

    # URL param policy
    drop_tracking_params = Column(Boolean, default=True)
    param_allowlist = Column(JSONB, default=list)
    param_denylist = Column(JSONB, default=list)

    # Patterns that should be indexable (for noindex audit)
    important_patterns = Column(JSONB, default=list)  # ["/", "/blog/", "/product/"]
    noindex_patterns = Column(JSONB, default=list)     # ["/search", "/tag/"]

    # Schedule
    schedule_cron = Column(String(50), default="0 2 1 * *")  # 1st of month, 02:00

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    site = relationship("Site", back_populates="crawl_policy")


class CrawlRun(Base):
    """One execution of a crawl for a site."""
    __tablename__ = "crawl_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    status = Column(Enum(RunStatus), default=RunStatus.pending, nullable=False)

    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    pages_crawled = Column(Integer, default=0)
    pages_rendered = Column(Integer, default=0)
    pages_indexable = Column(Integer, default=0)
    errors_count = Column(Integer, default=0)

    # Summary (populated after audit)
    issue_counts = Column(JSONB, default=dict)  # {"critical": 5, "high": 12, ...}
    meta = Column(JSONB, default=dict)  # arbitrary run metadata

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    site = relationship("Site", back_populates="crawl_runs")
    pages = relationship("Page", back_populates="crawl_run", cascade="all, delete-orphan")
    links = relationship("Link", back_populates="crawl_run", cascade="all, delete-orphan")
    issues = relationship("Issue", back_populates="crawl_run", cascade="all, delete-orphan")
    run_metrics = relationship("RunMetric", back_populates="crawl_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_crawl_runs_site_status", "site_id", "status"),
    )


class Page(Base):
    """Per-URL page record within a crawl run."""
    __tablename__ = "pages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_run_id = Column(UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)

    # Identity
    url = Column(Text, nullable=False)
    url_normalized = Column(Text, nullable=False)
    final_url = Column(Text)
    canonical_url = Column(Text)
    crawl_depth = Column(Integer, default=0)
    parent_urls = Column(JSONB, default=list)

    # HTTP
    status_code = Column(Integer)
    content_type = Column(String(100))
    charset = Column(String(50))
    response_bytes = Column(Integer)
    ttfb_ms = Column(Float)
    download_time_ms = Column(Float)
    fetch_timestamp = Column(DateTime(timezone=True))

    # Redirect chain (list of {url, status_code})
    redirect_chain = Column(JSONB, default=list)

    # Headers
    cache_headers = Column(JSONB, default=dict)
    x_robots_tag = Column(Text)
    hreflang_header = Column(JSONB, default=list)

    # Robots
    robots_txt_allowed = Column(Boolean, default=True)

    # Indexability
    meta_robots = Column(Text)  # raw content attr
    is_indexable = Column(Boolean, default=True)
    indexability_reason = Column(String(100))  # e.g. "noindex", "robots_blocked", "canonical_other"

    # On-page
    title = Column(Text)
    title_length = Column(Integer)
    meta_description = Column(Text)
    meta_description_length = Column(Integer)
    h1_text = Column(Text)  # first H1
    h1_count = Column(Integer, default=0)
    heading_outline = Column(JSONB, default=list)  # [{"level": 1, "text": "..."}, ...]
    word_count = Column(Integer, default=0)
    content_hash = Column(String(64))  # sha256 of main text

    # Hreflang
    hreflang_tags = Column(JSONB, default=list)  # [{"lang": "en", "href": "..."}]

    # Structured data
    structured_data = Column(JSONB, default=list)  # extracted JSON-LD blocks
    structured_data_types = Column(JSONB, default=list)  # ["Article", "BreadcrumbList"]

    # Images
    img_count = Column(Integer, default=0)
    img_missing_alt = Column(Integer, default=0)
    img_lazy_broken = Column(Integer, default=0)

    # Internal / external links
    internal_links_count = Column(Integer, default=0)
    external_links_count = Column(Integer, default=0)
    internal_nofollow_count = Column(Integer, default=0)

    # JS render signals
    was_rendered = Column(Boolean, default=False)
    render_time_ms = Column(Float)
    console_errors = Column(JSONB, default=list)
    dom_mutations_count = Column(Integer)
    raw_vs_rendered_diff = Column(JSONB, default=dict)  # {"h1_changed": true, "links_added": 5, ...}

    # Mobile parity
    mobile_checked = Column(Boolean, default=False)
    mobile_diff = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    crawl_run = relationship("CrawlRun", back_populates="pages")

    __table_args__ = (
        Index("ix_pages_run_url", "crawl_run_id", "url_normalized"),
        Index("ix_pages_run_status", "crawl_run_id", "status_code"),
        Index("ix_pages_content_hash", "crawl_run_id", "content_hash"),
    )


class Link(Base):
    """Edge in the link graph for a crawl run."""
    __tablename__ = "links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_run_id = Column(UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)

    source_url = Column(Text, nullable=False)
    dest_url = Column(Text, nullable=False)
    dest_url_normalized = Column(Text, nullable=False)
    anchor_text = Column(Text)
    is_internal = Column(Boolean, default=True)
    is_follow = Column(Boolean, default=True)
    link_context = Column(String(20))  # "content", "nav", "footer", "sidebar"
    source_status = Column(Integer)
    dest_status = Column(Integer)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    crawl_run = relationship("CrawlRun", back_populates="links")

    __table_args__ = (
        Index("ix_links_run_dest", "crawl_run_id", "dest_url_normalized"),
        Index("ix_links_run_source", "crawl_run_id", "source_url"),
    )


class Issue(Base):
    """Normalised audit finding."""
    __tablename__ = "issues"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_run_id = Column(UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)

    issue_type = Column(Enum(IssueType), nullable=False)
    severity = Column(Enum(IssueSeverity), nullable=False)
    confidence = Column(Float, default=1.0)  # 0.0 – 1.0

    affected_url = Column(Text)  # primary example URL
    affected_urls_count = Column(Integer, default=1)
    affected_urls_sample = Column(JSONB, default=list)  # up to 10 example URLs

    detail = Column(JSONB, default=dict)  # issue-specific payload
    how_to_fix = Column(Text)
    why_it_matters = Column(Text)

    # Regression tracking
    is_new = Column(Boolean, default=True)  # not present in previous run
    is_regression = Column(Boolean, default=False)  # was fixed but came back

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    crawl_run = relationship("CrawlRun", back_populates="issues")

    __table_args__ = (
        Index("ix_issues_run_type", "crawl_run_id", "issue_type"),
        Index("ix_issues_run_severity", "crawl_run_id", "severity"),
    )


class RunMetric(Base):
    """Aggregate KPIs per run for trend charts."""
    __tablename__ = "run_metrics"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    crawl_run_id = Column(UUID(as_uuid=True), ForeignKey("crawl_runs.id", ondelete="CASCADE"), nullable=False)

    metric_name = Column(String(100), nullable=False)
    metric_value = Column(Float, nullable=False)
    meta = Column(JSONB, default=dict)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    crawl_run = relationship("CrawlRun", back_populates="run_metrics")

    __table_args__ = (
        Index("ix_run_metrics_run_name", "crawl_run_id", "metric_name"),
    )
