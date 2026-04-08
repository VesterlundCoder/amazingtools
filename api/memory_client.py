"""
memory_client.py — Phase 4: RAG memory + reinforcement learning loop.

Storage: seo_memory table in the existing database (SQLite or PostgreSQL).
Embeddings: OpenAI text-embedding-3-small (1536 dims), stored as JSON TEXT.
Similarity: pure-Python cosine similarity (no pgvector needed; portable).

Reward cron: runs weekly, fetches new GSC data for actions taken 14-28 days ago,
computes reward_score = CTR_delta + position_improvement * 0.05, updates record.
"""
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_DIMS  = 1536


# ── Embedding helpers ──────────────────────────────────────────────────────────

def _embed(text: str, api_key: str) -> Optional[list[float]]:
    """Return OpenAI embedding vector, or None on failure."""
    try:
        from openai import OpenAI
        oai  = OpenAI(api_key=api_key)
        resp = oai.embeddings.create(model=_EMBED_MODEL, input=text[:8000])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning("Embedding failed: %s", e)
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot    = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── Store a new action memory ──────────────────────────────────────────────────

def store_action(
    engine,
    db_lock,
    site_url: str,
    page_url: str,
    action_type: str,
    action_value: str,
    context_text: str,
    before_metrics: dict,
    api_key: str,
    job_id: str = "",
) -> Optional[str]:
    """
    Embed context_text and insert a new seo_memory record.
    Returns memory ID or None on failure.
    """
    from sqlalchemy import text as sqla_text

    embedding = _embed(context_text, api_key)
    mem_id    = str(uuid.uuid4())[:8]
    now       = datetime.now(timezone.utc).isoformat()

    try:
        with db_lock:
            with engine.begin() as conn:
                conn.execute(sqla_text("""
                    INSERT INTO seo_memory
                        (id, site_url, page_url, action_type, action_value,
                         context_text, context_embedding,
                         before_metrics, after_metrics, reward_score,
                         job_id, action_taken_at)
                    VALUES
                        (:id, :site, :page, :atype, :aval,
                         :ctx, :emb,
                         :before, NULL, NULL,
                         :jid, :ts)
                """), {
                    "id":     mem_id,
                    "site":   site_url,
                    "page":   page_url,
                    "atype":  action_type,
                    "aval":   action_value[:500] if action_value else "",
                    "ctx":    context_text[:1000],
                    "emb":    json.dumps(embedding) if embedding else None,
                    "before": json.dumps(before_metrics),
                    "jid":    job_id,
                    "ts":     now,
                })
        return mem_id
    except Exception as e:
        logger.error("Memory store failed: %s", e)
        return None


# ── Retrieve similar memories ──────────────────────────────────────────────────

def retrieve_similar(
    engine,
    context_text: str,
    api_key: str,
    action_type: str = "",
    limit: int = 5,
    min_reward: float = 0.1,
) -> list[dict]:
    """
    Embed context_text and return the top `limit` stored actions with
    the highest (cosine similarity × reward_score) for the same action type.

    Returns [] when no embeddings exist or on any failure.
    """
    from sqlalchemy import text as sqla_text

    query_emb = _embed(context_text, api_key)
    if not query_emb:
        return []

    try:
        with engine.connect() as conn:
            rows = conn.execute(sqla_text("""
                SELECT id, site_url, page_url, action_type, action_value,
                       context_text, context_embedding, reward_score,
                       before_metrics, after_metrics
                FROM seo_memory
                WHERE reward_score IS NOT NULL
                  AND reward_score > :min_r
                  AND context_embedding IS NOT NULL
                  AND (:atype = '' OR action_type = :atype)
                ORDER BY reward_score DESC
                LIMIT 300
            """), {"min_r": min_reward, "atype": action_type}).mappings().fetchall()
    except Exception as e:
        logger.warning("Memory query failed: %s", e)
        return []

    scored: list[tuple[float, dict]] = []
    for row in rows:
        try:
            emb = json.loads(row["context_embedding"])
            sim = _cosine(query_emb, emb)
            scored.append((sim * float(row["reward_score"] or 0), dict(row)))
        except Exception:
            continue

    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def build_memory_prompt(memories: list[dict]) -> str:
    """Format retrieved memories into a concise prompt injection block."""
    if not memories:
        return ""
    lines = ["## Learned from past successful SEO actions:"]
    for m in memories:
        reward = m.get("reward_score") or 0
        lines.append(
            f"- [{m.get('action_type')}] Context: '{m.get('context_text', '')[:80]}' "
            f"→ value: '{m.get('action_value', '')[:80]}' (reward={reward:+.2f})"
        )
    return "\n".join(lines)


# ── Reward cron job ────────────────────────────────────────────────────────────

def run_reward_cron(engine, db_lock, api_key: str, lookback_days: int = 14) -> None:
    """
    Weekly job: for actions taken 14-28 days ago with no after_metrics,
    fetch fresh GSC data, compute reward, update record.

    reward_score = (after_ctr - before_ctr) + (before_pos - after_pos) * 0.05
    """
    from sqlalchemy import text as sqla_text
    import gsc_client

    cutoff_old = (datetime.now(timezone.utc) - timedelta(days=28)).isoformat()
    cutoff_new = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()

    try:
        with engine.connect() as conn:
            rows = conn.execute(sqla_text("""
                SELECT id, site_url, page_url, action_type, before_metrics
                FROM seo_memory
                WHERE after_metrics IS NULL
                  AND reward_score IS NULL
                  AND action_taken_at BETWEEN :old AND :new
                LIMIT 500
            """), {"old": cutoff_old, "new": cutoff_new}).mappings().fetchall()
    except Exception as e:
        logger.error("[reward-cron] Query failed: %s", e)
        return

    if not rows:
        logger.info("[reward-cron] No records to score")
        return

    logger.info("[reward-cron] Scoring %d action records", len(rows))

    # Group by site to minimise GSC API calls
    by_site: dict[str, list] = {}
    for row in rows:
        by_site.setdefault(row["site_url"], []).append(row)

    for site_url, site_rows in by_site.items():
        try:
            gsc_now = gsc_client.fetch_gsc_data(site_url)
        except Exception as e:
            logger.warning("[reward-cron] GSC fetch failed for %s: %s", site_url, e)
            continue

        for row in site_rows:
            page_url = row["page_url"]
            try:
                before    = json.loads(row["before_metrics"] or "{}")
                after     = gsc_now.get(page_url, {})
                if not after:
                    continue

                ctr_delta = float(after.get("gsc_ctr", 0))      - float(before.get("gsc_ctr", 0))
                pos_delta = float(before.get("gsc_position", 100)) - float(after.get("gsc_position", 100))
                reward    = round(ctr_delta + pos_delta * 0.05, 4)
                now       = datetime.now(timezone.utc).isoformat()

                with db_lock:
                    with engine.begin() as conn:
                        conn.execute(sqla_text("""
                            UPDATE seo_memory
                            SET after_metrics=:after,
                                reward_score=:reward,
                                reward_computed_at=:ts
                            WHERE id=:id
                        """), {
                            "after":  json.dumps(after),
                            "reward": reward,
                            "ts":     now,
                            "id":     row["id"],
                        })
            except Exception as e:
                logger.warning("[reward-cron] Reward calc failed for %s: %s", page_url, e)

    logger.info("[reward-cron] Complete")
