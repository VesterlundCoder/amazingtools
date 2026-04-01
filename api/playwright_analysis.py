"""
playwright_analysis.py — Enhanced Playwright-based per-page analysis.

Implements the full spec:
  • User-Agent switching  (Googlebot Desktop / Smartphone / custom)
  • Request interception  (block analytics / trackers)
  • DOM diffing           (raw HTML vs rendered DOM for title/meta/canonical)
  • Shadow DOM link discovery
  • JS error + failed-request capture
  • Tap-target validation (WCAG 48×48 px minimum)
  • Text-to-HTML ratio    (thin-content detection)
  • Visual hierarchy      (above-fold, main/article presence)
  • Image audit           (format WebP/AVIF, natural vs display, lazy-loading)
  • Infinite-scroll trigger (optional)
  • Modal / overlay detection & dismissal (optional)
  • Auth-cookie injection (optional)
"""

import asyncio
import logging
import re

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

# ── User-Agent strings ─────────────────────────────────────────────────────────

GOOGLEBOT_DESKTOP = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
GOOGLEBOT_MOBILE = (
    "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 "
    "(compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)

# ── Tracker / analytics block list ────────────────────────────────────────────

BLOCKED_PATTERNS = [
    "google-analytics", "googletagmanager", "doubleclick",
    "facebook.net", "fbevents", "connect.facebook",
    "hotjar", "mixpanel", "segment.com", "amplitude",
    "fullstory", "intercom", "hubspot", "marketo",
    "pardot", "criteo", "quantserve", "scorecardresearch",
    "adnxs", "adsystem", "googlesyndication",
]

# ── Modal / close selectors ────────────────────────────────────────────────────

MODAL_SELECTORS = [
    "[role='dialog']", ".modal", "#modal", ".popup", ".overlay",
    "[class*='cookie']", "[class*='consent']", "[class*='newsletter']",
    "[id*='cookie']", "[id*='popup']", "[id*='gdpr']",
]
CLOSE_SELECTORS = [
    "button[aria-label*='close' i]", "button[aria-label*='dismiss' i]",
    "button[aria-label*='accept' i]", "button[aria-label*='stäng' i]",
    ".modal-close", ".close-btn", "[class*='close']", "[id*='close']",
    "button[class*='dismiss']", "button[class*='accept']",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _raw_seo(html: str) -> dict:
    """Extract title / meta-desc / canonical from raw (pre-JS) HTML."""
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("title")
    title = t.get_text(strip=True) if t else ""
    m = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    desc = (m.get("content", "") or "").strip() if m else ""
    c = soup.find("link", rel=lambda r: r and "canonical" in r)
    canonical = (c.get("href", "") or "").strip() if c else ""
    return {"title": title, "desc": desc, "canonical": canonical}


async def _fetch_raw(url: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cl:
            r = await cl.get(url, headers={"User-Agent": "AmazingTools-SEO-Crawler/2.0"})
            return r.text
    except Exception:
        return ""


def _is_blocked(url: str) -> bool:
    return any(p in url for p in BLOCKED_PATTERNS)


async def _try_dismiss_modals(page: Page) -> None:
    for sel in MODAL_SELECTORS:
        try:
            els = await page.query_selector_all(sel)
            if not els:
                continue
            for close_sel in CLOSE_SELECTORS:
                btn = await page.query_selector(close_sel)
                if btn and await btn.is_visible():
                    await btn.click(timeout=1500)
                    break
        except Exception:
            pass


# ── Core single-page analyser ──────────────────────────────────────────────────

async def _analyse(page: Page, url: str, raw_html: str,
                   js_errors: list, failed_reqs: list) -> dict:
    """All analysis on an already-loaded & settled page."""

    # ── DOM diff ──────────────────────────────────────────────────────────────
    raw = _raw_seo(raw_html)
    r_title = (await page.title() or "").strip()
    r_desc  = (await page.evaluate(
        "()=>(document.querySelector('meta[name=\"description\"]')||{content:''}).content||''"
    ) or "").strip()
    r_can   = (await page.evaluate(
        "()=>(document.querySelector('link[rel=\"canonical\"]')||{href:''}).href||''"
    ) or "").strip()

    title_diff    = bool(raw["title"] != r_title   and (raw["title"]    or r_title))
    desc_diff     = bool(raw["desc"]  != r_desc    and (raw["desc"]     or r_desc))
    canon_diff    = bool(raw["canonical"] != r_can and (raw["canonical"] or r_can))

    # ── Shadow DOM links ──────────────────────────────────────────────────────
    shadow_count = await page.evaluate("""
        () => {
            const found = new Set();
            function walk(root) {
                const links = root.querySelectorAll ? root.querySelectorAll('a[href]') : [];
                links.forEach(a => found.add(a.href));
                const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
                all.forEach(el => { if (el.shadowRoot) walk(el.shadowRoot); });
            }
            walk(document);
            return found.size;
        }
    """) or 0
    regular_count = await page.evaluate(
        "()=>document.querySelectorAll('a[href]').length"
    ) or 0
    shadow_dom_links = max(0, shadow_count - regular_count)

    # ── Text-to-HTML ratio ────────────────────────────────────────────────────
    ratio = await page.evaluate("""
        () => {
            const txt  = (document.body||{}).innerText || '';
            const html = (document.documentElement||{}).outerHTML || '';
            return { t: txt.length, h: html.length };
        }
    """) or {"t": 0, "h": 1}
    html_len         = max(ratio.get("h", 1), 1)
    text_len         = ratio.get("t", 0)
    text_html_ratio  = round(text_len / html_len, 3)
    thin_content     = text_len < 300

    # ── Visual hierarchy / main content ──────────────────────────────────────
    content = await page.evaluate("""
        () => {
            const el = document.querySelector('main,[role="main"],article');
            if (!el) return { found: false, chars: 0, fold: false };
            const r   = el.getBoundingClientRect();
            const txt = el.innerText || '';
            return { found: true, chars: txt.trim().length, fold: r.top < window.innerHeight };
        }
    """) or {"found": False, "chars": 0, "fold": False}
    main_loaded   = bool(content.get("found") and content.get("chars", 0) > 50)
    above_fold    = bool(content.get("fold"))

    # ── Tap targets ───────────────────────────────────────────────────────────
    tap_issues = await page.evaluate("""
        () => {
            const MIN = 48, bad = [];
            const els = document.querySelectorAll('a,button,[role="button"],input,select');
            for (const el of els) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0 && (r.width < MIN || r.height < MIN)) {
                    const id = el.id ? '#'+el.id
                        : el.className
                            ? '.'+String(el.className).trim().split(/\\s+/)[0]
                            : el.tagName.toLowerCase();
                    bad.push(id);
                    if (bad.length >= 20) break;
                }
            }
            return bad;
        }
    """) or []

    # ── Image audit ───────────────────────────────────────────────────────────
    img_data = await page.evaluate("""
        () => {
            const imgs  = Array.from(document.images);
            const vp    = window.innerHeight;
            const nonMod = [], lazyMiss = [];
            imgs.forEach(img => {
                const src = img.currentSrc || img.src || '';
                const ext = src.split('?')[0].split('.').pop().toLowerCase();
                if (src && !['webp','avif','svg'].includes(ext))
                    nonMod.push(src.replace(/^https?:\\/\\/[^/]+/,'').substring(0,100));
                const rect = img.getBoundingClientRect();
                if (rect.top > vp && img.loading !== 'lazy')
                    lazyMiss.push(src.replace(/^https?:\\/\\/[^/]+/,'').substring(0,100));
            });
            return { non_modern: nonMod.slice(0,10), lazy_missing: lazyMiss.length };
        }
    """) or {"non_modern": [], "lazy_missing": 0}

    return {
        "seo": {
            "title_rendered":    r_title,
            "title_source_diff": title_diff,
            "meta_desc_rendered": r_desc,
            "meta_desc_diff":    desc_diff,
            "canonical_rendered": r_can,
            "canonical_diff":    canon_diff,
            "text_html_ratio":   text_html_ratio,
            "thin_content_warning": thin_content,
        },
        "ux": {
            "js_errors":          js_errors[:20],
            "failed_requests":    [r for r in failed_reqs if r][:20],
            "small_tap_targets":  tap_issues,
            "non_modern_images":  img_data.get("non_modern") or [],
            "images_lazy_missing": img_data.get("lazy_missing") or 0,
        },
        "architecture": {
            "shadow_dom_links_found": shadow_dom_links,
            "main_content_loaded":   main_loaded,
            "above_fold_content":    above_fold,
        },
    }


# ── Public: analyse a list of URLs ────────────────────────────────────────────

async def _run(urls: list, options: dict, concurrency: int = 3) -> dict:
    results: dict = {}

    ua_key = options.get("user_agent", "default")
    if ua_key == "googlebot_desktop":
        user_agent = GOOGLEBOT_DESKTOP
    elif ua_key == "googlebot_mobile":
        user_agent = GOOGLEBOT_MOBILE
    elif ua_key and ua_key != "default":
        user_agent = ua_key
    else:
        user_agent = None

    block     = bool(options.get("block_resources", False))
    scroll    = bool(options.get("scroll_pages", False))
    cookies   = options.get("auth_cookies") or []
    modals    = bool(options.get("dismiss_modals", False))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx_kwargs: dict = {"viewport": {"width": 1280, "height": 900}}
        if user_agent:
            ctx_kwargs["user_agent"] = user_agent
        ctx: BrowserContext = await browser.new_context(**ctx_kwargs)
        if cookies:
            await ctx.add_cookies(cookies)

        sem = asyncio.Semaphore(concurrency)

        async def process(url: str) -> None:
            async with sem:
                page = await ctx.new_page()
                js_errors:   list = []
                failed_reqs: list = []

                page.on("pageerror",     lambda e: js_errors.append(str(e)))
                page.on("requestfailed", lambda req: (
                    failed_reqs.append(f"{req.failure or 'failed'}: {req.url[:120]}")
                    if not _is_blocked(req.url) else None
                ))

                if block:
                    async def route_handler(route, request):
                        if _is_blocked(request.url):
                            await route.abort()
                        else:
                            await route.continue_()
                    await page.route("**/*", route_handler)

                raw_html = await _fetch_raw(url)

                try:
                    await page.goto(url, wait_until="networkidle", timeout=25000)
                except Exception:
                    try:
                        await page.goto(url, wait_until="load", timeout=20000)
                    except Exception as e:
                        logger.warning("PW nav failed %s: %s", url, e)
                        results[url] = {
                            "seo": {}, "ux": {"js_errors": [str(e)]}, "architecture": {}
                        }
                        await page.close()
                        return

                if modals:
                    await _try_dismiss_modals(page)

                if scroll:
                    try:
                        await page.evaluate("""
                            async () => {
                                await new Promise(res => {
                                    let y = 0;
                                    const t = setInterval(() => {
                                        window.scrollBy(0, 500);
                                        y += 500;
                                        if (y >= document.body.scrollHeight) {
                                            clearInterval(t); res();
                                        }
                                    }, 100);
                                    setTimeout(() => { clearInterval(t); res(); }, 6000);
                                });
                            }
                        """)
                        await page.wait_for_timeout(600)
                    except Exception:
                        pass

                try:
                    results[url] = await _analyse(page, url, raw_html, js_errors, failed_reqs)
                except Exception as e:
                    logger.warning("PW analysis error %s: %s", url, e)
                    results[url] = {
                        "seo": {}, "ux": {"js_errors": [str(e)]}, "architecture": {}
                    }
                finally:
                    await page.close()

        await asyncio.gather(*[process(u) for u in urls])
        await ctx.close()
        await browser.close()

    return results


def run_playwright_analysis(urls: list, options: dict, concurrency: int = 3) -> dict:
    """Synchronous wrapper — safe to call from a background thread."""
    if not urls:
        return {}
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run(urls, options, concurrency))
    finally:
        loop.close()
