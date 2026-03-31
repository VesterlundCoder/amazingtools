"""
CLI runner: standalone script to execute a crawl + audit for a site.

Can be used without the full API/Postgres stack — stores results as JSON/CSV.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.crawler.orchestrator import CrawlOrchestrator
from app.audit.rules import run_all_checks
from app.export.excel_report import generate_excel_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_crawl(
    domain: str,
    start_urls: list[str] | None = None,
    output_dir: str = "./crawl_output",
    max_pages: int = 10000,
    max_depth: int = 50,
    concurrency: int = 5,
    rate_limit_rps: float = 2.0,
    render_mode: str = "targeted",
    render_cap: int = 500,
    user_agent: str = "SEOCrawler/1.0",
    respect_robots: bool = True,
    drop_tracking_params: bool = True,
    include_subdomains: bool = False,
):
    """
    Run a full crawl + audit for a domain and save results.

    Usage from CLI:
        python -m app.crawler.runner --domain example.com --max-pages 500
    """
    if not start_urls:
        start_urls = [f"https://{domain}/"]

    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir) / f"{domain.replace('.', '_')}_{timestamp}"
    out_path.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("SEO CRAWLER — %s", domain)
    logger.info("=" * 70)
    logger.info("Output: %s", out_path)
    logger.info("Max pages: %d | Concurrency: %d | Render: %s", max_pages, concurrency, render_mode)

    # Progress callback
    def on_progress(stats):
        done = stats.get("total_done", 0)
        remaining = stats.get("budget_remaining", 0)
        queue = stats.get("queue_size", 0)
        logger.info("  Progress: %d done | %d in queue | %d budget remaining", done, queue, remaining)

    orchestrator = CrawlOrchestrator(
        site_id="cli-run",
        domain=domain,
        start_urls=start_urls,
        max_pages=max_pages,
        max_depth=max_depth,
        max_concurrency=concurrency,
        rate_limit_rps=rate_limit_rps,
        render_mode=render_mode,
        render_cap=render_cap,
        user_agent=user_agent,
        respect_robots=respect_robots,
        drop_tracking_params=drop_tracking_params,
        include_subdomains=include_subdomains,
        on_progress=on_progress,
    )

    # Run crawl
    logger.info("\n[STEP 1] Crawling...")
    crawl_result = asyncio.run(orchestrator.run())

    pages = crawl_result["pages"]
    links = crawl_result["links"]
    stats = crawl_result["stats"]
    robots = crawl_result["robots"]

    logger.info("Crawl complete: %d pages, %d links, %d errors",
                stats["pages_crawled"], stats["links_found"], stats["errors"])

    # Run audit
    logger.info("\n[STEP 2] Running audit...")
    issues = run_all_checks(
        pages=pages,
        links=links,
        robots_data=robots,
        sitemap_urls_count=crawl_result.get("sitemap_urls_count", 0),
    )

    # Categorize issues
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for issue in issues:
        sev = issue.get("severity", "low")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    logger.info("Audit complete: %d issues found", len(issues))
    logger.info("  Critical: %d | High: %d | Medium: %d | Low: %d",
                severity_counts["critical"], severity_counts["high"],
                severity_counts["medium"], severity_counts["low"])

    # Save results
    logger.info("\n[STEP 3] Saving results...")

    # Pages JSON
    with open(out_path / "pages.json", "w", encoding="utf-8") as f:
        json.dump(pages, f, indent=2, default=str, ensure_ascii=False)
    logger.info("  Saved %d pages → pages.json", len(pages))

    # Links JSON
    with open(out_path / "links.json", "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2, default=str, ensure_ascii=False)
    logger.info("  Saved %d links → links.json", len(links))

    # Issues JSON
    with open(out_path / "issues.json", "w", encoding="utf-8") as f:
        json.dump(issues, f, indent=2, default=str, ensure_ascii=False)
    logger.info("  Saved %d issues → issues.json", len(issues))

    # Summary JSON
    summary = {
        "domain": domain,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stats": stats,
        "robots": robots,
        "sitemap_urls_count": crawl_result.get("sitemap_urls_count", 0),
        "issue_summary": severity_counts,
        "total_issues": len(issues),
    }
    with open(out_path / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str, ensure_ascii=False)
    logger.info("  Saved summary → summary.json")

    # Pages CSV (key fields)
    _save_pages_csv(pages, out_path / "pages.csv")
    logger.info("  Saved pages → pages.csv")

    # Issues CSV
    _save_issues_csv(issues, out_path / "issues.csv")
    logger.info("  Saved issues → issues.csv")

    # Excel report (multi-sheet)
    try:
        generate_excel_report(
            pages=pages,
            links=links,
            issues=issues,
            summary=summary,
            output_path=out_path / "seo_report.xlsx",
        )
        logger.info("  Saved Excel report → seo_report.xlsx")
    except Exception as e:
        logger.warning("  Could not generate Excel report: %s", e)

    logger.info("\n" + "=" * 70)
    logger.info("DONE — Results saved to: %s", out_path)
    logger.info("=" * 70)

    return {
        "output_dir": str(out_path),
        "stats": stats,
        "issues": severity_counts,
    }


def _save_pages_csv(pages: list[dict], path: Path):
    """Save key page fields to CSV."""
    fields = [
        "url", "final_url", "status_code", "content_type",
        "title", "title_length", "meta_description_length",
        "h1_text", "h1_count", "word_count",
        "canonical_url", "is_indexable", "indexability_reason",
        "is_noindex", "depth",
        "internal_links_count", "external_links_count",
        "img_count", "img_missing_alt",
        "ttfb_ms", "response_bytes",
        "redirect_hops", "was_rendered",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for p in pages:
            writer.writerow(p)


def _save_issues_csv(issues: list[dict], path: Path):
    """Save issues to CSV."""
    fields = [
        "issue_type", "severity", "confidence",
        "affected_url", "affected_urls_count",
        "how_to_fix", "why_it_matters",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for issue in issues:
            writer.writerow(issue)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="SEO Crawler CLI")
    parser.add_argument("--domain", required=True, help="Domain to crawl (e.g. example.com)")
    parser.add_argument("--start-url", help="Start URL (default: https://domain/)")
    parser.add_argument("--output", default="./crawl_output", help="Output directory")
    parser.add_argument("--max-pages", type=int, default=10000, help="Max pages to crawl")
    parser.add_argument("--max-depth", type=int, default=50, help="Max crawl depth")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent requests")
    parser.add_argument("--rps", type=float, default=2.0, help="Requests per second per host")
    parser.add_argument("--render", choices=["none", "targeted", "full"], default="targeted")
    parser.add_argument("--render-cap", type=int, default=500, help="Max pages to render")
    parser.add_argument("--user-agent", default="SEOCrawler/1.0")
    parser.add_argument("--no-robots", action="store_true", help="Ignore robots.txt")
    parser.add_argument("--include-subdomains", action="store_true")

    args = parser.parse_args()

    start_urls = [args.start_url] if args.start_url else None

    run_crawl(
        domain=args.domain,
        start_urls=start_urls,
        output_dir=args.output,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        concurrency=args.concurrency,
        rate_limit_rps=args.rps,
        render_mode=args.render,
        render_cap=args.render_cap,
        user_agent=args.user_agent,
        respect_robots=not args.no_robots,
        include_subdomains=args.include_subdomains,
    )
