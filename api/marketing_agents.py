"""
marketing_agents.py — Seven marketing intelligence agents for Amazing Tools.

Agents:
  landing-page   CRO review (messaging, trust, UX, differentiation)
  competitor     Competitor research (positioning, pricing, market gaps)
  ad-copy        Ad copy generation (Google / Meta / LinkedIn)
  lead-qual      Lead qualification (ICP scoring + next steps)
  cwv            Core Web Vitals audit (LCP/INP/CLS + fix plan)
  utm            UTM framework builder (naming, channel grouping rules)
  conversion     Conversion tracking debugger (GTM/GA4/Ads/Meta)

Each agent exposes:
  AGENT_ID, DISPLAY_NAME, ICON, DESCRIPTION, INPUTS   — metadata for UI
  run(input_data: dict, use_dummy: bool = False) -> dict
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from openai import OpenAI

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "Mozilla/5.0 AmazingTools/1.0"}


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _oai() -> OpenAI:
    return OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))


def _fetch_text(url: str, max_chars: int = 6000) -> str:
    """Fetch a URL and return clean text content."""
    try:
        with httpx.Client(timeout=20, headers=_HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            for el in soup(["script", "style", "nav", "footer", "header"]):
                el.decompose()
            raw = " ".join(soup.get_text(" ", strip=True).split())
            return raw[:max_chars]
    except Exception as e:
        logger.warning("fetch_text failed for %s: %s", url, e)
        return f"[fetch error: {e}]"


def _fetch_html(url: str) -> str:
    """Return raw HTML (trimmed) for meta/title analysis."""
    try:
        with httpx.Client(timeout=20, headers=_HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return r.text[:40000]
    except Exception as e:
        return f"[fetch error: {e}]"


def _ddg_search(query: str, n: int = 5) -> str:
    """DuckDuckGo HTML search — returns top n result titles/snippets."""
    try:
        with httpx.Client(timeout=12, headers=_HEADERS) as c:
            r = c.get("https://html.duckduckgo.com/html/", params={"q": query})
            soup = BeautifulSoup(r.text, "lxml")
            items = []
            for div in soup.select(".result")[:n]:
                title = div.select_one(".result__a")
                snip  = div.select_one(".result__snippet")
                if title:
                    items.append(f"• {title.get_text(strip=True)}: {snip.get_text(strip=True) if snip else ''}")
            return "\n".join(items) if items else "No results found."
    except Exception as e:
        return f"[search error: {e}]"


def _gpt(system: str, user: str, max_tokens: int = 2000, json_mode: bool = True) -> dict | str:
    oai = _oai()
    kwargs = dict(
        model="gpt-4o",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0.3,
    )
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = oai.chat.completions.create(**kwargs)
    raw = resp.choices[0].message.content.strip()
    if json_mode:
        return json.loads(raw)
    return raw


# ── Agent 1: Landing Page Reviewer ─────────────────────────────────────────────

class LandingPageAgent:
    AGENT_ID     = "landing-page"
    DISPLAY_NAME = "Landing Page Reviewer"
    ICON         = "🎯"
    DESCRIPTION  = "CRO audit: messaging clarity, trust signals, CTA effectiveness, and top 5 conversion improvements."
    INPUTS = [
        {"key": "url", "label": "Landing Page URL", "placeholder": "https://example.com/pricing", "type": "url"},
    ]
    DUMMY = {
        "url": "https://example.com/pricing", "score": 62, "is_dummy": True,
        "sections": {
            "messaging": {"score": 18, "max": 30, "items": [
                {"label": "Headline clarity",      "score": 7,  "feedback": "Value stated but lacks specificity — no numbers or timeframe"},
                {"label": "Value prop specificity","score": 5,  "feedback": "'Powerful' and 'easy' are vague — use quantified claims"},
                {"label": "CTA strength",          "score": 6,  "feedback": "'Get started' is generic — try 'Start Free 14-Day Trial'"},
            ]},
            "trust": {"score": 16, "max": 30, "items": [
                {"label": "Social proof",       "score": 6, "feedback": "Has text testimonials but no logos or case study results"},
                {"label": "Credibility signals","score": 6, "feedback": "No security badge, no visible pricing, no refund policy"},
                {"label": "Transparency",       "score": 4, "feedback": "No contact info or terms link visible above fold"},
            ]},
            "ux": {"score": 14, "max": 20, "items": [
                {"label": "Form friction","score": 7, "feedback": "8-field signup form — reduce to email + name minimum"},
                {"label": "Mobile UX",   "score": 7, "feedback": "Primary CTA not visible without scrolling on mobile"},
            ]},
            "differentiation": {"score": 14, "max": 20, "items": [
                {"label": "vs Competitor A","score": 7, "feedback": "They lead with speed claims — you don't counter this"},
                {"label": "vs Competitor B","score": 7, "feedback": "You have more integrations — highlight this visibly"},
            ]},
        },
        "top_changes": [
            {"priority": 1, "change": "Reduce signup form from 8 to 2 fields (email + name only)", "impact": "Est. +25–35% form conversion rate"},
            {"priority": 2, "change": "Replace 'Get started' with 'Start your free 14-day trial'", "impact": "Est. +10–15% CTA click-through"},
            {"priority": 3, "change": "Add 3–5 customer logos in the hero section",               "impact": "Reduces bounce, increases trust"},
            {"priority": 4, "change": "Show starting price on this page to qualify leads",         "impact": "Better lead quality, fewer unqualified demos"},
            {"priority": 5, "change": "Add FAQ block addressing top 3 sales objections",           "impact": "Reduces pre-sales questions, lifts conversion"},
        ],
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return LandingPageAgent.DUMMY
        url  = input_data.get("url", "")
        text = _fetch_text(url, max_chars=6000)
        domain = re.sub(r"https?://(www\.)?", "", url).split("/")[0]
        comps  = _ddg_search(f'{domain} site:competitor OR alternatives pricing', n=3)
        system = (
            "You are a CRO expert. Analyze the landing page and return a JSON audit with this schema:\n"
            '{"url":"","score":0-100,"sections":{"messaging":{"score":0-30,"max":30,"items":[{"label":"","score":0-10,"feedback":""}]},'
            '"trust":{"score":0-30,"max":30,"items":[...]},"ux":{"score":0-20,"max":20,"items":[...]},'
            '"differentiation":{"score":0-20,"max":20,"items":[]}},'
            '"top_changes":[{"priority":1,"change":"","impact":""},...up to 5]}\n'
            "Be specific about which elements are missing or weak. Reference actual page content."
        )
        user  = f"URL: {url}\n\nPage content:\n{text}\n\nCompetitor context:\n{comps}"
        try:
            result = _gpt(system, user, max_tokens=2000)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "url": url, "is_dummy": False}


# ── Agent 2: Competitor Analyst ────────────────────────────────────────────────

class CompetitorAgent:
    AGENT_ID     = "competitor"
    DISPLAY_NAME = "Competitor Analyst"
    ICON         = "🔭"
    DESCRIPTION  = "Research 4–6 competitors: positioning, pricing, strengths, market gaps, and where you should attack."
    INPUTS = [
        {"key": "query", "label": "Your URL or market category", "placeholder": "yoursite.com  or  'project management tools'", "type": "text"},
    ]
    DUMMY = {
        "query": "marketing automation tools", "is_dummy": True,
        "competitors": [
            {"name": "HubSpot",   "tagline": "Everything you need to grow better", "audience": "SMB/Mid-market", "pricing": "$45–$3,200/mo", "strength": "All-in-one CRM + marketing"},
            {"name": "ActiveCampaign","tagline":"Grow your business with customer experience automation","audience":"SMB","pricing":"$29–$149/mo","strength":"Email automation depth"},
            {"name": "Klaviyo",   "tagline": "More valuable relationships", "audience": "E-commerce", "pricing": "Free–$700+/mo", "strength": "Shopify integration, revenue attribution"},
            {"name": "Brevo",     "tagline": "The all-in-one platform to grow customer relationships", "audience": "SMB budget", "pricing": "Free–$65/mo", "strength": "Price/feature ratio"},
        ],
        "search_dominance": [
            {"keyword": "marketing automation software", "leader": "HubSpot"},
            {"keyword": "email automation tool",         "leader": "ActiveCampaign"},
            {"keyword": "ecommerce email marketing",     "leader": "Klaviyo"},
        ],
        "market_gaps": [
            {"gap": "No affordable all-in-one for 1-person brands — everyone targets SMB teams", "opportunity": "Solo founder tier at $9/mo"},
            {"gap": "Weak AI-native automation — all rely on rule-based flows",                   "opportunity": "GPT-powered flow builder as differentiator"},
            {"gap": "Poor B2B lead scoring — everyone optimises for B2C",                         "opportunity": "B2B ICP scoring built-in"},
        ],
        "positioning_recommendation": "Position as 'the AI-native alternative' — emphasise GPT-powered flows and target solo founders and early-stage teams under 10 people who are priced out of HubSpot.",
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return CompetitorAgent.DUMMY
        query = input_data.get("query", "")

        # Determine if URL or keyword
        is_url = query.startswith("http") or (len(query.split(".")) >= 2 and "/" not in query[:20])
        if is_url:
            page_text = _fetch_text(f"https://{query}" if not query.startswith("http") else query, 4000)
            search_q  = f"competitors of {query}"
        else:
            page_text = ""
            search_q  = f"best {query} 2025 comparison"

        search_results = _ddg_search(search_q, n=8)
        comp_list_search = _ddg_search(f"{query} vs alternatives pricing", n=5)

        system = (
            "You are a competitive intelligence analyst. Research the market and return JSON:\n"
            '{"query":"","competitors":[{"name":"","tagline":"","audience":"","pricing":"","strength":""}],'
            '"search_dominance":[{"keyword":"","leader":""}],'
            '"market_gaps":[{"gap":"","opportunity":""}],'
            '"positioning_recommendation":""}\n'
            "Include 4–6 real competitors. Gaps should be actionable opportunities."
        )
        user = (
            f"Query/URL: {query}\n\n"
            f"Page content (if URL): {page_text}\n\n"
            f"Search results — competitors:\n{search_results}\n\n"
            f"Pricing/alternatives search:\n{comp_list_search}"
        )
        try:
            result = _gpt(system, user, max_tokens=2500)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "query": query, "is_dummy": False}


# ── Agent 3: Ad Copy Writer ────────────────────────────────────────────────────

class AdCopyAgent:
    AGENT_ID     = "ad-copy"
    DISPLAY_NAME = "Ad Copy Writer"
    ICON         = "✍️"
    DESCRIPTION  = "Generate platform-optimised ad copy for Google Ads (RSA), Meta, and LinkedIn — with character counts."
    INPUTS = [
        {"key": "url",         "label": "Product URL (optional)",  "placeholder": "https://yoursite.com", "type": "url"},
        {"key": "description", "label": "Or describe your product", "placeholder": "B2B SaaS for invoice automation", "type": "text"},
        {"key": "platforms",   "label": "Platforms",               "placeholder": "google, meta, linkedin", "type": "text"},
    ]
    DUMMY = {
        "product": "Project management tool for agencies", "is_dummy": True,
        "google": {
            "headlines": [
                {"text": "Manage Agency Projects Faster",   "chars": 30},
                {"text": "All Projects in One Dashboard",   "chars": 29},
                {"text": "Trusted by 2,000+ Agencies",      "chars": 27},
                {"text": "Cut Project Handoff Time 40%",    "chars": 28},
                {"text": "Free 14-Day Trial · No CC",       "chars": 26},
            ],
            "descriptions": [
                {"text": "Stop losing hours to status meetings. One dashboard for all your clients, tasks, and deadlines. Try free.", "chars": 104},
                {"text": "Built for agencies: client approvals, time tracking, and billing — all in one place. Start for free today.", "chars": 104},
            ],
        },
        "meta": [
            {"variation": "Pain → Solution", "primary": "Still losing track of which agency client is waiting on what? You're not alone — most agency PMs juggle 6 tools. We built one that does it all.", "headline": "One Tool for Your Whole Agency", "description": "Try free for 14 days", "cta": "Start Free Trial"},
            {"variation": "Social Proof",    "primary": "2,000+ agencies switched from spreadsheets and Asana. Here's what they said after week one.", "headline": "Agencies Love This Tool", "description": "No credit card needed", "cta": "Learn More"},
        ],
        "linkedin": [
            {"variation": "ROI Focus",    "intro": "Agency owners: how much time does your team spend on status updates each week? Our data says 4.7 hours. We can get that to under 30 minutes.", "headline": "Cut Agency Admin Time by 85%", "description": "Project management built for agencies"},
            {"variation": "Credibility",  "intro": "We've helped 200+ agency teams hit project deadlines 30% more often. Here's the framework that works.", "headline": "The Agency PM Tool That Actually Works", "description": "Used by top-tier creative and digital agencies"},
        ],
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return AdCopyAgent.DUMMY
        url         = input_data.get("url", "")
        description = input_data.get("description", "")
        platforms   = [p.strip().lower() for p in input_data.get("platforms", "google,meta,linkedin").split(",")]

        page_text = _fetch_text(url, 3000) if url else ""
        comp_search = _ddg_search(f"{description or url} competitors messaging", n=3)

        system = (
            "You are an expert ad copywriter. Generate high-converting ad copy and return JSON:\n"
            '{"product":"","google":{"headlines":[{"text":"","chars":0}],"descriptions":[{"text":"","chars":0}]},'
            '"meta":[{"variation":"","primary":"","headline":"","description":"","cta":""}],'
            '"linkedin":[{"variation":"","intro":"","headline":"","description":""}]}\n'
            "Google: 15 headlines ≤30 chars, 4 descriptions ≤90 chars.\n"
            "Meta: 3 variations — primary text ≤125 chars visible, headline ≤40 chars.\n"
            "LinkedIn: 3 variations — intro ≤150 chars, headline ≤70 chars.\n"
            "Only include requested platforms. Count characters accurately."
        )
        user = (
            f"Product description: {description}\nURL: {url}\n\n"
            f"Page content: {page_text}\n\n"
            f"Competitor messaging context:\n{comp_search}\n\n"
            f"Requested platforms: {', '.join(platforms)}"
        )
        try:
            result = _gpt(system, user, max_tokens=3000)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "is_dummy": False}


# ── Agent 4: Lead Qualifier ────────────────────────────────────────────────────

class LeadQualAgent:
    AGENT_ID     = "lead-qual"
    DISPLAY_NAME = "Lead Qualifier"
    ICON         = "🧭"
    DESCRIPTION  = "Research leads against your ICP: company size, industry fit, budget signals, and recommended next step."
    INPUTS = [
        {"key": "leads",    "label": "Leads (one per line: Name, email, Company)", "placeholder": "Anna Smith, anna@techcorp.com, TechCorp\nBob Jones, bob@gmail.com, Unknown", "type": "textarea"},
        {"key": "icp",      "label": "Your ICP description",                       "placeholder": "B2B SaaS companies, 10–200 employees, run paid ads", "type": "text"},
    ]
    DUMMY = {
        "icp": "Digital marketing agencies with 5–50 employees that run Google Ads", "is_dummy": True,
        "leads": [
            {"name": "Anna Lindqvist", "email": "anna@growthagency.se", "company": "Growth Agency AB",
             "role": "CEO", "company_size": "12 employees", "industry": "Digital marketing agency",
             "icp_fit": "HIGH", "score": 88,
             "signals": ["+Runs Google Ads (verified pixel)", "+Agency model matches ICP", "+Right company size"],
             "red_flags": [], "deal_value": "€800–1,200/mo", "next_step": "Book discovery call — reference Nordic agency case study"},
            {"name": "Bob Johnson", "email": "bob@gmail.com", "company": "Unknown",
             "role": "Unknown", "company_size": "Unknown", "industry": "Unknown",
             "icp_fit": "LOW", "score": 12,
             "signals": [], "red_flags": ["-Personal email address", "-No company info found"],
             "deal_value": "Unknown", "next_step": "Request company email before investing sales time"},
            {"name": "Maria Santos", "email": "m.santos@bigcorp.com", "company": "BigCorp Inc",
             "role": "Marketing Director", "company_size": "1,200 employees", "industry": "Enterprise manufacturing",
             "icp_fit": "MEDIUM", "score": 45,
             "signals": ["+Decision-maker title", "+Has marketing budget"],
             "red_flags": ["-Enterprise size (outside ICP)", "-No evidence of paid search spend"],
             "deal_value": "Unknown — would need custom pricing", "next_step": "Qualify budget and team size before booking call"},
        ],
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return LeadQualAgent.DUMMY
        leads_raw = input_data.get("leads", "")
        icp       = input_data.get("icp", "")

        # Parse leads
        parsed_leads = []
        for line in leads_raw.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 1:
                parsed_leads.append({
                    "name":    parts[0] if len(parts) > 0 else "",
                    "email":   parts[1] if len(parts) > 1 else "",
                    "company": parts[2] if len(parts) > 2 else "",
                })

        # Research each company (cap at 5 to avoid long runs)
        research = []
        for lead in parsed_leads[:5]:
            co = lead.get("company", "")
            if co and co.lower() not in ("unknown", ""):
                snippets = _ddg_search(f"{co} company size employees industry", n=3)
            else:
                snippets = "No company info"
            research.append({"lead": lead, "research": snippets})

        system = (
            "You are a B2B sales analyst. Qualify each lead against the ICP and return JSON:\n"
            '{"icp":"","leads":[{"name":"","email":"","company":"","role":"","company_size":"","industry":"",'
            '"icp_fit":"HIGH|MEDIUM|LOW|NONE","score":0-100,"signals":["+..."],"red_flags":["-..."],'
            '"deal_value":"","next_step":""}]}\n'
            "Be realistic — a personal gmail email with no company info should score < 20."
        )
        user = f"ICP: {icp}\n\nLeads and research:\n{json.dumps(research, ensure_ascii=False)}"
        try:
            result = _gpt(system, user, max_tokens=2500)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "is_dummy": False}


# ── Agent 5: CWV Auditor ───────────────────────────────────────────────────────

class CWVAgent:
    AGENT_ID     = "cwv"
    DISPLAY_NAME = "Core Web Vitals Auditor"
    ICON         = "⚡"
    DESCRIPTION  = "Fetch real PageSpeed data for any URL, diagnose LCP/INP/CLS issues, and get prioritised fix plan."
    INPUTS = [
        {"key": "url",      "label": "URL to audit",    "placeholder": "https://yoursite.com", "type": "url"},
        {"key": "strategy", "label": "Device strategy", "placeholder": "mobile (default) or desktop", "type": "text"},
    ]
    DUMMY = {
        "url": "https://example.com", "strategy": "mobile", "is_dummy": True,
        "metrics": {
            "psi_score": 58, "psi_lcp_ms": 3800, "psi_cls": 0.18,
            "psi_inp_ms": 320, "psi_fcp_ms": 1900, "psi_ttfb_ms": 420,
        },
        "grades": {"lcp": "needs-improvement", "cls": "poor", "inp": "needs-improvement"},
        "diagnosis": [
            {"metric": "LCP", "value": "3.8s", "threshold": "≤ 2.5s good", "root_cause": "Hero image (1.2MB WebP) not preloaded — render-blocked by 3 CSS files", "fix": "Add <link rel=preload as=image> for hero + inline critical CSS", "effort": "Medium", "priority": 1},
            {"metric": "CLS", "value": "0.18", "threshold": "≤ 0.1 good",  "root_cause": "Cookie consent banner loads without reserved space, shifts content 180px", "fix": "Add min-height:80px to cookie bar container; use position:fixed", "effort": "Easy",   "priority": 2},
            {"metric": "INP", "value": "320ms","threshold": "≤ 200ms good","root_cause": "Intercom chat widget blocks main thread on first interaction (6 long tasks)", "fix": "Lazy-load Intercom after 3s user idle: requestIdleCallback(() => loadIntercom())", "effort": "Easy", "priority": 3},
        ],
        "monitoring_query": "SELECT date, APPROX_QUANTILES(metric_value,100)[OFFSET(75)] AS p75\nFROM `project.analytics_XXXX.events_*`\nWHERE event_name IN ('LCP','INP','CLS')\nGROUP BY date ORDER BY date DESC",
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return CWVAgent.DUMMY
        url      = input_data.get("url", "")
        strategy = input_data.get("strategy", "mobile").lower().strip() or "mobile"

        # Fetch real PSI data
        from pagespeed_client import fetch_pagespeed
        metrics = fetch_pagespeed(url, strategy=strategy)

        def grade(metric: str, val: float) -> str:
            thresholds = {"lcp": (2500, 4000), "cls": (0.1, 0.25), "inp": (200, 500)}
            lo, hi = thresholds.get(metric, (0, 1))
            if val <= lo: return "good"
            if val <= hi: return "needs-improvement"
            return "poor"

        grades = {
            "lcp": grade("lcp", metrics.get("psi_lcp_ms", 0)),
            "cls": grade("cls", metrics.get("psi_cls", 0)),
            "inp": grade("inp", metrics.get("psi_inp_ms", 0)),
        }

        # Fetch page HTML for additional signals
        html = _fetch_html(url)
        soup = BeautifulSoup(html, "lxml") if html and not html.startswith("[fetch") else None
        has_preload = bool(soup and soup.find("link", {"rel": "preload"})) if soup else False
        has_defer   = bool(soup and soup.find("script", {"defer": True})) if soup else False
        img_count   = len(soup.find_all("img")) if soup else 0

        system = (
            "You are a Core Web Vitals expert (LCP good≤2.5s, INP good≤200ms, CLS good≤0.1). "
            "Analyze the PSI metrics and page signals, then return JSON:\n"
            '{"url":"","strategy":"","metrics":{...raw PSI...},"grades":{"lcp":"","cls":"","inp":""},'
            '"diagnosis":[{"metric":"","value":"","threshold":"","root_cause":"","fix":"","effort":"Easy|Medium|Hard","priority":1}],'
            '"monitoring_query":"<BigQuery SQL for CWV monitoring>"}\n'
            "Priority 1 = highest impact. Include 3–5 diagnosis items covering each failing metric."
        )
        user = (
            f"URL: {url} | Strategy: {strategy}\n"
            f"PSI metrics: {json.dumps(metrics)}\n"
            f"Grades: {json.dumps(grades)}\n"
            f"Page signals: has_preload={has_preload}, has_defer_scripts={has_defer}, img_count={img_count}"
        )
        try:
            result = _gpt(system, user, max_tokens=2000)
            result.setdefault("metrics", metrics)
            result.setdefault("grades", grades)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "url": url, "metrics": metrics, "grades": grades, "is_dummy": False}


# ── Agent 6: UTM Builder ───────────────────────────────────────────────────────

class UTMAgent:
    AGENT_ID     = "utm"
    DISPLAY_NAME = "UTM Framework Builder"
    ICON         = "🔗"
    DESCRIPTION  = "Build a complete UTM naming convention system with channel groupings, validation rules, and example URLs."
    INPUTS = [
        {"key": "brand",     "label": "Brand / site name",    "placeholder": "Increv", "type": "text"},
        {"key": "channels",  "label": "Your channels (comma-separated)", "placeholder": "google ads, meta, linkedin, email, organic social", "type": "text"},
        {"key": "campaigns", "label": "Current campaigns",    "placeholder": "link_building, seo_audit, spring_promo", "type": "text"},
    ]
    DUMMY = {
        "brand": "AcmeSaaS", "is_dummy": True,
        "naming_convention": {
            "utm_source":   "Traffic origin platform (google, facebook, linkedin, newsletter)",
            "utm_medium":   "Marketing channel type (cpc, social, email, organic, affiliate)",
            "utm_campaign": "Campaign name — use snake_case, include quarter: q2_link_building",
            "utm_content":  "Ad/creative identifier: headline_v1, carousel_a, cta_test",
            "utm_term":     "Paid keyword (Google Ads auto-populate or manual: seo+tools)",
        },
        "channel_groupings": [
            {"ga4_channel": "Paid Search",  "rules": "utm_source=(google|bing) AND utm_medium=cpc"},
            {"ga4_channel": "Paid Social",  "rules": "utm_source=(facebook|instagram|linkedin) AND utm_medium=cpc|paid-social"},
            {"ga4_channel": "Email",        "rules": "utm_medium=email"},
            {"ga4_channel": "Organic Social","rules":"utm_medium=social AND utm_source=(facebook|instagram|linkedin|twitter)"},
            {"ga4_channel": "Affiliate",    "rules": "utm_medium=affiliate"},
        ],
        "example_urls": [
            {"label": "Google Ads — Brand",       "url": "https://acmesaas.com/pricing?utm_source=google&utm_medium=cpc&utm_campaign=q2_brand&utm_content=headline_v1&utm_term=acmesaas"},
            {"label": "LinkedIn — Sponsored Post","url": "https://acmesaas.com/demo?utm_source=linkedin&utm_medium=paid-social&utm_campaign=q2_link_building&utm_content=carousel_a"},
            {"label": "Email Newsletter",         "url": "https://acmesaas.com/blog/seo-guide?utm_source=newsletter&utm_medium=email&utm_campaign=q2_nurture&utm_content=cta_button"},
        ],
        "validation_rules": [
            "Always lowercase — 'Google' breaks channel groupings",
            "Use snake_case for campaign names, no spaces or special chars",
            "Include quarter in campaign name: q2_campaign_name",
            "utm_medium must exactly match GA4 channel grouping rules",
            "Never use UTMs on internal links — inflates session count",
        ],
        "bigquery_validation": "SELECT utm_campaign, COUNT(*) sessions FROM `project.analytics_xxx.events_*`\nWHERE event_name='session_start'\nGROUP BY 1 ORDER BY 2 DESC LIMIT 50",
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return UTMAgent.DUMMY
        brand     = input_data.get("brand", "")
        channels  = input_data.get("channels", "")
        campaigns = input_data.get("campaigns", "")

        system = (
            "You are a marketing analytics expert specialising in UTM tracking and GA4 channel groupings. "
            "Build a complete UTM framework and return JSON:\n"
            '{"brand":"","naming_convention":{"utm_source":"","utm_medium":"","utm_campaign":"","utm_content":"","utm_term":""},'
            '"channel_groupings":[{"ga4_channel":"","rules":""}],'
            '"example_urls":[{"label":"","url":""}],'
            '"validation_rules":[...],'
            '"bigquery_validation":"<SQL>"}\n'
            "Make channel groupings match GA4 default channel grouping regex format. "
            "Include 3–5 example URLs with complete UTM parameters for the actual channels provided. "
            "Validation rules should be specific to common mistakes teams make."
        )
        user = f"Brand: {brand}\nChannels: {channels}\nCampaigns: {campaigns}"
        try:
            result = _gpt(system, user, max_tokens=2000)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "is_dummy": False}


# ── Agent 7: Conversion Tracking Debugger ──────────────────────────────────────

class ConversionAgent:
    AGENT_ID     = "conversion"
    DISPLAY_NAME = "Conversion Tracking Debugger"
    ICON         = "🐛"
    DESCRIPTION  = "Diagnose GTM/GA4/Google Ads/Meta tracking issues — duplicate conversions, consent mode, CAPI setup."
    INPUTS = [
        {"key": "url",      "label": "Site URL",              "placeholder": "https://yoursite.com", "type": "url"},
        {"key": "platform", "label": "Platform(s) involved",  "placeholder": "GA4, Google Ads, Meta, GTM", "type": "text"},
        {"key": "issue",    "label": "Describe the issue",    "placeholder": "Conversions are double-counting purchase events", "type": "textarea"},
    ]
    DUMMY = {
        "url": "https://example.com", "platform": "GA4 + Google Ads", "is_dummy": True,
        "issue_summary": "Purchase events double-counting in both GA4 and Google Ads",
        "likely_causes": [
            {"rank": 1, "cause": "Missing transaction_id deduplication — GA4 can't dedup without unique ID", "probability": "High"},
            {"rank": 2, "cause": "Thank-you page reloads trigger second purchase event", "probability": "Medium"},
            {"rank": 3, "cause": "Both GTM web container tag AND hardcoded gtag.js tag firing", "probability": "Medium"},
        ],
        "diagnosis_steps": [
            {"step": 1, "action": "Open GTM Preview on /checkout/thank-you — does purchase tag fire once or twice?"},
            {"step": 2, "action": "DevTools > Network — filter by 'collect' — count how many GA4 hits fire per conversion"},
            {"step": 3, "action": "Run BigQuery dedup query to find transaction_ids appearing >1 time in last 7 days"},
            {"step": 4, "action": "Check if page has both GTM snippet AND direct gtag.js script tag in <head>"},
        ],
        "fixes": [
            {"fix": "Add transaction_id to all purchase dataLayer pushes", "code": "window.dataLayer.push({event:'purchase',ecommerce:{transaction_id:'T-'+orderId,...}})"},
            {"fix": "Add sessionStorage guard to prevent re-fire on reload", "code": "if(!sessionStorage.getItem('purchased_'+txId)){dataLayer.push({...});sessionStorage.setItem('purchased_'+txId,'1')}"},
            {"fix": "Remove direct gtag.js script if GTM is present — only one should fire"},
        ],
        "bigquery_queries": [
            {"label": "Find duplicate transaction_ids (last 7 days)", "sql": "SELECT (SELECT value.string_value FROM UNNEST(event_params) WHERE key='transaction_id') AS txn_id, COUNT(*) AS count\nFROM `project.analytics_XXXX.events_*`\nWHERE event_name='purchase' AND _TABLE_SUFFIX >= FORMAT_DATE('%Y%m%d',DATE_SUB(CURRENT_DATE(),INTERVAL 7 DAY))\nGROUP BY 1 HAVING count > 1 ORDER BY 2 DESC"},
            {"label": "Purchases without transaction_id (revenue at risk)", "sql": "SELECT event_date, COUNT(*) AS no_txn_id_count\nFROM `project.analytics_XXXX.events_*`\nWHERE event_name='purchase' AND (SELECT value.string_value FROM UNNEST(event_params) WHERE key='transaction_id') IS NULL\nGROUP BY 1 ORDER BY 1 DESC"},
        ],
    }

    @staticmethod
    def run(input_data: dict, use_dummy: bool = False) -> dict:
        if use_dummy:
            return ConversionAgent.DUMMY
        url      = input_data.get("url", "")
        platform = input_data.get("platform", "")
        issue    = input_data.get("issue", "")

        # Fetch page to check for tracking signals
        html  = _fetch_html(url)
        soup  = BeautifulSoup(html, "lxml") if html and not html.startswith("[fetch") else None
        has_gtm      = "GTM-" in (html or "") or "googletagmanager.com/gtm" in (html or "")
        has_gtag     = "gtag(" in (html or "") or "googletagmanager.com/gtag" in (html or "")
        has_fbpixel  = "fbq(" in (html or "") or "connect.facebook.net" in (html or "")
        has_meta_capi= False  # server-side, can't detect from HTML
        double_gtag  = has_gtm and has_gtag  # potential dual-fire

        system = (
            "You are a conversion tracking debugging expert (GTM, GA4, Google Ads, Meta Pixel, CAPI). "
            "Diagnose the described issue and return JSON:\n"
            '{"url":"","platform":"","issue_summary":"","likely_causes":[{"rank":1,"cause":"","probability":"High|Medium|Low"}],'
            '"diagnosis_steps":[{"step":1,"action":""}],'
            '"fixes":[{"fix":"","code":""}],'
            '"bigquery_queries":[{"label":"","sql":""}]}\n'
            "Provide 3–5 likely causes ranked by probability. Include copy-pasteable BigQuery SQL. "
            "Fix code should be real JavaScript or bash where applicable."
        )
        user = (
            f"URL: {url}\nPlatform(s): {platform}\nIssue: {issue}\n\n"
            f"Page signals: has_gtm={has_gtm}, has_direct_gtag={has_gtag}, "
            f"has_fbpixel={has_fbpixel}, potential_double_fire={double_gtag}"
        )
        try:
            result = _gpt(system, user, max_tokens=2500)
            result["is_dummy"] = False
            return result
        except Exception as e:
            return {"error": str(e), "is_dummy": False}


# ── Registry ───────────────────────────────────────────────────────────────────

AGENT_REGISTRY: dict[str, type] = {
    "landing-page": LandingPageAgent,
    "competitor":   CompetitorAgent,
    "ad-copy":      AdCopyAgent,
    "lead-qual":    LeadQualAgent,
    "cwv":          CWVAgent,
    "utm":          UTMAgent,
    "conversion":   ConversionAgent,
}


def list_agents() -> list[dict]:
    """Return metadata for all registered agents (for the UI)."""
    return [
        {
            "id":          cls.AGENT_ID,
            "name":        cls.DISPLAY_NAME,
            "icon":        cls.ICON,
            "description": cls.DESCRIPTION,
            "inputs":      cls.INPUTS,
        }
        for cls in AGENT_REGISTRY.values()
    ]
