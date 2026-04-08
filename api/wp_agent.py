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


def _creds(override: dict | None = None) -> tuple[str, str, str]:
    """Return (url, user, pass) — use override dict if provided, else env vars."""
    if override:
        return (
            override.get("wp_url", WP_URL).rstrip("/"),
            override.get("wp_user", WP_USER),
            override.get("wp_app_password", WP_PASS),
        )
    return WP_URL, WP_USER, WP_PASS


def _is_configured(override: dict | None = None) -> bool:
    url, user, pw = _creds(override)
    return bool(url and user and pw)


def debug_auth(override: dict | None = None) -> dict:
    """Test WP authentication and return diagnostic info."""
    url, user, pw = _creds(override)
    if not _is_configured(override):
        return {"configured": False, "wp_url": url, "wp_user": user, "reason": "missing credentials"}
    try:
        r = httpx.get(
            f"{url}/wp-json/wp/v2/users/me",
            params={"context": "edit"},
            headers=_auth_header(override),
            timeout=15,
        )
        if r.status_code == 200:
            u = r.json()
            return {
                "auth_ok": True,
                "wp_url": url,
                "wp_user": user,
                "logged_in_as": u.get("name"),
                "slug": u.get("slug"),
                "roles": list(u.get("roles", [])),
                "can_edit_posts": u.get("capabilities", {}).get("edit_posts", False),
            }
        return {
            "auth_ok": False,
            "wp_url": url,
            "wp_user": user,
            "status_code": r.status_code,
            "error": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:300],
        }
    except Exception as e:
        return {"auth_ok": False, "wp_user": user, "exception": str(e)}


def _auth_header(override: dict | None = None) -> dict:
    _, user, pw = _creds(override)
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


# ── Post/page lookup ───────────────────────────────────────────────────────────

def _fetch_all_posts(post_type: str = "posts", per_page: int = 100, override: dict | None = None) -> list[dict]:
    """Fetch all posts of a given type with minimal fields."""
    url, _, _ = _creds(override)
    items, page = [], 1
    while True:
        try:
            r = httpx.get(
                f"{url}/wp-json/wp/v2/{post_type}",
                params={"per_page": per_page, "page": page,
                        "_fields": "id,link,slug,status"},
                headers=_auth_header(override),
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


def build_url_map(override: dict | None = None) -> dict[str, dict]:
    """Return {path → {id, type}} for all published WP posts and pages."""
    url_map: dict[str, dict] = {}
    for post_type in ("posts", "pages"):
        for item in _fetch_all_posts(post_type, override=override):
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

def get_post_content(post_id: int, post_type: str = "posts", override: dict | None = None) -> str | None:
    """Fetch raw post content via WP REST API (needs Gutenberg raw context)."""
    url, _, _ = _creds(override)
    try:
        r = httpx.get(
            f"{url}/wp-json/wp/v2/{post_type}/{post_id}",
            params={"context": "edit", "_fields": "id,content,title"},
            headers=_auth_header(override),
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
                      meta_desc: str | None = None,
                      override: dict | None = None) -> dict:
    """
    Update Yoast SEO title and/or meta description for a post.
    Returns {"ok": bool, "status_code": int}.
    """
    if not _is_configured(override):
        return {"ok": False, "reason": "WP credentials not configured"}
    wp_url, _, _ = _creds(override)
    meta = {}
    if title:
        meta["_yoast_wpseo_title"] = title
    if meta_desc:
        meta["_yoast_wpseo_metadesc"] = meta_desc
    if not meta:
        return {"ok": False, "reason": "nothing to update"}

    try:
        r = httpx.post(
            f"{wp_url}/wp-json/wp/v2/{post_type}/{post_id}",
            json={"meta": meta},
            headers=_auth_header(override),
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
                          anchor_text: str, target_url: str,
                          override: dict | None = None) -> dict:
    """
    Find `anchor_text` in post content and wrap the first occurrence with
    <a href="target_url">anchor_text</a> — only if not already linked.

    Returns {"ok": bool, "action": "injected"|"already_linked"|"anchor_not_found"|"error"}.
    """
    if not _is_configured(override):
        return {"ok": False, "action": "error", "reason": "WP credentials not configured"}
    wp_url, _, _ = _creds(override)
    content = get_post_content(post_id, post_type, override=override)
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
            f"{wp_url}/wp-json/wp/v2/{post_type}/{post_id}",
            json={"content": new_content},
            headers=_auth_header(override),
            timeout=30,
        )
        ok = r.status_code in (200, 201)
        return {"ok": ok, "action": "injected" if ok else "error",
                "status_code": r.status_code}
    except Exception as e:
        logger.warning("inject_internal_link %d error: %s", post_id, e)
        return {"ok": False, "action": "error", "reason": str(e)}


# ── Image alt-text update ─────────────────────────────────────────────────────

