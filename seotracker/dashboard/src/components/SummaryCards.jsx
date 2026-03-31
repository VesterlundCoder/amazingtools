import React from 'react'
import { FileText, Zap, Link2, AlertTriangle, CheckCircle, Clock } from 'lucide-react'

export default function SummaryCards({
  pagesCrawled, pagesRendered, linksFound, totalIssues,
  critical, high, medium, low, indexable, elapsed,
}) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
      <Card icon={FileText} label="Pages Crawled" value={pagesCrawled} color="blue" />
      <Card icon={CheckCircle} label="Indexable" value={indexable} color="green" />
      <Card icon={Link2} label="Links Found" value={linksFound} color="indigo" />
      <Card icon={Zap} label="JS Rendered" value={pagesRendered} color="purple" />
      <Card icon={AlertTriangle} label="Total Issues" value={totalIssues} color="orange" />
      <Card icon={Clock} label="Elapsed (s)" value={elapsed || 0} color="gray" />

      {/* Severity strip */}
      <div className="col-span-2 md:col-span-3 lg:col-span-6 flex gap-2">
        <SeverityPill label="Critical" count={critical} bg="bg-red-500" />
        <SeverityPill label="High" count={high} bg="bg-orange-500" />
        <SeverityPill label="Medium" count={medium} bg="bg-yellow-500" />
        <SeverityPill label="Low" count={low} bg="bg-blue-400" />
      </div>
    </div>
  )
}

function Card({ icon: Icon, label, value, color }) {
  const colorMap = {
    blue: 'text-blue-600 bg-blue-50',
    green: 'text-green-600 bg-green-50',
    indigo: 'text-indigo-600 bg-indigo-50',
    purple: 'text-purple-600 bg-purple-50',
    orange: 'text-orange-600 bg-orange-50',
    gray: 'text-gray-600 bg-gray-50',
  }
  const cls = colorMap[color] || colorMap.gray

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-4">
      <div className="flex items-center gap-2 mb-1">
        <div className={`p-1.5 rounded-lg ${cls}`}>
          <Icon className="w-4 h-4" />
        </div>
        <span className="text-xs text-gray-500 font-medium">{label}</span>
      </div>
      <p className="text-2xl font-bold text-gray-900">
        {typeof value === 'number' ? value.toLocaleString() : value}
      </p>
    </div>
  )
}

function SeverityPill({ label, count, bg }) {
  return (
    <div className="flex items-center gap-2 bg-white rounded-lg border border-gray-200 px-3 py-2 flex-1">
      <span className={`w-3 h-3 rounded-full ${bg}`} />
      <span className="text-sm text-gray-600">{label}</span>
      <span className="text-sm font-bold text-gray-900 ml-auto">{count}</span>
    </div>
  )
}
