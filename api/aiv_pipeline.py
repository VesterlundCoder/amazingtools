"""
aiv_pipeline.py — AI Visibility pipeline for Amazing Tools.

No SBERT / no Ahrefs dependencies. Uses the configured model throughout.

Steps:
  1. Generate N Swedish prompts per persona using 4 types:
       - how_to, recommendation, comparison, brand_recommendation
     Brand-specific prompts (~35%) directly name the client/competitors.
  2. Run each prompt through OpenAI to capture AI response text
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
    return OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
        base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    )


def _normalize_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def _build_brand_prompts(
    client_name: str,
    competitor_names: list[str],
    services: list[str],
    region: str,
    persona: str,
) -> list[dict]:
    """Hard-coded brand-specific prompts that directly name the client/competitors."""
    prompts = []
    all_brands = [client_name] + competitor_names[:2]
    for svc in services[:2]:
        # Direct recommendation prompt for client
        prompts.append({
            "prompt_type": "brand_recommendation",
            "final_text": (
                f"Skulle du rekommendera {client_name} för {svc} i {region}? "
                f"Om inte, varför? Vilka andra leverantörer skulle du i så fall rekommendera?"
            ),
            "service": svc,
        })
        # Comparison prompt if competitors exist
        if competitor_names:
            comp = competitor_names[0]
            prompts.append({
                "prompt_type": "comparison",
                "final_text": (
                    f"Hur skiljer sig {client_name} från {comp} när det gäller {svc}? "
                    f"Vilken är bäst för ett {persona}-perspektiv i {region}?"
                ),
                "service": svc,
            })
        # Alternative/market prompt
        prompts.append({
            "prompt_type": "recommendation",
            "final_text": (
                f"Vilka {svc}-leverantörer rekommenderar du för {persona} i {region}? "
                f"Inkludera gärna {client_name} i jämförelsen."
            ),
            "service": svc,
        })
    return prompts


def _generate_prompts(
    client_name: str,
    client_url: str,
    competitor_names: list[str],
    personas: list[str],
    services: list[str],
    regions: list[str],
    num_per_persona: int,
) -> list[dict]:
    """Generate prompts: ~35% brand-specific + ~65% AI-generated generic/how-to."""
    oai = _client()
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    all_prompts: list[dict] = []
    prompt_id = 0

    for persona in personas:
        region_str = regions[0] if regions else "Sverige"
        service_str = ", ".join(services) if services else "tjänster"

        # ── Part A: brand-specific hard-coded prompts (~35%) ──────────────────
        brand_ps = _build_brand_prompts(client_name, competitor_names, services, region_str, persona)
        # Keep at most 35% of total budget as brand prompts
        brand_budget = max(2, round(num_per_persona * 0.35))
        for bp in brand_ps[:brand_budget]:
            all_prompts.append({
                "prompt_id":   f"P{prompt_id:03d}",
                "persona":     persona,
                "region":      region_str,
                **bp,
            })
            prompt_id += 1

        # ── Part B: AI-generated generic prompts (~65%) ───────────────────────
        generic_n = num_per_persona - min(len(brand_ps), brand_budget)
        system = (
            "Du genererar realistiska svenska B2B-frågor som en beslutsfattare (\"" + persona + "\") "
            "skulle ställa till en AI-assistent när de söker leverantörer. "
            "Svara ENBART med ett JSON-objekt: {\"prompts\": [\"fråga 1\", ...]}. "
            "Blanda: hur-gör-man-frågor (how_to), jämförelsefrågor (comparison) och "
            "rekommendationsfrågor (recommendation). Nämn gärna "
            + client_name + " eller tjänstekategorin i några av frågorna."
        )
        user = (
            f"Persona: {persona}\n"
            f"Tjänster: {service_str}\n"
            f"Region: {region_str}\n"
            f"Generera {generic_n} frågor."
        )
        try:
            resp = oai.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                max_tokens=1400,
                temperature=0.8,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            for i, q in enumerate(data.get("prompts", [])[:generic_n]):
                svc = services[i % len(services)] if services else ""
                all_prompts.append({
                    "prompt_id":   f"P{prompt_id:03d}",
                    "persona":     persona,
                    "service":     svc,
                    "region":      region_str,
                    "prompt_type": "generic",
                    "final_text":  str(q),
                })
                prompt_id += 1
        except Exception as e:
            logger.warning("Generic prompt generation failed for persona %s: %s", persona, e)

    return all_prompts


def _run_visibility(prompts: list[dict]) -> list[dict]:
    """Run each prompt through the model and record the answer text."""
    oai = _client()
    model = os.environ.get("OPENAI_CHAT_MODEL", "gpt-4o-mini")
    results = []
    system_msg = (
        "Du är en AI-assistent med god kunskap om den svenska B2B-marknaden, leverantörer, "
        "tjänsteföretag och branscher. När du svarar på frågor om leverantörer eller tjänster "
        "namnger du konkreta aktörer du känner till. Svara alltid på svenska och ge "
        "välgrundade, specifika svar."
    )
    for p in prompts:
        try:
            resp = oai.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user",   "content": p["final_text"]},
                ],
                max_tokens=500,
                temperature=0.6,
            )
            answer = resp.choices[0].message.content or ""
        except Exception as e:
            answer = f"[error: {e}]"
            logger.warning("Visibility check failed for %s: %s", p["prompt_id"], e)

        results.append({**p, "answer_text": answer})
        time.sleep(0.25)

    return results


def _brand_tokens(name: str) -> list[str]:
    """Return a list of strings, any of which counts as a mention of this brand."""
    tokens = [name.lower()]
    # Strip legal suffixes so "Amazing Group AB" also matches "Amazing Group"
    cleaned = re.sub(r"\s+(ab|hb|kb|as|inc|ltd|gmbh|llc|bv|oy)\.?$", "", name, flags=re.IGNORECASE).strip()
    if cleaned.lower() != name.lower():
        tokens.append(cleaned.lower())
    # First two words as abbreviation (e.g. "Amazing Group")
    parts = cleaned.split()
    if len(parts) >= 2:
        tokens.append(" ".join(parts[:2]).lower())
    return list(dict.fromkeys(tokens))


def _detect_mentions(results: list[dict], brand_names: list[str]) -> list[dict]:
    """Add boolean mention flags per brand to each result row."""
    brand_token_map = {b: _brand_tokens(b) for b in brand_names}
    out = []
    for r in results:
        text_lower = r["answer_text"].lower()
        flags = {
            f"mentions_{b.lower().replace(' ', '_')}": any(t in text_lower for t in toks)
            for b, toks in brand_token_map.items()
        }
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

    # Step 1 — generate prompts (brand-specific + generic mix)
    prompts = _generate_prompts(
        client_name=client_name, client_url=client_url,
        competitor_names=competitor_names,
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
