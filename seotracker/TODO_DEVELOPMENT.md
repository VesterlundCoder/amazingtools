# SEO Crawler — Development Roadmap

Things the crawler **should detect** but currently doesn't fully cover, organized by category. Each item describes what to add or improve.

---

## 1. Internal Links (Currently Incomplete)

The crawl of expoduluterum.se found **0 links** despite 502 pages — the link extraction pipeline isn't wiring link records into the output properly.

- [ ] **Fix link persistence in CLI mode** — `runner.py` collects page data but doesn't save extracted links to `links.json`; the orchestrator extracts them but they're lost before export
- [ ] **Internal link graph** — build a full source→dest map of all internal `<a href>` links
- [ ] **Orphan page detection** — pages with zero inbound internal links
- [ ] **Click depth analysis** — how many clicks from the homepage to reach each page
- [ ] **Internal link distribution** — flag pages with very few or excessive internal links
- [ ] **Anchor text analysis** — collect and report anchor text distribution per target URL
- [ ] **Broken internal links** — detect links pointing to 404/5xx pages within the site
- [ ] **Nofollow internal links** — flag `rel="nofollow"` on internal links (usually a mistake)

## 2. Missing/Malformed H1 Tags

- [ ] **Missing H1** — flag indexable pages with no `<h1>` tag at all
- [ ] **Multiple H1s** — flag pages with more than one `<h1>`
- [ ] **Empty H1** — detect `<h1></h1>` or whitespace-only H1
- [ ] **H1 matches title** — warn when H1 is identical to `<title>` (missed optimization opportunity)
- [ ] **H1 too long/short** — flag H1 tags shorter than 10 chars or longer than 70 chars
- [ ] **Heading hierarchy gaps** — detect skipped heading levels (e.g., H1 → H3 with no H2)

## 3. Structured Data / Schema.org

- [ ] **JSON-LD extraction and validation** — parse all `<script type="application/ld+json">` blocks, validate against Schema.org
- [ ] **Missing structured data** — flag pages that should have it (product pages, articles, FAQ, local business)
- [ ] **Required property checks** — verify `@type`-specific required fields (e.g., Product needs `name`, `image`, `offers`)
- [ ] **Breadcrumb markup** — detect missing `BreadcrumbList` schema
- [ ] **Organization/LocalBusiness** — check homepage for org-level schema
- [ ] **FAQ schema** — detect FAQ-style content without FAQ markup
- [ ] **Review/Rating schema** — validate review markup completeness

## 4. JavaScript-Rendered Content

- [ ] **JS-only text content** — detect text visible only after JS execution (not in raw HTML)
- [ ] **JS-injected links** — links that only appear after rendering (invisible to bots without JS)
- [ ] **JS framework detection** — identify React/Vue/Angular SPAs that need rendering
- [ ] **Lazy-loaded content below fold** — content loaded via IntersectionObserver that crawlers may miss
- [ ] **Client-side routing detection** — SPAs using `pushState` where content changes without page load
- [ ] **Critical rendering path** — measure if key SEO content is in initial HTML or requires JS
- [ ] **`noscript` fallback check** — verify `<noscript>` content exists for JS-dependent pages

## 5. Meta Tags & Open Graph

- [ ] **Missing meta description** — flag indexable pages without `<meta name="description">`
- [ ] **Duplicate meta descriptions** — same description across multiple pages
- [ ] **Meta description length** — warn if < 70 or > 160 characters
- [ ] **Missing Open Graph tags** — `og:title`, `og:description`, `og:image`, `og:url`
- [ ] **Missing Twitter Card tags** — `twitter:card`, `twitter:title`, `twitter:description`
- [ ] **Viewport meta tag** — missing `<meta name="viewport">` (mobile-friendliness)
- [ ] **Charset declaration** — missing or incorrect `<meta charset>`

## 6. Images

- [ ] **Missing alt text** — `<img>` without `alt` attribute
- [ ] **Empty alt text on non-decorative images** — `alt=""` on images that convey information
- [ ] **Oversized images** — images larger than 200KB that should be compressed
- [ ] **Missing width/height** — causes layout shifts (CLS impact)
- [ ] **Broken image URLs** — images returning 404
- [ ] **Next-gen format check** — flag JPEG/PNG that could be WebP/AVIF
- [ ] **Lazy-load without noscript** — `loading="lazy"` images with no fallback

## 7. URL & Crawlability Issues

