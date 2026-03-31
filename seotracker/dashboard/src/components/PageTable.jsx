import React from 'react'

export default function PageTable({ pages }) {
  if (!pages || pages.length === 0) {
    return <p className="text-gray-500 text-sm p-4">No pages to display.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-gray-50">
          <tr className="text-left">
            <th className="px-4 py-3 font-medium text-gray-600">URL</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-center">Status</th>
            <th className="px-4 py-3 font-medium text-gray-600">Title</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-center">H1</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Words</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Int Links</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Depth</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">TTFB</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-center">Indexable</th>
          </tr>
        </thead>
        <tbody>
          {pages.slice(0, 200).map((p, i) => {
            const statusColor = (p.status_code || 0) >= 500 ? 'bg-red-100 text-red-700'
              : (p.status_code || 0) >= 400 ? 'bg-orange-100 text-orange-700'
              : (p.status_code || 0) >= 300 ? 'bg-yellow-100 text-yellow-700'
              : 'bg-green-100 text-green-700'

            return (
              <tr key={i} className="border-b border-gray-100 hover:bg-gray-50">
                <td className="px-4 py-2.5 max-w-xs truncate text-blue-600" title={p.url}>
                  {p.url}
                </td>
                <td className="px-4 py-2.5 text-center">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor}`}>
                    {p.status_code || '-'}
                  </span>
                </td>
                <td className="px-4 py-2.5 max-w-xs truncate text-gray-700" title={p.title}>
                  {p.title || <span className="text-red-400 italic">Missing</span>}
                </td>
                <td className="px-4 py-2.5 text-center">
                  {p.h1_count === 0 ? (
                    <span className="text-red-400">0</span>
                  ) : p.h1_count > 1 ? (
                    <span className="text-orange-500 font-medium">{p.h1_count}</span>
                  ) : (
                    <span className="text-green-600">1</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-600">
                  {(p.word_count || 0).toLocaleString()}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-600">
                  {p.internal_links_count || 0}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-600">
                  {p.depth ?? '-'}
                </td>
                <td className="px-4 py-2.5 text-right font-mono text-gray-600">
                  {p.ttfb_ms ? `${Math.round(p.ttfb_ms)}ms` : '-'}
                </td>
                <td className="px-4 py-2.5 text-center">
                  {p.is_indexable === false ? (
                    <span className="text-red-500 text-xs font-medium">No</span>
                  ) : (
                    <span className="text-green-600 text-xs font-medium">Yes</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {pages.length > 200 && (
        <p className="text-sm text-gray-500 p-4">Showing 200 of {pages.length} pages</p>
      )}
    </div>
  )
}
