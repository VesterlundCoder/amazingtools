import React from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

export default function DepthChart({ pages }) {
  const depthCounts = {}
  for (const p of pages) {
    const d = p.depth ?? p.crawl_depth ?? 0
    depthCounts[d] = (depthCounts[d] || 0) + 1
  }

  const data = Object.entries(depthCounts)
    .map(([depth, count]) => ({ depth: `Depth ${depth}`, count }))
    .sort((a, b) => parseInt(a.depth.split(' ')[1]) - parseInt(b.depth.split(' ')[1]))

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Page Depth Distribution</h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="depth" />
          <YAxis allowDecimals={false} />
          <Tooltip
            contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
            formatter={(value) => [value, 'Pages']}
          />
          <Bar dataKey="count" fill="#6366f1" radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
