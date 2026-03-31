import React, { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

const SEVERITY_STYLES = {
  critical: 'bg-red-100 text-red-700 border-red-200',
  high: 'bg-orange-100 text-orange-700 border-orange-200',
  medium: 'bg-yellow-100 text-yellow-700 border-yellow-200',
  low: 'bg-blue-100 text-blue-700 border-blue-200',
}

const TYPE_LABELS = {
  robots_txt_missing: 'Robots.txt Missing',
  robots_txt_error: 'Robots.txt Error',
  robots_blocks_important: 'Robots Blocks Important Pages',
  sitemap_missing: 'Sitemap Missing',
  sitemap_error: 'Sitemap Error',
  sitemap_url_error: 'Sitemap URL Errors',
  sitemap_robots_conflict: 'Sitemap/Robots Conflict',
  http_4xx: 'Client Errors (4xx)',
  http_5xx: 'Server Errors (5xx)',
  soft_404: 'Soft 404',
  redirect_chain: 'Redirect Chains',
  redirect_loop: 'Redirect Loops',
  redirect_to_error: 'Redirect → Error',
  mixed_redirect_chain: 'Mixed Redirect Chain',
  canonical_missing: 'Canonical Missing',
  canonical_multiple: 'Multiple Canonicals',
  canonical_mismatch: 'Canonical Mismatch',
  duplicate_content: 'Duplicate Content',
  duplicate_title: 'Duplicate Titles',
  param_duplicate: 'Parameter Duplicates',
  noindex_should_index: 'Noindex on Important Pages',
  robots_noindex_conflict: 'Robots + Noindex Conflict',
  title_missing: 'Title Missing',
  title_duplicate: 'Duplicate Titles',
  title_too_short: 'Title Too Short',
  title_too_long: 'Title Too Long',
  meta_desc_missing: 'Meta Description Missing',
  meta_desc_duplicate: 'Duplicate Meta Descriptions',
  h1_missing: 'H1 Missing',
  h1_multiple: 'Multiple H1s',
  thin_content: 'Thin Content',
  broken_internal_link: 'Broken Internal Links',
  orphan_page: 'Orphan Pages',
  high_click_depth: 'High Click Depth',
  internal_nofollow: 'Internal Nofollow',
  img_missing_alt: 'Images Missing Alt',
  img_lazy_broken: 'Broken Lazy Loading',
  structured_data_invalid: 'Invalid Structured Data',
  js_render_errors: 'JS Console Errors',
  js_content_parity: 'JS Content Parity',
  js_link_parity: 'JS Link Parity',
  mobile_content_parity: 'Mobile Content Parity',
  mobile_link_parity: 'Mobile Link Parity',
  slow_ttfb: 'Slow TTFB',
  large_page: 'Large Page Size',
  hreflang_missing_self: 'Hreflang Missing Self-Ref',
  hreflang_missing_return: 'Hreflang Missing Return',
  hreflang_canonical_conflict: 'Hreflang/Canonical Conflict',
  // H1 enhancements
  h1_too_short: 'H1 Too Short',
  h1_too_long: 'H1 Too Long',
  h1_matches_title: 'H1 Matches Title',
  heading_hierarchy_gap: 'Heading Hierarchy Gap',
  // Meta tags
  meta_desc_too_short: 'Meta Description Too Short',
  meta_desc_too_long: 'Meta Description Too Long',
  og_tags_missing: 'Open Graph Tags Missing',
  twitter_card_missing: 'Twitter Card Missing',
  viewport_missing: 'Viewport Meta Missing',
  charset_missing: 'Charset Declaration Missing',
  // Structured data
  structured_data_missing: 'Structured Data Missing',
  structured_data_missing_fields: 'Structured Data Missing Fields',
  // Images
  img_oversized: 'Oversized Images',
  img_missing_dimensions: 'Images Missing Dimensions',
  img_blocked_robots: 'Images Blocked by Robots',
  // Content quality
  near_duplicate_content: 'Near-Duplicate Content',
  keyword_stuffing: 'Keyword Stuffing Detected',
  stale_content: 'Stale Content',
  // URL hygiene
  mixed_case_url: 'Mixed Case URLs',
  excessive_url_depth: 'Excessive URL Depth',
  url_special_characters: 'URL Special Characters',
  sitemap_crawl_gap: 'Sitemap/Crawl Gap',
  // Hreflang
  hreflang_invalid_lang: 'Invalid Hreflang Language',
  hreflang_x_default_missing: 'Hreflang x-default Missing',
  hreflang_to_error: 'Hreflang Points to Error',
  // Performance
  render_blocking_resource: 'Render-Blocking Resources',
  font_display_missing: 'Missing font-display',
  cls_risk: 'CLS Risk',
  // Security
  mixed_content: 'Mixed Content',
  missing_hsts: 'Missing HSTS Header',
  insecure_form_action: 'Insecure Form Action',
  http_to_https_missing: 'HTTP to HTTPS Redirect Missing',
  www_canonicalization: 'WWW Canonicalization Issue',
  // Accessibility
  missing_html_lang: 'Missing HTML Lang',
  empty_link_text: 'Empty Link Text',
  missing_form_label: 'Missing Form Labels',
  missing_skip_nav: 'Missing Skip Navigation',
  // Existing that may be missing
  index_should_noindex: 'Should Be Noindex',
  canonical_to_redirect: 'Canonical → Redirect',
  canonical_to_error: 'Canonical → Error',
  h1_parity_issue: 'H1 Parity Issue',
}

export default function IssueTable({ issues, compact = false }) {
  const [expanded, setExpanded] = useState({})

  const toggle = (idx) => {
    setExpanded(prev => ({ ...prev, [idx]: !prev[idx] }))
  }

  if (!issues || issues.length === 0) {
    return <p className="text-gray-500 text-sm">No issues found.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-left">
            <th className="pb-2 w-8"></th>
            <th className="pb-2 font-medium text-gray-600">Severity</th>
            <th className="pb-2 font-medium text-gray-600">Issue</th>
            <th className="pb-2 font-medium text-gray-600 text-right">Affected URLs</th>
            {!compact && <th className="pb-2 font-medium text-gray-600">Confidence</th>}
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, idx) => {
            const isOpen = expanded[idx]
            const sevStyle = SEVERITY_STYLES[issue.severity] || SEVERITY_STYLES.low
            return (
              <React.Fragment key={idx}>
                <tr
                  className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer"
                  onClick={() => toggle(idx)}
                >
                  <td className="py-2.5">
                    {isOpen
                      ? <ChevronDown className="w-4 h-4 text-gray-400" />
                      : <ChevronRight className="w-4 h-4 text-gray-400" />
                    }
                  </td>
                  <td className="py-2.5">
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${sevStyle}`}>
                      {(issue.severity || 'low').toUpperCase()}
                    </span>
                  </td>
                  <td className="py-2.5 font-medium text-gray-800">
                    {TYPE_LABELS[issue.issue_type] || issue.issue_type}
                  </td>
                  <td className="py-2.5 text-right font-mono text-gray-700">
                    {issue.affected_urls_count || 0}
                  </td>
                  {!compact && (
                    <td className="py-2.5 text-gray-500">
                      {Math.round((issue.confidence || 1) * 100)}%
                    </td>
                  )}
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={compact ? 4 : 5} className="px-8 py-4 bg-gray-50">
                      <div className="space-y-3">
                        {issue.how_to_fix && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase mb-1">How to Fix</p>
                            <p className="text-sm text-gray-700">{issue.how_to_fix}</p>
                          </div>
                        )}
                        {issue.why_it_matters && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Why It Matters</p>
                            <p className="text-sm text-gray-700">{issue.why_it_matters}</p>
                          </div>
                        )}
                        {issue.affected_url && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase mb-1">Example URL</p>
                            <p className="text-sm text-blue-600 break-all">{issue.affected_url}</p>
                          </div>
                        )}
                        {issue.affected_urls_sample && issue.affected_urls_sample.length > 1 && (
                          <div>
                            <p className="text-xs font-semibold text-gray-500 uppercase mb-1">
                              Sample URLs ({issue.affected_urls_sample.length})
                            </p>
                            <ul className="text-sm text-blue-600 space-y-0.5">
                              {issue.affected_urls_sample.slice(0, 5).map((u, i) => (
                                <li key={i} className="break-all">{u}</li>
                              ))}
                              {issue.affected_urls_sample.length > 5 && (
                                <li className="text-gray-500">
                                  ...and {issue.affected_urls_sample.length - 5} more
                                </li>
                              )}
                            </ul>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
