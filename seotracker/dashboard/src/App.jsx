import React, { useState, useCallback } from 'react'
import {
  Search, Upload, AlertTriangle, CheckCircle, XCircle, Info,
  Globe, Link2, FileText, Image, Code, Smartphone, Zap,
  ChevronDown, ChevronRight, ExternalLink, BarChart3, Shield,
  Wifi, WifiOff, Download, RefreshCw
} from 'lucide-react'
import SummaryCards from './components/SummaryCards'
import IssueTable from './components/IssueTable'
import PageTable from './components/PageTable'
import IssuePieChart from './components/IssuePieChart'
import StatusCodeChart from './components/StatusCodeChart'
import DepthChart from './components/DepthChart'
import ContentQualityChart from './components/ContentQualityChart'
import { useApi } from './hooks/useApi'

const TABS = [
  { id: 'overview', label: 'Overview', icon: BarChart3 },
  { id: 'issues', label: 'Issues', icon: AlertTriangle },
  { id: 'pages', label: 'Pages', icon: FileText },
  { id: 'redirects', label: 'Redirects', icon: Link2 },
  { id: 'indexability', label: 'Indexability', icon: Shield },
]

export default function App() {
  const [data, setData] = useState(null)
  const [activeTab, setActiveTab] = useState('overview')
  const [loading, setLoading] = useState(false)

  const handleFileUpload = useCallback(async (fileType, file) => {
    const text = await file.text()
    const json = JSON.parse(text)
    setData(prev => ({ ...prev, [fileType]: json }))
  }, [])

  const handleDrop = useCallback(async (e) => {
    e.preventDefault()
    setLoading(true)
    const files = Array.from(e.dataTransfer.files)
    const newData = { ...data }

    for (const file of files) {
      try {
        const text = await file.text()
        const json = JSON.parse(text)
        if (file.name.includes('summary')) newData.summary = json
        else if (file.name.includes('issues')) newData.issues = json
        else if (file.name.includes('pages')) newData.pages = json
        else if (file.name.includes('links')) newData.links = json
      } catch (err) {
        console.error(`Failed to parse ${file.name}:`, err)
      }
    }

    setData(newData)
    setLoading(false)
  }, [data])

  const handleDragOver = (e) => e.preventDefault()

  const handleFolderSelect = async () => {
    const input = document.createElement('input')
    input.type = 'file'
    input.multiple = true
    input.accept = '.json'
    input.onchange = async (e) => {
      setLoading(true)
      const files = Array.from(e.target.files)
      const newData = {}
      for (const file of files) {
        try {
          const text = await file.text()
          const json = JSON.parse(text)
          if (file.name.includes('summary')) newData.summary = json
          else if (file.name.includes('issues')) newData.issues = json
          else if (file.name.includes('pages')) newData.pages = json
          else if (file.name.includes('links')) newData.links = json
        } catch (err) {
          console.error(`Failed to parse ${file.name}:`, err)
        }
      }
      setData(newData)
      setLoading(false)
    }
    input.click()
  }

  // API connection state
  const [apiMode, setApiMode] = useState(false)
  const [apiUrl, setApiUrl] = useState('http://localhost:8000/api/v1')
  const [apiConnected, setApiConnected] = useState(false)
  const [apiSiteId, setApiSiteId] = useState('')
  const api = useApi(apiUrl)

  const connectApi = useCallback(async () => {
    try {
      const report = await api.fetchLatestReport(apiSiteId)
      const issues = await api.fetchIssues(report.run.id, null, 500)
      setData({
        summary: {
          domain: apiSiteId,
          timestamp: report.run.completed_at,
          stats: {
            pages_crawled: report.run.pages_crawled,
            pages_rendered: report.run.pages_rendered,
          },
          issue_summary: {
            critical: report.issue_summary.critical,
            high: report.issue_summary.high,
            medium: report.issue_summary.medium,
            low: report.issue_summary.low,
          },
          total_issues: report.issue_summary.total,
        },
        issues: issues.map(i => ({
          ...i,
          issue_type: i.issue_type?.value || i.issue_type,
          severity: i.severity?.value || i.severity,
        })),
        pages: [],
        links: [],
        _runId: report.run.id,
        _apiMode: true,
      })
      setApiConnected(true)
    } catch (err) {
      alert(`API Error: ${err.message}`)
    }
  }, [api, apiSiteId])

  if (!data || !data.summary) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center p-8">
        <div className="max-w-xl w-full space-y-6">
          {/* File upload mode */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            className="bg-white rounded-2xl shadow-lg border-2 border-dashed border-gray-300 p-10 text-center hover:border-blue-400 transition-colors cursor-pointer"
            onClick={handleFolderSelect}
          >
            <Upload className="w-12 h-12 text-gray-400 mx-auto mb-3" />
            <h1 className="text-2xl font-bold text-gray-800 mb-2">SEO Crawler Dashboard</h1>
            <p className="text-gray-500 mb-4">
              Drop your crawl output JSON files here, or click to select files.
            </p>
            <p className="text-sm text-gray-400">
              Expected files: summary.json, pages.json, issues.json, links.json
            </p>
            {loading && (
              <div className="mt-4 text-blue-600 font-medium">Loading files...</div>
            )}
          </div>

          {/* Divider */}
          <div className="flex items-center gap-3">
            <div className="flex-1 border-t border-gray-300" />
            <span className="text-sm text-gray-400 font-medium">OR CONNECT TO API</span>
            <div className="flex-1 border-t border-gray-300" />
          </div>

          {/* API connection mode */}
          <div className="bg-white rounded-2xl shadow-lg border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Wifi className="w-5 h-5 text-blue-600" />
              <h2 className="text-lg font-semibold text-gray-800">Connect to API</h2>
            </div>
            <div className="space-y-3">
              <div>
                <label className="text-sm font-medium text-gray-600">API Base URL</label>
                <input
                  type="text"
                  value={apiUrl}
                  onChange={e => setApiUrl(e.target.value)}
                  className="w-full mt-1 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                  placeholder="http://localhost:8000/api/v1"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-gray-600">Site ID (UUID)</label>
                <input
                  type="text"
                  value={apiSiteId}
                  onChange={e => setApiSiteId(e.target.value)}
                  className="w-full mt-1 px-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                  placeholder="Enter site UUID..."
                />
              </div>
              <button
                onClick={connectApi}
                disabled={!apiSiteId || api.loading}
                className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {api.loading ? 'Connecting...' : 'Load Latest Report'}
              </button>
              {api.error && (
                <p className="text-sm text-red-600">{api.error}</p>
              )}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const summary = data.summary || {}
  const pages = data.pages || []
  const issues = data.issues || []
  const links = data.links || []

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Search className="w-7 h-7 text-blue-600" />
            <div>
              <h1 className="text-xl font-bold text-gray-900">SEO Crawler</h1>
              <p className="text-sm text-gray-500">{summary.domain || 'Unknown domain'}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {data._apiMode && (
              <span className="flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-1 rounded-full">
                <Wifi className="w-3 h-3" /> API Connected
              </span>
            )}
            <span className="text-sm text-gray-500">
              {summary.timestamp ? new Date(summary.timestamp).toLocaleDateString() : ''}
            </span>
            {data._runId && (
              <a
                href={`${apiUrl}/runs/${data._runId}/export/xlsx`}
                className="flex items-center gap-1 px-3 py-1.5 text-sm bg-green-50 text-green-700 hover:bg-green-100 rounded-lg transition-colors"
              >
                <Download className="w-3.5 h-3.5" /> XLSX
              </a>
            )}
            <button
              onClick={() => { setData(null); setApiConnected(false) }}
              className="flex items-center gap-1 px-3 py-1.5 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" /> New Report
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="max-w-7xl mx-auto px-4">
          <nav className="flex gap-1">
            {TABS.map(tab => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                    isActive
                      ? 'border-blue-600 text-blue-600'
                      : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                  }`}
                >
                  <Icon className="w-4 h-4" />
                  {tab.label}
                </button>
              )
            })}
          </nav>
        </div>
      </header>

      {/* Content */}
      <main className="max-w-7xl mx-auto px-4 py-6">
        {activeTab === 'overview' && (
          <OverviewTab summary={summary} pages={pages} issues={issues} links={links} />
        )}
        {activeTab === 'issues' && (
          <IssuesTab issues={issues} />
        )}
        {activeTab === 'pages' && (
          <PagesTab pages={pages} />
        )}
        {activeTab === 'redirects' && (
          <RedirectsTab pages={pages} />
        )}
        {activeTab === 'indexability' && (
          <IndexabilityTab pages={pages} />
        )}
      </main>
    </div>
  )
}

function OverviewTab({ summary, pages, issues, links }) {
  const stats = summary.stats || {}
  const issueSummary = summary.issue_summary || {}

  const indexable = pages.filter(p => p.is_indexable && p.status_code === 200).length
  const noindex = pages.filter(p => p.is_noindex).length
  const errors = pages.filter(p => (p.status_code || 0) >= 400).length
  const redirects = pages.filter(p => (p.redirect_chain || []).length > 0).length

  return (
    <div className="space-y-6">
      <SummaryCards
        pagesCrawled={stats.pages_crawled || pages.length}
        pagesRendered={stats.pages_rendered || 0}
        linksFound={stats.links_found || links.length}
        totalIssues={summary.total_issues || issues.length}
        critical={issueSummary.critical || 0}
        high={issueSummary.high || 0}
        medium={issueSummary.medium || 0}
        low={issueSummary.low || 0}
        indexable={indexable}
        elapsed={stats.elapsed_seconds}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <IssuePieChart issueSummary={issueSummary} />
        <StatusCodeChart pages={pages} />
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <QuickStat label="Indexable" value={indexable} color="text-green-600" />
        <QuickStat label="Noindex" value={noindex} color="text-orange-600" />
        <QuickStat label="Errors (4xx/5xx)" value={errors} color="text-red-600" />
        <QuickStat label="Redirected" value={redirects} color="text-yellow-600" />
      </div>

      {pages.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <DepthChart pages={pages} />
          <ContentQualityChart pages={pages} />
        </div>
      )}

      {/* Top issues preview */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Top Issues</h3>
        <IssueTable issues={issues.slice(0, 10)} compact />
      </div>
    </div>
  )
}

function QuickStat({ label, value, color }) {
  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
      <p className="text-sm text-gray-500">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value}</p>
    </div>
  )
}

function IssuesTab({ issues }) {
  const [filter, setFilter] = useState('all')
  const [search, setSearch] = useState('')

  const filtered = issues.filter(i => {
    if (filter !== 'all' && i.severity !== filter) return false
    if (search && !i.issue_type.toLowerCase().includes(search.toLowerCase())
        && !(i.affected_url || '').toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const counts = {
    all: issues.length,
    critical: issues.filter(i => i.severity === 'critical').length,
    high: issues.filter(i => i.severity === 'high').length,
    medium: issues.filter(i => i.severity === 'medium').length,
    low: issues.filter(i => i.severity === 'low').length,
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        {['all', 'critical', 'high', 'medium', 'low'].map(sev => (
          <button
            key={sev}
            onClick={() => setFilter(sev)}
            className={`px-3 py-1.5 text-sm rounded-lg font-medium transition-colors ${
              filter === sev
                ? sev === 'critical' ? 'bg-red-100 text-red-700'
                : sev === 'high' ? 'bg-orange-100 text-orange-700'
                : sev === 'medium' ? 'bg-yellow-100 text-yellow-700'
                : sev === 'low' ? 'bg-blue-100 text-blue-700'
                : 'bg-gray-200 text-gray-800'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {sev === 'all' ? 'All' : sev.charAt(0).toUpperCase() + sev.slice(1)} ({counts[sev]})
          </button>
        ))}
        <input
          type="text"
          placeholder="Search issues..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="ml-auto px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
        />
      </div>
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <IssueTable issues={filtered} />
      </div>
    </div>
  )
}

