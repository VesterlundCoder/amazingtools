import React from 'react'
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'

const COLORS = {
  critical: '#ef4444',
  high: '#f97316',
  medium: '#eab308',
  low: '#60a5fa',
}

export default function IssuePieChart({ issueSummary }) {
  const data = [
    { name: 'Critical', value: issueSummary.critical || 0, color: COLORS.critical },
    { name: 'High', value: issueSummary.high || 0, color: COLORS.high },
    { name: 'Medium', value: issueSummary.medium || 0, color: COLORS.medium },
    { name: 'Low', value: issueSummary.low || 0, color: COLORS.low },
  ].filter(d => d.value > 0)

  if (data.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6 flex items-center justify-center">
        <p className="text-gray-500">No issues found</p>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <h3 className="text-lg font-semibold text-gray-900 mb-4">Issues by Severity</h3>
      <ResponsiveContainer width="100%" height={280}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={60}
            outerRadius={100}
            paddingAngle={3}
            dataKey="value"
            label={({ name, value }) => `${name}: ${value}`}
          >
            {data.map((entry, index) => (
              <Cell key={index} fill={entry.color} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value, name) => [value, name]}
            contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
          />
          <Legend />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