def update_image_alt(image_url: str, alt_text: str, override: dict | None = None) -> dict:
    """
    Find a WordPress media attachment by its source URL and update its alt text.
    Uses WP REST API: GET /wp/v2/media?search=<filename> → POST /wp/v2/media/<id>
    Returns {"ok": bool, ...}.
    """
    if not _is_configured(override):
        return {"ok": False, "reason": "WP credentials not configured"}

    wp_url, _, _ = _creds(override)
    filename = image_url.rstrip("/").split("/")[-1].split("?")[0]

    try:
        r = httpx.get(
            f"{wp_url}/wp-json/wp/v2/media",
            params={"search": filename, "per_page": 10, "_fields": "id,source_url"},
            headers=_auth_header(override),
            timeout=20,
        )
        r.raise_for_status()
        media = r.json()
    except Exception as e:
        return {"ok": False, "reason": f"media search failed: {e}"}

    # Find exact match on source_url
    attachment_id = None
    for m in media:
        if image_url in m.get("source_url", "") or filename in m.get("source_url", ""):
            attachment_id = m["id"]
            break

    if not attachment_id:
        return {"ok": False, "reason": f"attachment not found for {filename}"}

    try:
        r2 = httpx.post(
            f"{wp_url}/wp-json/wp/v2/media/{attachment_id}",
            json={"alt_text": alt_text},
            headers=_auth_header(override),
            timeout=20,
        )
        ok = r2.status_code in (200, 201)
        if not ok:
            logger.warning("update_image_alt %d failed %d", attachment_id, r2.status_code)
        return {"ok": ok, "status_code": r2.status_code, "attachment_id": attachment_id}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


# ── Batch action executor ──────────────────────────────────────────────────────

def execute_actions(actions: list[dict], override: dict | None = None) -> list[dict]:
    """
    Execute a list of structured actions against WordPress.
    Pass `override` dict with wp_url/wp_user/wp_app_password for per-site credentials.

    Supported action types ("type" or "action" key accepted):
      update_title       — {"url"|"page_url": "...", "title"|"new_value": "..."}
      update_meta_desc   — {"url"|"page_url": "...", "meta_desc"|"new_value": "..."}
      add_internal_link  — {"source_url": "...", "anchor_text": "...", "target_url": "..."}
      add_image_alt      — {"image_url": "...", "alt_text": "..."}

    Returns list of result dicts.
    """
    if not _is_configured(override):
        logger.warning("WP not configured — skipping %d actions", len(actions))
        return [{"action": a, "ok": False, "reason": "WP not configured"} for a in actions]

    url_map = build_url_map(override)
    results = []

    for action in actions:
        # Accept both "type" and "action" as the discriminator key
        atype = action.get("type") or action.get("action", "")
        # Accept both "url" and "page_url"
        page_url = action.get("url") or action.get("page_url", "")
        try:
            if atype in ("update_title", "update_meta_desc"):
                pid, ptype = find_post_id(page_url, url_map)
                if not pid:
                    results.append({"action": action, "ok": False,
                                    "reason": f"post not found for {page_url}"})
                    continue
                # Accept "title"/"meta_desc" or generic "new_value"
                title     = action.get("title")     or (action.get("new_value") if atype == "update_title"     else None)
                meta_desc = action.get("meta_desc") or (action.get("new_value") if atype == "update_meta_desc" else None)
                res = update_yoast_meta(
                    pid, ptype or "posts",
                    title=title, meta_desc=meta_desc, override=override,
                )
                results.append({"action": action, **res})

            elif atype == "add_internal_link":
                source_url  = action.get("source_url", page_url)
                anchor_text = action.get("anchor_text", "")
                target_url  = action.get("target_url", "")
                pid, ptype  = find_post_id(source_url, url_map)
                if not pid:
                    results.append({"action": action, "ok": False,
                                    "reason": f"source post not found for {source_url}"})
                    continue
                res = inject_internal_link(pid, ptype or "posts",
                                           anchor_text, target_url, override=override)
                results.append({"action": action, **res})

            elif atype == "add_image_alt":
                image_url = action.get("image_url", "")
                alt_text  = action.get("alt_text", "")
                if not image_url or not alt_text:
                    results.append({"action": action, "ok": False,
                                    "reason": "image_url and alt_text required"})
                    continue
                res = update_image_alt(image_url, alt_text, override=override)
                results.append({"action": action, **res})

            else:
                results.append({"action": action, "ok": False,
                                 "reason": f"unknown action type: {atype}"})

        except Exception as e:
            logger.error("execute_action %s error: %s", atype, e, exc_info=True)
            results.append({"action": action, "ok": False, "reason": str(e)})

    ok_count = sum(1 for r in results if r.get("ok"))
    logger.info("WP actions: %d/%d succeeded", ok_count, len(results))
    return results
