"""Initial schema — all tables.

Revision ID: 001
Revises: 
Create Date: 2026-03-03
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tenants ---
    op.create_table(
        'tenants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False, unique=True),
        sa.Column('contact_email', sa.String(255)),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- sites ---
    op.create_table(
        'sites',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('start_urls', postgresql.JSONB, nullable=False, server_default='[]'),
        sa.Column('domain', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_sites_tenant', 'sites', ['tenant_id'])

    # --- crawl_policies ---
    op.create_table(
        'crawl_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('site_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('max_pages', sa.Integer, server_default='10000'),
        sa.Column('max_depth', sa.Integer, server_default='50'),
        sa.Column('max_concurrency', sa.Integer, server_default='5'),
        sa.Column('rate_limit_rps', sa.Float, server_default='2.0'),
        sa.Column('render_mode', sa.String(20), server_default="'targeted'"),
        sa.Column('render_cap', sa.Integer, server_default='500'),
        sa.Column('user_agent', sa.Text, server_default="''"),
        sa.Column('mobile_parity_check', sa.Boolean, server_default='false'),
        sa.Column('respect_robots', sa.Boolean, server_default='true'),
        sa.Column('include_subdomains', sa.Boolean, server_default='false'),
        sa.Column('subdomain_allowlist', postgresql.JSONB, server_default='[]'),
        sa.Column('drop_tracking_params', sa.Boolean, server_default='true'),
        sa.Column('param_allowlist', postgresql.JSONB, server_default='[]'),
        sa.Column('param_denylist', postgresql.JSONB, server_default='[]'),
        sa.Column('important_patterns', postgresql.JSONB, server_default='[]'),
        sa.Column('noindex_patterns', postgresql.JSONB, server_default='[]'),
        sa.Column('schedule_cron', sa.String(50), server_default="'0 2 1 * *'"),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- crawl_runs ---
    op.create_table(
        'crawl_runs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('site_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('sites.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default="'pending'"),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('pages_crawled', sa.Integer, server_default='0'),
        sa.Column('pages_rendered', sa.Integer, server_default='0'),
        sa.Column('pages_indexable', sa.Integer, server_default='0'),
        sa.Column('errors_count', sa.Integer, server_default='0'),
        sa.Column('issue_counts', postgresql.JSONB, server_default='{}'),
        sa.Column('meta', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_crawl_runs_site_status', 'crawl_runs', ['site_id', 'status'])

    # --- pages ---
    op.create_table(
        'pages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('crawl_run_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('crawl_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('url', sa.Text, nullable=False),
        sa.Column('url_normalized', sa.Text, nullable=False),
        sa.Column('final_url', sa.Text),
        sa.Column('canonical_url', sa.Text),
        sa.Column('crawl_depth', sa.Integer, server_default='0'),
        sa.Column('parent_urls', postgresql.JSONB, server_default='[]'),
        sa.Column('status_code', sa.Integer),
        sa.Column('content_type', sa.String(100)),
        sa.Column('charset', sa.String(50)),
        sa.Column('response_bytes', sa.Integer),
        sa.Column('ttfb_ms', sa.Float),
        sa.Column('download_time_ms', sa.Float),
        sa.Column('fetch_timestamp', sa.DateTime(timezone=True)),
        sa.Column('redirect_chain', postgresql.JSONB, server_default='[]'),
        sa.Column('cache_headers', postgresql.JSONB, server_default='{}'),
        sa.Column('x_robots_tag', sa.Text),
        sa.Column('hreflang_header', postgresql.JSONB, server_default='[]'),
        sa.Column('robots_txt_allowed', sa.Boolean, server_default='true'),
        sa.Column('meta_robots', sa.Text),
        sa.Column('is_indexable', sa.Boolean, server_default='true'),
        sa.Column('indexability_reason', sa.String(100)),
        sa.Column('title', sa.Text),
        sa.Column('title_length', sa.Integer),
        sa.Column('meta_description', sa.Text),
        sa.Column('meta_description_length', sa.Integer),
        sa.Column('h1_text', sa.Text),
        sa.Column('h1_count', sa.Integer, server_default='0'),
        sa.Column('heading_outline', postgresql.JSONB, server_default='[]'),
        sa.Column('word_count', sa.Integer, server_default='0'),
        sa.Column('content_hash', sa.String(64)),
        sa.Column('hreflang_tags', postgresql.JSONB, server_default='[]'),
        sa.Column('structured_data', postgresql.JSONB, server_default='[]'),
        sa.Column('structured_data_types', postgresql.JSONB, server_default='[]'),
        sa.Column('img_count', sa.Integer, server_default='0'),
        sa.Column('img_missing_alt', sa.Integer, server_default='0'),
        sa.Column('img_lazy_broken', sa.Integer, server_default='0'),
        sa.Column('internal_links_count', sa.Integer, server_default='0'),
        sa.Column('external_links_count', sa.Integer, server_default='0'),
        sa.Column('internal_nofollow_count', sa.Integer, server_default='0'),
        sa.Column('was_rendered', sa.Boolean, server_default='false'),
        sa.Column('render_time_ms', sa.Float),
        sa.Column('console_errors', postgresql.JSONB, server_default='[]'),
        sa.Column('dom_mutations_count', sa.Integer),
        sa.Column('raw_vs_rendered_diff', postgresql.JSONB, server_default='{}'),
        sa.Column('mobile_checked', sa.Boolean, server_default='false'),
        sa.Column('mobile_diff', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_pages_run_url', 'pages', ['crawl_run_id', 'url_normalized'])
    op.create_index('ix_pages_run_status', 'pages', ['crawl_run_id', 'status_code'])
    op.create_index('ix_pages_content_hash', 'pages', ['crawl_run_id', 'content_hash'])

    # --- links ---
    op.create_table(
        'links',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('crawl_run_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('crawl_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_url', sa.Text, nullable=False),
        sa.Column('dest_url', sa.Text, nullable=False),
        sa.Column('dest_url_normalized', sa.Text, nullable=False),
        sa.Column('anchor_text', sa.Text),
        sa.Column('is_internal', sa.Boolean, server_default='true'),
        sa.Column('is_follow', sa.Boolean, server_default='true'),
        sa.Column('link_context', sa.String(20)),
        sa.Column('source_status', sa.Integer),
        sa.Column('dest_status', sa.Integer),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_links_run_dest', 'links', ['crawl_run_id', 'dest_url_normalized'])
    op.create_index('ix_links_run_source', 'links', ['crawl_run_id', 'source_url'])

    # --- issues ---
    op.create_table(
        'issues',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('crawl_run_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('crawl_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('issue_type', sa.String(60), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False),
        sa.Column('confidence', sa.Float, server_default='1.0'),
        sa.Column('affected_url', sa.Text),
        sa.Column('affected_urls_count', sa.Integer, server_default='1'),
        sa.Column('affected_urls_sample', postgresql.JSONB, server_default='[]'),
        sa.Column('detail', postgresql.JSONB, server_default='{}'),
        sa.Column('how_to_fix', sa.Text),
        sa.Column('why_it_matters', sa.Text),
        sa.Column('is_new', sa.Boolean, server_default='true'),
        sa.Column('is_regression', sa.Boolean, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_issues_run_type', 'issues', ['crawl_run_id', 'issue_type'])
    op.create_index('ix_issues_run_severity', 'issues', ['crawl_run_id', 'severity'])

    # --- run_metrics ---
    op.create_table(
        'run_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('crawl_run_id', postgresql.UUID(as_uuid=True),
                   sa.ForeignKey('crawl_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('metric_name', sa.String(100), nullable=False),
        sa.Column('metric_value', sa.Float, nullable=False),
        sa.Column('meta', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_run_metrics_run_name', 'run_metrics', ['crawl_run_id', 'metric_name'])


def downgrade() -> None:
    op.drop_table('run_metrics')
    op.drop_table('issues')
    op.drop_table('links')
    op.drop_table('pages')
    op.drop_table('crawl_runs')
    op.drop_table('crawl_policies')
    op.drop_table('sites')
    op.drop_table('tenants')
