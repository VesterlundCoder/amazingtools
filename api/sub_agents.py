"""
sub_agents.py — Phase 3: Specialized SEO sub-agents.

Tech SEO Agent:    status codes, CWV, broken links → markdown recommendations text
Content SEO Agent: titles, CTR (GSC), entities, word counts → JSON rewrite actions
Master Agent:      merges outputs, prioritises, caps at max_actions (default 40)
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI

logger = logging.getLogger(__name__)


# ── Tech SEO Agent ─────────────────────────────────────────────────────────────

def run_tech_seo_agent(
    pages: list[dict],
    metrics: dict,
    client_url: str,
    oai: OpenAI,
) -> str:
    """
    Focused GPT-4o call: status codes, Core Web Vitals, broken links.
    Returns a short markdown recommendations string.
    """
    bad_status = [p for p in pages if (p.get("status_code") or 200) >= 400]
    bad_lcp    = [p for p in pages if (p.get("psi_lcp_ms") or 0) > 2500]
    bad_cls    = [p for p in pages if (p.get("psi_cls")    or 0) > 0.1]
    bad_inp    = [p for p in pages if (p.get("psi_inp_ms") or 0) > 200]
    broken_src = [p for p in pages if p.get("broken_links")]

    lines = [
        f"Site: {client_url}",
        f"Total pages: {metrics.get('total_pages', 0)}",
        f"4xx: {metrics.get('pages_4xx', 0)}  5xx: {metrics.get('pages_5xx', 0)}  "
        f"broken internal links: {metrics.get('broken_links', 0)}",
        "",
    ]
    if bad_status:
        lines.append("HTTP error pages (first 10):")
        for p in bad_status[:10]:
            lines.append(f"  {p.get('status_code')}  {p.get('url', '')}")
        lines.append("")

    cwv_issues = list({p["url"]: p for p in bad_lcp + bad_cls + bad_inp}.values())[:15]
    if cwv_issues:
        lines.append("Core Web Vitals issues:")
        for p in cwv_issues:
            lines.append(
                f"  score={p.get('psi_score')}  "
                f"LCP={p.get('psi_lcp_ms')}ms  CLS={p.get('psi_cls')}  "
                f"INP={p.get('psi_inp_ms')}ms  {p.get('url', '')}"
            )
        lines.append("")

    if broken_src:
        lines.append("Pages with broken outbound links (first 10):")
        for p in broken_src[:10]:
            bl = (p.get("broken_links") or [])[:3]
            lines.append(f"  {p.get('url', '')} → {bl}")
        lines.append("")

    try:
        resp = oai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical SEO expert specialising in Core Web Vitals and site health.\n\n"
                        "CWV thresholds (75th percentile field data):\n"
                        "  LCP: ≤2.5s good | ≤4.0s needs improvement | >4.0s poor\n"
                        "  INP: ≤200ms good | ≤500ms needs improvement | >500ms poor\n"
                        "  CLS: ≤0.1 good | ≤0.25 needs improvement | >0.25 poor\n\n"
                        "Common LCP causes: unoptimised hero image (no preload), render-blocking CSS/JS, "
                        "slow TTFB (>600ms), no CDN, missing srcset for responsive images.\n"
                        "Common INP causes: long tasks >50ms on main thread, heavy third-party scripts "
                        "(chat widgets, tag managers), synchronous event handlers, large React re-renders.\n"
                        "Common CLS causes: images without width/height attributes, late-loading fonts "
                        "(FOIT/FOUT), cookie/consent banners without reserved space, ads without dimensions.\n\n"
                        "Quick wins by effort:\n"
                        "  Easy: add width/height to images, font-display:swap, preconnect hints\n"
                        "  Medium: preload LCP image, inline critical CSS, lazy-load below-fold images\n"
                        "  Hard: reduce JS bundle, fix long tasks, upgrade hosting/CDN\n\n"
                        "Analyse the data and provide concise, prioritised technical recommendations. "
                        "For CWV failures, state the specific metric value, threshold breached, "
                        "most likely root cause, and exact fix. Be specific about which pages to fix."
                    ),
                },
                {"role": "user", "content": "\n".join(lines)},
            ],
            max_tokens=800,
            temperature=0.3,
        )
        result = resp.choices[0].message.content.strip()
        logger.info("[tech-agent] Done (%d chars)", len(result))
        return result
    except Exception as e:
        logger.error("[tech-agent] Failed: %s", e)
        return ""


# ── Content SEO Agent ──────────────────────────────────────────────────────────

def run_content_seo_agent(
    pages: list[dict],
    client_url: str,
    oai: OpenAI,
    memory_context: str = "",
) -> list[dict]:
    """
    Focused GPT-4o call: titles, GSC CTR/position, entities, word counts.
    Generates update_title / update_meta_desc actions for underperforming pages.
    Returns list of action dicts.
    """
    candidates = [
        p for p in pages
        if p.get("status_code") == 200
        and not p.get("noindex")
        and (
            not p.get("title")
            or not p.get("meta_description")
            or (p.get("gsc_impressions") or 0) >= 20
        )
    ][:50]

    if not candidates:
        return []

    page_data = [
        {
            "url":        p.get("url", ""),
            "title":      p.get("title", ""),
            "meta_desc":  p.get("meta_description", ""),
            "h1":         p.get("h1", ""),
            "word_count": p.get("word_count", 0),
            "gsc_ctr":    p.get("gsc_ctr"),
            "gsc_pos":    p.get("gsc_position"),
            "gsc_imp":    p.get("gsc_impressions"),
            "entities":   p.get("entities", [])[:6],
        }
        for p in candidates
    ]

    system_msg = (
        "You are a Content SEO expert. Analyse the following pages and generate "
        "JSON actions to improve underperforming titles and meta descriptions.\n"
        "Focus on: (1) low CTR pages with >= 20 impressions, (2) missing tags, "
        "(3) pages where extracted entities suggest a stronger keyword angle.\n"
        "Rules: titles max 60 chars 'Keyword — Site Name' style; "
        "meta descriptions 140-155 chars, compelling, include keyword. "
        "Match the language of the page content.\n"
        "Return ONLY a JSON object: {\"actions\": [{\"type\": \"update_title\"|\"update_meta_desc\", "
        "\"url\": \"...\", \"title\": \"...\"|\"meta_desc\": \"...\"}]}"
    )
    if memory_context:
        system_msg += f"\n\n{memory_context}"

    try:
        resp = oai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": json.dumps(page_data, ensure_ascii=False)},
            ],
            max_tokens=3000,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        parsed = json.loads(resp.choices[0].message.content.strip())
        actions = parsed if isinstance(parsed, list) else parsed.get("actions", [])
        logger.info("[content-agent] Generated %d actions", len(actions))
        return actions if isinstance(actions, list) else []
    except Exception as e:
        logger.error("[content-agent] Failed: %s", e)
        return []


# ── Master Agent ───────────────────────────────────────────────────────────────

def run_master_agent(
    tech_text: str,
    content_actions: list[dict],
    extra_actions: list[dict],
    client_url: str,
    oai: OpenAI,
    max_actions: int = 40,
) -> tuple[str, list[dict]]:
    """
    Merge Tech + Content + extra (vision) outputs.
    Prioritise by expected SEO impact, cap at max_actions.

    Returns (analysis_text, final_actions_list).
    """
    all_candidates = content_actions + extra_actions

    prompt = (
        f"Site: {client_url}\n\n"
        f"Technical SEO findings:\n{tech_text or '(none)'}\n\n"
        f"Proposed actions ({len(all_candidates)} total):\n"
        f"{json.dumps(all_candidates[:60], ensure_ascii=False)}\n\n"
        f"Task:\n"
        f"1. Write a 3-5 sentence overall SEO analysis (key: \"analysis\").\n"
        f"2. Return the top {max_actions} most impactful actions in priority order "
        f"(key: \"actions\"). Deduplicate. Prefer: missing tags > low-CTR rewrites > "
        f"internal links > alt texts.\n"
        f"Return ONLY a JSON object: {{\"analysis\": \"...\", \"actions\": [...]}}"
    )

    try:
        resp = oai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a senior SEO strategist. Prioritise actions by expected ROI.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=4000,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        parsed   = json.loads(resp.choices[0].message.content.strip())
        analysis = parsed.get("analysis", tech_text[:400])
        actions  = parsed.get("actions", all_candidates)
        logger.info("[master-agent] Final: %d actions", len(actions))
        return analysis, (actions if isinstance(actions, list) else all_candidates)[:max_actions]
    except Exception as e:
        logger.error("[master-agent] Failed: %s", e)
        return tech_text[:400], all_candidates[:max_actions]
