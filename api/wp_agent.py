"""
wp_agent.py — WordPress REST API write-back agent.

Finds posts/pages by URL slug, then applies SEO fixes:
  - Yoast SEO title + meta description
  - Internal link injection into post content

Requires env vars:
  WP_URL            e.g. https://davidvesterlund.com
  WP_USER           WordPress username (e.g. david)
  WP_APP_PASSWORD   WordPress application password (generate in WP → Users → Application Passwords)
"""

import base64
import logging
import os
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

WP_URL  = os.environ.get("WP_URL", "").rstrip("/")
WP_USER = os.environ.get("WP_USER", "")
WP_PASS = os.environ.get("WP_APP_PASSWORD", "")


def _is_configured() -> bool:
    return bool(WP_URL and WP_USER and WP_PASS)


def debug_auth() -> dict:
    """Test WP authentication and return diagnostic info."""
    if not _is_configured():
        return {"configured": False, "wp_url": WP_URL, "wp_user": WP_USER, "reason": "missing credentials"}
    try:
        r = httpx.get(
            f"{WP_URL}/wp-json/wp/v2/users/me",
            params={"context": "edit"},
            headers=_auth_header(),
            timeout=15,
        )
        if r.status_code == 200:
            u = r.json()
            return {
                "auth_ok": True,
                "wp_url": WP_URL,
                "wp_user": WP_USER,
                "logged_in_as": u.get("name"),
                "slug": u.get("slug"),
                "roles": list(u.get("roles", [])),
                "can_edit_posts": u.get("capabilities", {}).get("edit_posts", False),
            }
        return {
            "auth_ok": False,
            "wp_url": WP_URL,
            "wp_user": WP_USER,
            "status_code": r.status_code,
            "error": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300],
        }
    except Exception as e:
        return {"auth_ok": False, "wp_user": WP_USER, "exception": str(e)}


