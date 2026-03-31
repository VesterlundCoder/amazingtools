import { useState, useCallback } from 'react'

const DEFAULT_API_BASE = 'http://localhost:8000/api/v1'

export function useApi(baseUrl = DEFAULT_API_BASE) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const request = useCallback(async (path, options = {}) => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${baseUrl}${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `HTTP ${res.status}`)
      }
      return await res.json()
    } catch (err) {
      setError(err.message)
      throw err
    } finally {
      setLoading(false)
    }
  }, [baseUrl])

  const fetchSites = useCallback((tenantId) =>
    request(`/tenants/${tenantId}/sites`), [request])

  const fetchRuns = useCallback((siteId, limit = 20) =>
    request(`/sites/${siteId}/runs?limit=${limit}`), [request])

  const fetchLatestReport = useCallback((siteId) =>
    request(`/sites/${siteId}/runs/latest`), [request])

  const fetchIssues = useCallback((runId, severity, limit = 200) => {
    let path = `/runs/${runId}/issues?limit=${limit}`
    if (severity) path += `&severity=${severity}`
    return request(path)
  }, [request])

  const fetchTrends = useCallback((siteId, months = 6) =>
    request(`/sites/${siteId}/trends?months=${months}`), [request])

  const triggerRun = useCallback((siteId) =>
    request(`/sites/${siteId}/runs`, { method: 'POST' }), [request])

  const cancelRun = useCallback((runId) =>
    request(`/runs/${runId}/cancel`, { method: 'POST' }), [request])

  const fetchQuota = useCallback((tenantId) =>
    request(`/tenants/${tenantId}/quota`), [request])

  return {
    loading,
    error,
    request,
    fetchSites,
    fetchRuns,
    fetchLatestReport,
    fetchIssues,
    fetchTrends,
    triggerRun,
    cancelRun,
    fetchQuota,
  }
}
