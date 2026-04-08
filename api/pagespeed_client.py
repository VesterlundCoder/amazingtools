"""
pagespeed_client.py — Google PageSpeed Insights v5 / Core Web Vitals fetcher.

Sync implementation (safe to call from background threads in FastAPI).
Works without an API key (rate-limited to ~2 req/s); set PSI_API_KEY env
var for a higher quota.

Fetches: LCP, CLS, INP, FCP, TTFB, Performance score.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_PSI_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_DEFAULT_TIMEOUT = 45
_DEFAULT_STRATEGY = "mobile"


def fetch_pagespeed(
    url: str,
    strategy: str = _DEFAULT_STRATEGY,
    api_key: Optional[str] = None,
) -> dict:
    """
    Fetch Core Web Vitals for a single URL.

    Returns a dict with psi_* keys, or {} on failure.
    """
    key = api_key or os.environ.get("PSI_API_KEY", "")
    params: dict = {
        "url":      url,
        "strategy": strategy,
        "category": "performance",
    }
    if key:
        params["key"] = key

    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT) as client:
            resp = client.get(_PSI_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

        lhr    = data.get("lighthouseResult", {})
        audits = lhr.get("audits", {})
        cats   = lhr.get("categories", {})

        def ms(k: str) -> int:
            return round(audits.get(k, {}).get("numericValue") or 0)

        def flt(k: str) -> float:
            return round(float(audits.get(k, {}).get("numericValue") or 0), 3)

        return {
            "psi_score":    round((cats.get("performance", {}).get("score") or 0) * 100),
            "psi_lcp_ms":   ms("largest-contentful-paint"),
            "psi_cls":      flt("cumulative-layout-shift"),
            "psi_inp_ms":   ms("interaction-to-next-paint"),
            "psi_fcp_ms":   ms("first-contentful-paint"),
            "psi_ttfb_ms":  ms("server-response-time"),
            "psi_strategy": strategy,
        }

    except Exception as e:
        logger.warning("PSI fetch failed for %s: %s", url, e)
        return {}


def fetch_pagespeed_batch(
    urls: list[str],
    strategy: str = _DEFAULT_STRATEGY,
    api_key: Optional[str] = None,
    cap: int = 20,
    delay_s: float = 1.2,
) -> dict[str, dict]:
    """
    Fetch PSI for multiple URLs sequentially with rate limiting.

    Args:
        urls:     List of page URLs to analyse.
        cap:      Max URLs to process (avoids quota burn on large sites).
        delay_s:  Sleep between requests (1.2s ≈ safe without API key).

    Returns:
        dict[url, psi_metrics]
    """
    results: dict[str, dict] = {}
    key = api_key or os.environ.get("PSI_API_KEY", "")

    for url in urls[:cap]:
        result = fetch_pagespeed(url, strategy=strategy, api_key=key)
        if result:
            results[url] = result
        time.sleep(delay_s)

    logger.info("PSI: fetched %d/%d URLs", len(results), min(len(urls), cap))
    return results


def merge_psi_into_pages(pages: list[dict], psi_data: dict[str, dict]) -> None:
    """Mutate each page dict in-place, injecting PSI metrics where available."""
    if not psi_data:
        return
    for page in pages:
        url = page.get("url", "")
        if url in psi_data:
            page.update(psi_data[url])