def _auth_header() -> dict:
    token = base64.b64encode(f"{WP_USER}:{WP_PASS}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


# ── Post/page lookup ───────────────────────────────────────────────────────────

def _fetch_all_posts(post_type: str = "posts", per_page: int = 100) -> list[dict]:
    """Fetch all posts of a given type with minimal fields."""
    items, page = [], 1
    while True:
        try:
            r = httpx.get(
                f"{WP_URL}/wp-json/wp/v2/{post_type}",
                params={"per_page": per_page, "page": page,
                        "_fields": "id,link,slug,status"},
                headers=_auth_header(),
                timeout=30,
            )
            if r.status_code == 400:
                break
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            items.extend(batch)
            page += 1
        except Exception as e:
            logger.warning("WP fetch %s page %d failed: %s", post_type, page, e)
            break
    return items


def build_url_map() -> dict[str, dict]:
    """Return {path → {id, type}} for all published WP posts and pages."""
    url_map: dict[str, dict] = {}
    for post_type in ("posts", "pages"):
        for item in _fetch_all_posts(post_type):
            if item.get("status") not in ("publish", "published"):
                continue
            link = item.get("link", "")
            if not link:
                continue
            path = urlparse(link).path.rstrip("/")
            url_map[path] = {"id": item["id"], "type": post_type}
    logger.info("WP url_map built: %d entries", len(url_map))
    return url_map


def find_post_id(target_url: str, url_map: dict) -> tuple[int | None, str | None]:
    """Find WP post id and type for a given absolute URL."""
    path = urlparse(target_url).path.rstrip("/")
    entry = url_map.get(path)
    if entry:
        return entry["id"], entry["type"]
    # Fuzzy: try without trailing slash variants
    for k, v in url_map.items():
        if k.rstrip("/") == path:
            return v["id"], v["type"]
    return None, None


# ── Read post content ──────────────────────────────────────────────────────────

def get_post_content(post_id: int, post_type: str = "posts") -> str | None:
    """Fetch raw post content via WP REST API (needs Gutenberg raw context)."""
    try:
        r = httpx.get(
            f"{WP_URL}/wp-json/wp/v2/{post_type}/{post_id}",
            params={"context": "edit", "_fields": "id,content,title"},
            headers=_auth_header(),
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("content", {}).get("raw") or data.get("content", {}).get("rendered", "")
    except Exception as e:
        logger.warning("get_post_content %d failed: %s", post_id, e)
        return None


# ── Apply Yoast SEO meta ───────────────────────────────────────────────────────

def update_yoast_meta(post_id: int, post_type: str = "posts",
                      title: str | None = None,
                      meta_desc: str | None = None) -> dict:
    """
    Update Yoast SEO title and/or meta description for a post.
    Returns {"ok": bool, "status_code": int}.
    """
    if not _is_configured():
        return {"ok": False, "reason": "WP credentials not configured"}

    meta = {}
    if title:
        meta["_yoast_wpseo_title"] = title
    if meta_desc:
        meta["_yoast_wpseo_metadesc"] = meta_desc
    if not meta:
        return {"ok": False, "reason": "nothing to update"}

    try:
        r = httpx.post(
            f"{WP_URL}/wp-json/wp/v2/{post_type}/{post_id}",
            json={"meta": meta},
            headers=_auth_header(),
            timeout=30,
        )
        ok = r.status_code in (200, 201)
        if not ok:
            logger.warning("Yoast update %d failed %d: %s", post_id, r.status_code, r.text[:200])
        return {"ok": ok, "status_code": r.status_code}
    except Exception as e:
        logger.warning("update_yoast_meta %d error: %s", post_id, e)
        return {"ok": False, "reason": str(e)}


# ── Internal link injection ────────────────────────────────────────────────────

def _already_linked(content: str, target_url: str) -> bool:
    """Return True if the target URL is already present as an href in the content."""
    path = urlparse(target_url).path.rstrip("/")
    return path in content


def inject_internal_link(post_id: int, post_type: str,
                          anchor_text: str, target_url: str) -> dict:
    """
    Find `anchor_text` in post content and wrap the first occurrence with
    <a href="target_url">anchor_text</a> — only if not already linked.

    Returns {"ok": bool, "action": "injected"|"already_linked"|"anchor_not_found"|"error"}.
    """
    if not _is_configured():
        return {"ok": False, "action": "error", "reason": "WP credentials not configured"}

    content = get_post_content(post_id, post_type)
    if content is None:
        return {"ok": False, "action": "error", "reason": "could not fetch content"}

    if _already_linked(content, target_url):
        return {"ok": True, "action": "already_linked"}

    # Case-insensitive search for anchor text (avoid matching inside existing links)
    pattern = r'(?<!["\'>])(\b' + re.escape(anchor_text) + r'\b)(?![^<]*>)'
    if not re.search(pattern, content, re.IGNORECASE):
        return {"ok": False, "action": "anchor_not_found", "anchor": anchor_text}

    new_content = re.sub(
        pattern,
        f'<a href="{target_url}">{anchor_text}</a>',
        content,
        count=1,
        flags=re.IGNORECASE,
    )

    try:
        r = httpx.post(
            f"{WP_URL}/wp-json/wp/v2/{post_type}/{post_id}",
            json={"content": new_content},
            headers=_auth_header(),
            timeout=30,
        )
        ok = r.status_code in (200, 201)
        return {"ok": ok, "action": "injected" if ok else "error",
                "status_code": r.status_code}
    except Exception as e:
        logger.warning("inject_internal_link %d error: %s", post_id, e)
        return {"ok": False, "action": "error", "reason": str(e)}


# ── Batch action executor ──────────────────────────────────────────────────────

def execute_actions(actions: list[dict]) -> list[dict]:
    """
    Execute a list of structured actions against WordPress.

    Action types:
      {"type": "update_title",       "url": "...", "title": "..."}
      {"type": "update_meta_desc",   "url": "...", "meta_desc": "..."}
      {"type": "add_internal_link",  "source_url": "...", "anchor_text": "...", "target_url": "..."}

    Returns list of result dicts.
    """
    if not _is_configured():
        logger.warning("WP not configured — skipping %d actions", len(actions))
        return [{"action": a, "ok": False, "reason": "WP not configured"} for a in actions]

    url_map = build_url_map()
    results = []

    for action in actions:
        atype = action.get("type", "")
        try:
            if atype in ("update_title", "update_meta_desc"):
                url = action.get("url", "")
                pid, ptype = find_post_id(url, url_map)
                if not pid:
                    results.append({"action": action, "ok": False, "reason": f"post not found for {url}"})
                    continue
                res = update_yoast_meta(
                    pid, ptype or "posts",
                    title    = action.get("title")    if atype == "update_title"     else None,
                    meta_desc= action.get("meta_desc") if atype == "update_meta_desc" else None,
                )
                results.append({"action": action, **res})

            elif atype == "add_internal_link":
                source_url  = action.get("source_url", "")
                anchor_text = action.get("anchor_text", "")
                target_url  = action.get("target_url", "")
                pid, ptype = find_post_id(source_url, url_map)
                if not pid:
                    results.append({"action": action, "ok": False, "reason": f"source post not found for {source_url}"})
                    continue
                res = inject_internal_link(pid, ptype or "posts", anchor_text, target_url)
                results.append({"action": action, **res})

            else:
                results.append({"action": action, "ok": False, "reason": f"unknown action type: {atype}"})

        except Exception as e:
            logger.error("execute_action %s error: %s", atype, e, exc_info=True)
            results.append({"action": action, "ok": False, "reason": str(e)})

    ok_count = sum(1 for r in results if r.get("ok"))
    logger.info("WP actions: %d/%d succeeded", ok_count, len(results))
    return results
