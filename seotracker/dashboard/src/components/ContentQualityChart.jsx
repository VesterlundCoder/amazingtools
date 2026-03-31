import React from 'react'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from 'recharts'

export default function ContentQualityChart({ pages }) {
  const indexable = pages.filter(p => p.is_indexable && (p.status_code || 0) === 200)

  const hasTitle = indexable.filter(p => p.title && p.title.length > 0).length
  const hasDesc = indexable.filter(p => p.meta_description && p.meta_description.length > 0).length
  const hasH1 = indexable.filter(p => (p.h1_count || 0) > 0).length
  const goodWordCount = indexable.filter(p => (p.word_count || 0) >= 200).length
  const hasCanonical = indexable.filter(p => p.canonical_url && p.canonical_url.length > 0).length

  const total = indexable.length || 1

  const data = [
    { name: 'Title', pct: Math.round((hasTitle / total) * 100), color: '#22c55e' },
    { name: 'Meta Desc', pct: Math.round((hasDesc / total) * 100), color: '#3b82f6' },
    { name: 'H1', pct: Math.round((hasH1 / total) * 100), color: '#8b5cf6' },
    { name: '200+ Words', pct: Math.round((goodWordCount / total) * 100), color: '#f59e0b' },
    { name: 'Canonical', pct: Math.round((hasCanonical / total) * 100), color: '#06b6d4' },
  ]

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Content Quality (% of indexable pages)</h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data} layout="vertical" margin={{ top: 5, right: 30, left: 80, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis type="number" domain={[0, 100]} unit="%" />
          <YAxis type="category" dataKey="name" width={80} />
          <Tooltip
            contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
            formatter={(value) => [`${value}%`, 'Coverage']}
          />
          <Bar dataKey="pct" radius={[0, 6, 6, 0]}>
            {data.map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
