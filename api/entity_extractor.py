"""
entity_extractor.py — Phase 2: Lightweight SEO entity/topic extraction via GPT-4o-mini.

Extracts the main entities, topics, and target keywords from a page's text content.
Results are stored directly in each page dict as page["entities"] = [...].
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


def extract_entities(
    text: str,
    page_title: str,
    api_key: str,
    max_entities: int = 10,
) -> list[str]:
    """
    Extract the top SEO-relevant entities/topics from page text.

    Returns a list of keyword/topic strings, or [] on failure/insufficient content.
    """
    if not text or len(text) < 100:
        return []

    try:
        oai = OpenAI(api_key=api_key)
        resp = oai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": (
                    f"Page title: {page_title}\n"
                    f"Content (first 800 chars):\n{text[:800]}\n\n"
                    f"Extract the top {max_entities} main SEO-relevant entities, "
                    "topics, or target keywords from this page. "
                    "Return ONLY a JSON object: {\"entities\": [\"...\", ...]}. "
                    "No explanation."
                ),
            }],
            max_tokens=150,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw    = resp.choices[0].message.content.strip()
        parsed = json.loads(raw)

        if isinstance(parsed, list):
            return [str(e) for e in parsed[:max_entities]]
        for key in ("entities", "topics", "keywords", "items"):
            if isinstance(parsed.get(key), list):
                return [str(e) for e in parsed[key][:max_entities]]
        return []

    except Exception as e:
        logger.warning("Entity extraction failed: %s", e)
        return []


def extract_entities_for_pages(
    pages: list[dict],
    api_key: str,
    cap: int = 40,
    min_word_count: int = 150,
) -> None:
    """
    Mutate pages in-place: add 'entities' list to each qualifying page.

    Skips pages already having 'entities', non-200 pages, noindex, and thin content.
    Caps total API calls at `cap` to control cost.
    """
    processed = 0
    for page in pages:
        if processed >= cap:
            break
        if page.get("entities"):
            continue
        if (
            page.get("status_code") != 200
            or page.get("noindex")
            or (page.get("word_count") or 0) < min_word_count
        ):
            continue

        text  = page.get("text_sample") or page.get("h1", "")
        title = page.get("title", "")
        entities = extract_entities(text, title, api_key)
        if entities:
            page["entities"] = entities
            processed += 1

    logger.info("Entities extracted for %d pages", processed)
