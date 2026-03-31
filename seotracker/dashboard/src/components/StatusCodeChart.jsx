import React from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

const STATUS_COLORS = {
  '2xx': '#22c55e',
  '3xx': '#eab308',
  '4xx': '#f97316',
  '5xx': '#ef4444',
}

export default function StatusCodeChart({ pages }) {
  const counts = { '2xx': 0, '3xx': 0, '4xx': 0, '5xx': 0 }

  for (const p of pages) {
    const code = p.status_code || 0
    if (code >= 200 && code < 300) counts['2xx']++
    else if (code >= 300 && code < 400) counts['3xx']++
    else if (code >= 400 && code < 500) counts['4xx']++
    else if (code >= 500) counts['5xx']++
  }

  const data = Object.entries(counts).map(([name, value]) => ({
    name,
    value,
    color: STATUS_COLORS[name],
  }))

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Status Code Distribution</h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="name" />
          <YAxis allowDecimals={false} />
          <Tooltip
            contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
            formatter={(value) => [value, 'Pages']}
          />
          <Bar dataKey="value" radius={[6, 6, 0, 0]}>
            {data.map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