function PagesTab({ pages }) {
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  const filtered = pages.filter(p => {
    if (search && !(p.url || '').toLowerCase().includes(search.toLowerCase())) return false
    if (statusFilter === '2xx' && (p.status_code < 200 || p.status_code >= 300)) return false
    if (statusFilter === '3xx' && (p.status_code < 300 || p.status_code >= 400)) return false
    if (statusFilter === '4xx' && (p.status_code < 400 || p.status_code >= 500)) return false
    if (statusFilter === '5xx' && p.status_code < 500) return false
    return true
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        {['all', '2xx', '3xx', '4xx', '5xx'].map(s => (
          <button
            key={s}
            onClick={() => setStatusFilter(s)}
            className={`px-3 py-1.5 text-sm rounded-lg font-medium transition-colors ${
              statusFilter === s ? 'bg-blue-100 text-blue-700' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {s === 'all' ? 'All' : s.toUpperCase()}
          </button>
        ))}
        <input
          type="text"
          placeholder="Search URLs..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="ml-auto px-3 py-1.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none w-64"
        />
      </div>
      <div className="bg-white rounded-xl shadow-sm border border-gray-200">
        <PageTable pages={filtered} />
      </div>
    </div>
  )
}

function RedirectsTab({ pages }) {
  const redirected = pages.filter(p => (p.redirect_chain || []).length > 0)

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold mb-4">Redirect Chains ({redirected.length})</h3>
      {redirected.length === 0 ? (
        <p className="text-gray-500">No redirects detected in this crawl.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left">
                <th className="pb-2 font-medium text-gray-600">URL</th>
                <th className="pb-2 font-medium text-gray-600">Final URL</th>
                <th className="pb-2 font-medium text-gray-600">Hops</th>
                <th className="pb-2 font-medium text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody>
              {redirected.map((p, i) => (
                <tr key={i} className="border-b border-gray-100">
                  <td className="py-2 text-blue-600 truncate max-w-xs">{p.url}</td>
                  <td className="py-2 text-gray-700 truncate max-w-xs">{p.final_url}</td>
                  <td className="py-2">{(p.redirect_chain || []).length}</td>
                  <td className="py-2">
                    <StatusBadge code={p.status_code} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function IndexabilityTab({ pages }) {
  const indexable = pages.filter(p => p.is_indexable && p.status_code === 200)
  const nonIndexable = pages.filter(p => !p.is_indexable || (p.status_code || 0) >= 400)

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-green-50 rounded-xl border border-green-200 p-6">
          <p className="text-sm text-green-700 font-medium">Indexable</p>
          <p className="text-3xl font-bold text-green-800">{indexable.length}</p>
        </div>
        <div className="bg-red-50 rounded-xl border border-red-200 p-6">
          <p className="text-sm text-red-700 font-medium">Non-Indexable</p>
          <p className="text-3xl font-bold text-red-800">{nonIndexable.length}</p>
        </div>
      </div>

      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <h3 className="text-lg font-semibold mb-4">Non-Indexable Pages</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 text-left">
                <th className="pb-2 font-medium text-gray-600">URL</th>
                <th className="pb-2 font-medium text-gray-600">Status</th>
                <th className="pb-2 font-medium text-gray-600">Reason</th>
                <th className="pb-2 font-medium text-gray-600">Robots</th>
                <th className="pb-2 font-medium text-gray-600">Noindex</th>
              </tr>
            </thead>
            <tbody>
              {nonIndexable.slice(0, 100).map((p, i) => (
                <tr key={i} className="border-b border-gray-100">
                  <td className="py-2 text-blue-600 truncate max-w-md">{p.url}</td>
                  <td className="py-2"><StatusBadge code={p.status_code} /></td>
                  <td className="py-2 text-gray-600">{p.indexability_reason || '-'}</td>
                  <td className="py-2">{p.robots_txt_allowed === false ? '❌ Blocked' : '✅'}</td>
                  <td className="py-2">{p.is_noindex ? '❌ Yes' : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {nonIndexable.length > 100 && (
            <p className="text-sm text-gray-500 mt-2">Showing 100 of {nonIndexable.length}</p>
          )}
        </div>
      </div>
    </div>
  )
}

function StatusBadge({ code }) {
  if (!code) return <span className="text-gray-400">-</span>
  const color = code >= 500 ? 'bg-red-100 text-red-700'
    : code >= 400 ? 'bg-orange-100 text-orange-700'
    : code >= 300 ? 'bg-yellow-100 text-yellow-700'
    : 'bg-green-100 text-green-700'
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>{code}</span>
}
