"""
vision_client.py — Phase 2: GPT-4o Vision alt-text generator for images missing alt attributes.

For each qualifying image URL, downloads the image and asks GPT-4o Vision to
produce a concise, SEO-friendly alt text (<= 125 chars).

New action produced: {"type": "add_image_alt", "page_url": "...", "image_url": "...", "alt_text": "..."}
"""
from __future__ import annotations

import base64
import logging
import time
from typing import Optional

import os

import httpx
from openai import OpenAI

logger = logging.getLogger(__name__)

_VISION_MODEL = os.environ.get("OPENAI_VISION_MODEL", "gpt-4o")
_MAX_ALT_LEN  = 125


def _image_to_data_url(image_url: str, timeout: int = 15) -> Optional[str]:
    """Download image and return a base64 data-URL string."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
            r = c.get(image_url)
            r.raise_for_status()
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            b64 = base64.b64encode(r.content).decode()
            return f"data:{ct};base64,{b64}"
    except Exception as e:
        logger.debug("Vision: could not fetch image %s: %s", image_url, e)
        return None


def generate_alt_text(
    image_url: str,
    page_title: str,
    page_context: str,
    api_key: str,
) -> Optional[str]:
    """
    Download image_url and call GPT-4o Vision to generate SEO alt text.
    Returns a string (<= 125 chars) or None on failure.
    """
    data_url = _image_to_data_url(image_url)
    if not data_url:
        return None

    try:
        oai = OpenAI(api_key=api_key, base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
        resp = oai.chat.completions.create(
            model=_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Page title: {page_title}\n"
                            f"Page context: {page_context[:200]}\n\n"
                            "Write one concise, SEO-friendly alt text for this image "
                            f"(max {_MAX_ALT_LEN} characters). "
                            "Describe what is shown and relate it to the page topic. "
                            "No quotes, no leading/trailing whitespace."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "low"},
                    },
                ],
            }],
            max_tokens=60,
        )
        alt = resp.choices[0].message.content.strip().strip('"').strip("'")
        return alt[:_MAX_ALT_LEN] if alt else None
    except Exception as e:
        logger.warning("Vision: alt generation failed for %s: %s", image_url, e)
        return None


def generate_alt_texts_for_job(
    pages: list[dict],
    api_key: str,
    cap_per_page: int = 3,
    cap_total: int = 30,
    delay_s: float = 0.5,
) -> list[dict]:
    """
    Scan pages for images without alt text; generate add_image_alt actions.

    Args:
        pages:        List of crawled page dicts (must contain 'images_without_alt_urls').
        cap_per_page: Max images to process per page.
        cap_total:    Hard cap on total OpenAI Vision calls.

    Returns:
        List of {"type": "add_image_alt", "page_url", "image_url", "alt_text"} dicts.
    """
    actions: list[dict] = []
    total   = 0

    for page in pages:
        if total >= cap_total:
            break
        if page.get("status_code") != 200 or page.get("noindex"):
            continue

        img_urls: list[str] = page.get("images_without_alt_urls") or []
        if not img_urls:
            continue

        page_url  = page.get("url", "")
        page_title = page.get("title", "")
        page_ctx   = page.get("h1") or page.get("text_sample", "")

        for img_url in img_urls[:cap_per_page]:
            if total >= cap_total:
                break
            alt = generate_alt_text(img_url, page_title, page_ctx, api_key)
            if alt:
                actions.append({
                    "type":      "add_image_alt",
                    "page_url":  page_url,
                    "image_url": img_url,
                    "alt_text":  alt,
                })
                total += 1
                time.sleep(delay_s)

    logger.info("Vision: generated %d alt-text actions", total)
    return actions
