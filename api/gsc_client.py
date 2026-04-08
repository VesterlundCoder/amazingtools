"""
gsc_client.py — Google Search Console data fetcher.

Auth: Service Account (Option A).
  - Global key: GOOGLE_SERVICE_ACCOUNT_JSON env var (JSON string).
  - Per-site override: pass service_account_json arg directly.

If no credentials are available, returns {} gracefully so the pipeline
falls back to Ahrefs data.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def _build_service(sa_info: dict):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(
        sa_info, scopes=_SCOPES
    )
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def fetch_gsc_data(
    site_url: str,
    service_account_json: Optional[str] = None,
    days: int = 28,
    row_limit: int = 5000,
) -> dict[str, dict]:
    """
    Fetch GSC clicks / impressions / CTR / position per page URL.

    Args:
        site_url: GSC property URL, e.g. "https://example.com/" or
                  "sc-domain:example.com"
        service_account_json: JSON string of the service account key.
                              Falls back to GOOGLE_SERVICE_ACCOUNT_JSON env var.
        days: Lookback window (GSC has ~2-day data lag).
        row_limit: Max rows returned per query (max 25000).

    Returns:
        dict[page_url, {gsc_clicks, gsc_impressions, gsc_ctr, gsc_position}]
        Empty dict if no credentials or on any error.
    """
    sa_str = service_account_json or os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not sa_str:
        logger.debug("GSC: no service account credentials for %s — skipping", site_url)
        return {}

    try:
        sa_info = json.loads(sa_str)
    except Exception as e:
        logger.warning("GSC: invalid service account JSON: %s", e)
        return {}

    end_date   = date.today() - timedelta(days=2)   # GSC ~2-day lag
    start_date = end_date - timedelta(days=days - 1)

    try:
        svc = _build_service(sa_info)
        body = {
            "startDate":  start_date.isoformat(),
            "endDate":    end_date.isoformat(),
            "dimensions": ["page"],
            "rowLimit":   row_limit,
            "dataState":  "final",
        }
        response = (
            svc.searchanalytics()
               .query(siteUrl=site_url, body=body)
               .execute()
        )
        rows = response.get("rows", [])
        result: dict[str, dict] = {}
        for row in rows:
            url = row["keys"][0]
            result[url] = {
                "gsc_clicks":      int(row.get("clicks", 0)),
                "gsc_impressions": int(row.get("impressions", 0)),
                "gsc_ctr":         round(float(row.get("ctr", 0.0)) * 100, 2),
                "gsc_position":    round(float(row.get("position", 0.0)), 1),
            }
        logger.info(
            "GSC: fetched %d URL rows for %s (last %d days)",
            len(result), site_url, days,
        )
        return result

    except Exception as e:
        logger.warning("GSC fetch failed for %s: %s", site_url, e)
        return {}


def merge_gsc_into_pages(pages: list[dict], gsc_data: dict[str, dict]) -> None:
    """Mutate each page dict in-place, injecting GSC metrics where available."""
    if not gsc_data:
        return
    for page in pages:
        url = page.get("url", "")
        if url in gsc_data:
            page.update(gsc_data[url])
        else:
            page.setdefault("gsc_clicks", None)
            page.setdefault("gsc_impressions", None)
            page.setdefault("gsc_ctr", None)
            page.setdefault("gsc_position", None)
