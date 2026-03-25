import axios from 'axios'
import { useEffect, useRef, useState, useCallback } from 'react'

const api = axios.create({ baseURL: '/api' })

// ─── REST ─────────────────────────────────────────────────────────────────
export const fetchSystemStatus  = () => api.get('/system/status').then(r => r.data)
export const fetchFleetWorkers  = () => api.get('/fleet/workers').then(r => r.data)
export const fetchWorker        = (id) => api.get(`/fleet/workers/${id}`).then(r => r.data)
export const fetchFleetEvents   = (limit=100) => api.get(`/fleet/events?limit=${limit}`).then(r => r.data)
export const fetchCoverage      = () => api.get('/fleet/coverage').then(r => r.data)
export const killWorker         = (id) => api.post(`/fleet/workers/${id}/kill`).then(r => r.data)
export const restartWorker      = (id) => api.post(`/fleet/workers/${id}/restart`).then(r => r.data)
export const spawnWorker        = (payload) => api.post('/workers/spawn', payload).then(r => r.data)
export const reassignPairs      = (id, pairs) => api.post(`/workers/${id}/reassign`, pairs).then(r => r.data)
export const fetchContexts      = () => api.get('/analysis/contexts').then(r => r.data)
export const fetchSignals       = () => api.get('/analysis/signals').then(r => r.data)
export const fetchPrices        = () => api.get('/market/prices').then(r => r.data)
export const fetchSpreads       = () => api.get('/market/spreads').then(r => r.data)
export const fetchBalances      = () => api.get('/balances').then(r => r.data)
export const fetchSecurityInfo  = () => api.get('/security/workers').then(r => r.data)
export const registerWorker     = (payload) => api.post('/security/workers/register', payload).then(r => r.data)
export const revokeWorker       = (id) => api.post(`/security/workers/${id}/revoke`).then(r => r.data)
export const fetchCRSignals     = () => api.get('/cr/signals').then(r => r.data)

// ─── WebSocket Hook ───────────────────────────────────────────────────────
export function useWebSocket(path) {
  const [data,   setData]   = useState(null)
  const [status, setStatus] = useState('connecting')
  const wsRef    = useRef(null)
  const timerRef = useRef(null)

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws    = new WebSocket(`${proto}://${window.location.host}${path}`)
    wsRef.current = ws
    ws.onopen    = () => setStatus('connected')
    ws.onclose   = () => { setStatus('reconnecting'); timerRef.current = setTimeout(connect, 3000) }
    ws.onerror   = () => ws.close()
    ws.onmessage = (e) => { try { setData(JSON.parse(e.data)) } catch {} }
  }, [path])

  useEffect(() => {
    connect()
    return () => { clearTimeout(timerRef.current); wsRef.current?.close() }
  }, [connect])

  return { data, status }
}

// ─── Polling Hook ─────────────────────────────────────────────────────────
export function usePolling(fetchFn, interval = 5000) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const result = await fetchFn()
        if (!cancelled) { setData(result); setError(null) }
      } catch (e) {
        if (!cancelled) setError(e.message)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, interval)
    return () => { cancelled = true; clearInterval(id) }
  }, [interval])

  return { data, loading, error }
}
