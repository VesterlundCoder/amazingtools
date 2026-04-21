"""brand_voice_agent.py — Three-module Brand Voice Agent."""
from __future__ import annotations
import json, logging, os, re
from openai import OpenAI

logger = logging.getLogger(__name__)

DIMS = [
    ("v1_authority",        "Authority",         "0=Peer → 1=Absolute Expert"),
    ("v2_warmth",           "Warmth",            "0=Clinical → 1=Deeply Empathetic"),
    ("v3_formality",        "Formality",         "0=Colloquial → 1=Academic"),
    ("v4_energy",           "Energy",            "0=Placid → 1=Kinetic"),
    ("v5_persuasiveness",   "Persuasiveness",    "0=Passive → 1=Urgent"),
    ("v6_emotionality",     "Emotionality",      "0=Stoic → 1=Highly Expressive"),
    ("v7_specificity",      "Specificity",       "0=Abstract → 1=Hyper-concrete"),
    ("v8_jargon",           "Jargon",            "0=Layman → 1=Niche Specialist"),
    ("v9_syntax_complexity","Syntax Complexity",  "0=Staccato → 1=Flowing/Compound"),
    ("v10_pov",             "POV",               "0=Brand-centric (We) → 1=Customer-centric (You)"),
]

def _oai(api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url)

def _parse_json(raw: str) -> dict:
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError("No JSON object found in response")

# ── Module 1: Builder ────────────────────────────────────────────────────────

def build_voice_profile(sample_texts: list[str], brand_name: str,
                        api_key: str, base_url: str, model: str) -> dict:
    dim_lines = "\n".join(f'    "{k}": <0.0-1.0>,  // {lbl}: {desc}' for k, lbl, desc in DIMS)
    samples_block = "\n\n---\n".join(f"SAMPLE {i+1}:\n{t.strip()}" for i, t in enumerate(sample_texts[:5]))

    prompt = f"""You are an expert brand voice analyst.
Analyze these brand text samples and extract the brand's voice profile.
Return ONLY valid JSON — no markdown, no explanation.

Brand name: {brand_name or 'Unknown'}

SAMPLES:
{samples_block}

JSON format:
{{
  "brand_name": "{brand_name}",
  "summary": "<2-3 sentences describing the brand voice>",
  "vector": {{
{dim_lines}
  }},
  "lexical": {{
    "required": ["<characteristic words/phrases>"],
    "taboo": ["<clichés or off-brand phrases to avoid>"]
  }}
}}"""

    resp = _oai(api_key, base_url).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900, temperature=0.3,
    )
    return _parse_json(resp.choices[0].message.content)


# ── Module 2: Auditor ────────────────────────────────────────────────────────

def audit_text(text: str, profile: dict, weights: dict | None,
               api_key: str, base_url: str, model: str) -> dict:
    vec_str = json.dumps(profile.get("vector", {}), indent=2)
    w = weights or {k: 1.0 for k, *_ in DIMS}
    prompt = f"""You are a brand voice auditor. Measure how well this text matches the target brand voice.
Return ONLY valid JSON.

TARGET VECTOR:
{vec_str}

LEXICAL TABOO: {json.dumps(profile.get('lexical', {}).get('taboo', []))}

TEXT TO AUDIT:
{text.strip()}

JSON format:
{{
  "actual_vector": {{ <same keys as target, 0.0-1.0> }},
  "delta_vector":  {{ <target minus actual for each key> }},
  "divergence_score": <0.0-1.0 weighted distance>,
  "flagged": <true if divergence_score > 0.35>,
  "dimension_analysis": [
    {{"key": "<dim_key>", "label": "<dim label>", "target": 0.0, "actual": 0.0, "delta": 0.0, "note": "<1-sentence insight>"}}
  ],
  "overall_feedback": "<2-3 sentence summary of gaps>"
}}"""

    resp = _oai(api_key, base_url).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=900, temperature=0.2,
    )
    return _parse_json(resp.choices[0].message.content)


# ── Module 3: Rewriter ───────────────────────────────────────────────────────

def rewrite_text(text: str, profile: dict, audit_result: dict | None,
                 api_key: str, base_url: str, model: str) -> dict:
    vec_str  = json.dumps(profile.get("vector", {}), indent=2)
    taboo    = profile.get("lexical", {}).get("taboo", [])
    required = profile.get("lexical", {}).get("required", [])
    delta    = json.dumps(audit_result.get("delta_vector", {}) if audit_result else {}, indent=2)
    wc       = len(text.split())
    lo, hi   = max(20, int(wc * 0.8)), int(wc * 1.3)

    prompt = f"""You are a brand copywriter. Rewrite the text to match the brand voice vector below.
Return ONLY valid JSON.

TARGET VECTOR:
{vec_str}

DELTA TO CLOSE (positive = needs more of that dimension):
{delta}

HARD CONSTRAINTS:
1. Preserve ALL factual claims and named entities.
2. NEVER use these words/phrases: {json.dumps(taboo)}
3. Prefer these words/phrases: {json.dumps(required)}
4. Word count: {lo}–{hi} words.

ORIGINAL TEXT:
{text.strip()}

JSON format:
{{
  "rewritten": "<rewritten text>",
  "qa": {{
    "semantic_preserved": <true/false>,
    "taboo_clean": <true/false>,
    "length_ok": <true/false>,
    "qa_passed": <true if all three>
  }},
  "new_vector_estimate": {{ <estimated scores after rewrite, 0.0-1.0> }},
  "changes_summary": "<1-2 sentences on main changes made>"
}}"""

    resp = _oai(api_key, base_url).chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1200, temperature=0.5,
    )
    return _parse_json(resp.choices[0].message.content)
