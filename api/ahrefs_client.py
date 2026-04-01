"""
ahrefs_client.py — Ahrefs v3 API client.

Functions:
  fetch_ref_domains(url, api_key)       -> {"ref_domains_dr10": int, "ref_domains_total": int}
  fetch_organic_keywords(url, api_key)  -> [{"keyword", "position", "volume", "traffic"}, ...]

Used by main.py post-crawl to enrich client pages with external authority data.
The AHREFS_API_KEY environment variable must be set on the server.
"""

import logging
from datetime import date
import httpx

logger   = logging.getLogger(__name__)


def _today() -> str:
    return date.today().isoformat()
_BASE    = "https://api.ahrefs.com/v3"
_TIMEOUT = 20


def fetch_ref_domains(url: str, api_key: str) -> dict:
    """
    Fetch referring domains for a specific URL (exact match).
    Endpoint: GET /v3/site-explorer/refdomains
    Returns dict with:
      ref_domains_dr10    — count of referring domains with Domain Rating >= 10
      ref_domains_total   — total referring domains returned (up to 1000)
    """
    try:
        resp = httpx.get(
            f"{_BASE}/site-explorer/refdomains",
            params={
                "target":   url,
                "mode":     "prefix",
                "select":   "domain_rating_source,referring_domain",
                "limit":    "1000",
                "order_by": "domain_rating_source:desc",
                "date":     _today(),
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("Ahrefs ref-domains [%d] %s — %s",
                           resp.status_code, url, resp.text[:200])
            return {"ref_domains_dr10": 0, "ref_domains_total": 0}

        data    = resp.json()
        # Ahrefs v3 returns {"refdomains": [...], "total": N}
        domains = data.get("refdomains") or data.get("data") or []
        total   = len(domains)
        dr10    = sum(1 for d in domains if (d.get("domain_rating_source") or 0) >= 10)
        logger.info("Ahrefs ref-domains %s: total=%d dr10=%d", url, total, dr10)
        return {"ref_domains_dr10": dr10, "ref_domains_total": total}

    except Exception as e:
        logger.warning("Ahrefs ref-domains error %s: %s", url, e)
        return {"ref_domains_dr10": 0, "ref_domains_total": 0}


def fetch_organic_keywords(url: str, api_key: str, limit: int = 10) -> list:
    """
    Fetch top organic keyword rankings for a specific URL (exact match).
    Endpoint: GET /v3/site-explorer/organic-keywords
    Results are ordered by traffic descending.
    Returns list of {keyword, position, volume, traffic}.
    """
    try:
        resp = httpx.get(
            f"{_BASE}/site-explorer/organic-keywords",
            params={
                "target":   url,
                "mode":     "exact",
                "select":   "keyword,pos,volume,traffic",
                "limit":    str(limit),
                "order_by": "traffic:desc",
                "date":     _today(),
            },
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.warning("Ahrefs org-kw [%d] %s — %s",
                           resp.status_code, url, resp.text[:200])
            return []

        data = resp.json()
        # Ahrefs v3 returns {"organic_keywords": [...]} or {"keywords": [...]}
        kws  = (data.get("organic_keywords")
                or data.get("keywords")
                or data.get("data")
                or [])
        result = []
        for k in kws:
            kw = k.get("keyword", "").strip()
            if not kw:
                continue
            result.append({
                "keyword":  kw,
                "position": int(k.get("pos") or k.get("position") or 0),
                "volume":   int(k.get("volume") or 0),
                "traffic":  int(k.get("traffic") or 0),
            })
        logger.info("Ahrefs org-kw %s: %d keywords", url, len(result))
        return result

    except Exception as e:
        logger.warning("Ahrefs org-kw error %s: %s", url, e)
        return []
