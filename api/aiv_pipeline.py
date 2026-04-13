"""
aiv_pipeline.py — Simplified AI Visibility pipeline for Amazing Tools.

No SBERT / no Ahrefs dependencies. Uses GPT-4o-mini throughout.

Steps:
  1. Generate N Swedish prompts per persona × service combination (GPT-4o-mini)
  2. Run each prompt through OpenAI to capture AI response text (GPT-4o-mini)
  3. Detect brand mentions using case-insensitive string matching
  4. Compute KPIs: mention rate, Share of Voice, by-persona / by-service breakdown
  5. Identify visibility gaps and return JSON result
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import urlparse

from openai import OpenAI

logger = logging.getLogger(__name__)


def _client() -> OpenAI:
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


def _normalize_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _generate_prompts(
    client_name: str,
    client_url: str,
    personas: list[str],
    services: list[str],
    regions: list[str],
    num_per_persona: int,
) -> list[dict]:
    """Use GPT-4o-mini to generate realistic B2B Swedish queries."""
    oai = _client()
    all_prompts: list[dict] = []
    prompt_id = 0

    for persona in personas:
        region_str = regions[0] if regions else "Sverige"
        service_str = ", ".join(services) if services else "tjänster"

        system = (
            "Du genererar realistiska svenska B2B-frågor som en beslutsfattare skulle ställa till ChatGPT. "
            "Svara ENBART med ett JSON-objekt: {\"prompts\": [\"fråga 1\", \"fråga 2\", ...]}. "
            "Frågorna ska variera: informationsfrågor, jämförelsefrågor och beslutsfrågor."
        )
        user = (
            f"Persona: {persona}\n"
            f"Tjänster: {service_str}\n"
            f"Region: {region_str}\n"
            f"Generera {num_per_persona} frågor."
        )
        try:
            resp = oai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=1200,
                temperature=0.8,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            for q in data.get("prompts", [])[:num_per_persona]:
                service = services[prompt_id % len(services)] if services else ""
                all_prompts.append({
                    "prompt_id": f"P{prompt_id:03d}",
                    "persona": persona,
                    "service": service,
                    "region": region_str,
                    "final_text": str(q),
                })
                prompt_id += 1
        except Exception as e:
            logger.warning("Prompt generation failed for persona %s: %s", persona, e)

    return all_prompts


def _run_visibility(prompts: list[dict]) -> list[dict]:
    """Run each prompt through GPT-4o-mini and record the answer text."""
    oai = _client()
    results = []
    for p in prompts:
        try:
            resp = oai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{
                    "role": "user",
                    "content": (
                        "Svara på svenska. Du pratar med en beslutsfattare i B2B. "
                        "Ge ett hjälpsamt och informativt svar.\n\n"
                        f"Fråga: {p['final_text']}"
                    )
                }],
                max_tokens=400,
                temperature=0.7,
            )
            answer = resp.choices[0].message.content or ""
        except Exception as e:
            answer = f"[error: {e}]"
            logger.warning("Visibility check failed for %s: %s", p["prompt_id"], e)

        results.append({**p, "answer_text": answer})
        time.sleep(0.3)  # basic rate limiting

    return results


def _detect_mentions(results: list[dict], brand_names: list[str]) -> list[dict]:
    """Add boolean mention flags per brand to each result row."""
    out = []
    for r in results:
        text_lower = r["answer_text"].lower()
        flags = {f"mentions_{b.lower().replace(' ', '_')}": b.lower() in text_lower
                 for b in brand_names}
        out.append({**r, **flags})
    return out


def _compute_metrics(
    results: list[dict],
    client_name: str,
    competitor_names: list[str],
) -> dict:
    """Compute brand mention rates, SoV, and persona/service breakdowns."""
    all_brands = [client_name] + competitor_names
    total = max(len(results), 1)

    def mention_count(name: str) -> int:
        key = f"mentions_{name.lower().replace(' ', '_')}"
        return sum(1 for r in results if r.get(key))

    counts = {b: mention_count(b) for b in all_brands}
    total_mentions = max(sum(counts.values()), 1)

    brands_out = []
    for b in all_brands:
        c = counts[b]
        brands_out.append({
            "name": b,
            "type": "client" if b == client_name else "competitor",
            "mention_rate": round(c / total, 3),
            "sov_mentions": round(c / total_mentions, 3),
            "prompts_with_mentions": c,
        })

    client_key = f"mentions_{client_name.lower().replace(' ', '_')}"

    # By persona
    personas = sorted({r["persona"] for r in results})
    by_persona = []
    for persona in personas:
        subset = [r for r in results if r["persona"] == persona]
        rate = sum(1 for r in subset if r.get(client_key)) / max(len(subset), 1)
        by_persona.append({"persona": persona, "mention_rate": round(rate, 3), "prompts": len(subset)})

    # By service
    services = sorted({r.get("service", "") for r in results if r.get("service")})
    by_service = []
    for svc in services:
        subset = [r for r in results if r.get("service") == svc]
        rate = sum(1 for r in subset if r.get(client_key)) / max(len(subset), 1)
        by_service.append({"service": svc, "mention_rate": round(rate, 3)})

    # Visibility gaps
    gaps = []
    for bp in by_persona:
        if bp["mention_rate"] < 0.3:
            gaps.append(f"Low visibility for {bp['persona']} persona (mention rate {bp['mention_rate']:.0%})")
    for bs in by_service:
        if bs["mention_rate"] < 0.3:
            gaps.append(f"Low visibility for service '{bs['service']}' (mention rate {bs['mention_rate']:.0%})")
    for b in brands_out:
        if b["type"] == "competitor" and b["mention_rate"] > counts[client_name] / total * 1.5:
            gaps.append(f"{b['name']} has {b['mention_rate']:.0%} mention rate vs your {counts[client_name] / total:.0%} — content gap")

    # Sample responses (5 mixed)
    samples = []
    mentioned = [r for r in results if r.get(client_key)][:3]
    not_mentioned = [r for r in results if not r.get(client_key)][:2]
    for r in mentioned + not_mentioned:
        samples.append({
            "prompt": r["final_text"],
            "answer": r["answer_text"][:300] + ("…" if len(r["answer_text"]) > 300 else ""),
            "mentions_client": bool(r.get(client_key)),
        })

    avg_len = round(sum(len(r["answer_text"]) for r in results) / total)
    client_mention_rate = counts[client_name] / total

    return {
        "summary": {
            "total_prompts": total,
            "client_mention_rate": round(client_mention_rate, 3),
            "client_sov_mentions": round(counts[client_name] / total_mentions, 3),
            "avg_response_length": avg_len,
        },
        "brands":         brands_out,
        "by_persona":     by_persona,
        "by_service":     by_service,
        "visibility_gaps": gaps[:5],
        "sample_responses": samples,
    }


def run_aiv_pipeline(
    client_name: str,
    client_url: str,
    personas: list[str],
    services: list[str],
    regions: list[str],
    competitor_names: list[str],
    competitor_urls: list[str],
    num_prompts: int = 10,
) -> dict:
    """
    Full simplified AIV pipeline.

    Returns a dict with summary, brands, by_persona, by_service,
    visibility_gaps, and sample_responses.
    """
    import time as _time
    run_id = f"{client_name.replace(' ', '_')}_{int(_time.time())}"

    logger.info("[AIV] Starting run %s — %d prompts × %d personas", run_id, num_prompts, len(personas))

    # Step 1 — generate prompts
    prompts = _generate_prompts(
        client_name=client_name, client_url=client_url,
        personas=personas or ["Decision Maker"],
        services=services or ["main service"],
        regions=regions or ["Sweden"],
        num_per_persona=num_prompts,
    )
    if not prompts:
        return {"error": "Prompt generation failed — no prompts created.", "run_id": run_id}

    # Step 2 — run visibility checks
    results_raw = _run_visibility(prompts)

    # Step 3 — detect mentions
    all_brands = [client_name] + competitor_names
    results = _detect_mentions(results_raw, all_brands)

    # Step 4 — compute metrics
    metrics = _compute_metrics(results, client_name, competitor_names)

    return {
        "client":  client_name,
        "run_id":  run_id,
        **metrics,
    }