- [ ] **URL parameter handling** — detect paginated/filtered URLs creating duplicate content
- [ ] **Trailing slash inconsistency** — same page accessible with and without trailing slash
- [ ] **Mixed case URLs** — uppercase letters in URLs creating duplicates
- [ ] **Excessive URL depth** — URLs with 5+ path segments
- [ ] **URL contains special characters** — spaces, underscores, non-ASCII in URLs
- [ ] **Pagination detection** — find `rel="next"` / `rel="prev"` or page parameter patterns
- [ ] **Faceted navigation** — detect filter combinations creating crawl traps
- [ ] **XML sitemap vs crawled pages** — pages in sitemap but not found by crawler, and vice versa

## 8. Performance & Core Web Vitals

- [ ] **TTFB threshold alerts** — flag pages with TTFB > 600ms
- [ ] **Large page size** — HTML > 100KB, total page weight > 3MB
- [ ] **Too many requests** — pages loading 100+ resources
- [ ] **Render-blocking resources** — CSS/JS in `<head>` without `async`/`defer`
- [ ] **Cumulative Layout Shift hints** — missing image dimensions, dynamic content injection
- [ ] **Font loading** — detect `font-display: swap` missing
- [ ] **HTTP/2 check** — flag sites still on HTTP/1.1

## 9. Security & HTTPS

- [ ] **Mixed content** — HTTPS pages loading HTTP resources
- [ ] **HTTP to HTTPS redirect** — verify all HTTP URLs redirect to HTTPS
- [ ] **HSTS header** — check for `Strict-Transport-Security`
- [ ] **Certificate validity** — flag expiring SSL certificates
- [ ] **Insecure form actions** — `<form>` submitting to HTTP URLs

## 10. Content Quality

- [ ] **Thin content** — indexable pages with fewer than 200 words
- [ ] **Duplicate titles** — multiple pages sharing the same `<title>`
- [ ] **Duplicate H1s** — same H1 across different pages
- [ ] **Near-duplicate content** — pages with >80% content similarity (simhash/minhash)
- [ ] **Keyword stuffing detection** — abnormally high keyword density
- [ ] **Reading level analysis** — Flesch-Kincaid readability score
- [ ] **Content freshness** — detect `dateModified`/`datePublished` and flag stale content

## 11. Redirects & Canonicals

- [ ] **Redirect chains > 2 hops** — flag long redirect chains
- [ ] **Redirect loops** — detect infinite redirect cycles
- [ ] **302 vs 301** — flag temporary redirects that should be permanent
- [ ] **Canonical to redirected URL** — canonical pointing to a URL that redirects
- [ ] **Self-referencing canonical missing** — indexable pages without `<link rel="canonical">`
- [ ] **Canonical mismatch** — canonical URL differs from the actual URL
- [ ] **HTTP ↔ HTTPS canonical conflicts**

## 12. International SEO (Hreflang)

- [ ] **Missing self-referencing hreflang** — page doesn't include itself in hreflang set
- [ ] **Missing return links** — page A → page B hreflang but B doesn't link back to A
- [ ] **Hreflang to non-200 page** — hreflang pointing to redirected or error pages
- [ ] **Invalid language codes** — hreflang with incorrect ISO 639-1 codes
- [ ] **x-default missing** — no fallback `x-default` hreflang

## 13. Accessibility (SEO-Adjacent)

- [ ] **Missing lang attribute** — `<html>` without `lang`
- [ ] **Empty link text** — `<a>` tags with no visible text or aria-label
- [ ] **Form labels** — `<input>` without associated `<label>`
- [ ] **Color contrast hints** — detect very low contrast text (basic heuristic)
- [ ] **Skip navigation link** — missing skip-to-content for screen readers

---

## Priority Order for Development

### Phase 1 — Critical Fixes (Broken Functionality)
1. Fix link extraction persistence (links.json is empty)
2. Missing H1 detection (currently extracted but not flagged in issues)
3. Structured data extraction and basic validation

### Phase 2 — High-Value Additions
4. Internal link graph + orphan page detection
5. JS-rendered content detection (enable Playwright rendering)
6. Meta description completeness
7. Image optimization checks

### Phase 3 — Advanced Analysis
8. Near-duplicate content detection
9. Core Web Vitals hints
10. Hreflang validation improvements
11. Content quality scoring

### Phase 4 — Polish
12. Security checks
13. Accessibility basics
14. URL hygiene scoring
