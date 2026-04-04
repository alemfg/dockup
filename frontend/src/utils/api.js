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
export const pauseWorker        = (id) => api.post(`/workers/${id}/pause`).then(r => r.data)
export const resumeWorker       = (id) => api.post(`/workers/${id}/resume`).then(r => r.data)
export const reloadWorker       = (id) => api.post(`/workers/${id}/reload`).then(r => r.data)
export const reloadAllWorkers   = () => api.post('/workers/all/reload').then(r => r.data)
export const killAllWorkers     = () => api.post('/workers/all/kill').then(r => r.data)
export const spawnWorker        = (payload) => api.post('/workers/spawn', payload).then(r => r.data)
export const reassignPairs      = (id, pairs) => api.post(`/workers/${id}/reassign`, pairs).then(r => r.data)
export const fetchContexts      = () => api.get('/analysis/contexts').then(r => r.data)
export const fetchSignals       = () => api.get('/analysis/signals').then(r => r.data)
export const fetchPrices        = () => api.get('/market/prices').then(r => r.data)
export const fetchSpreads       = () => api.get('/market/spreads').then(r => r.data)
export const fetchBalances        = () => api.get('/balances').then(r => r.data)
export const suggestRebalance     = (threshold=5) => api.post('/balances/rebalance/suggest', { threshold_pct: threshold }).then(r => r.data)
export const fetchSecurityInfo  = () => api.get('/security/workers').then(r => r.data)
export const registerWorker     = (payload) => api.post('/security/workers/register', payload).then(r => r.data)
export const revokeWorker       = (id) => api.post(`/security/workers/${id}/revoke`).then(r => r.data)
export const fetchCRSignals       = () => api.get('/cr/signals').then(r => r.data)
export const setCRForceActive     = (active) => api.post('/cr/force-active', { active }).then(r => r.data)

// Orders
export const fetchOrders          = (params = {}) => api.get('/orders', { params }).then(r => r.data)
export const fetchOpenOrders      = () => api.get('/orders/open').then(r => r.data)
export const fetchOrderLog        = (limit = 100) => api.get('/orders/log', { params: { limit } }).then(r => r.data)
export const fetchDailyPnl        = () => api.get('/orders/daily-pnl').then(r => r.data)

// Positions
export const fetchPositions       = () => api.get('/positions').then(r => r.data)
export const fetchClosedPositions = (limit = 50) => api.get('/positions/closed', { params: { limit } }).then(r => r.data)
export const closePosition        = (id, reason = 'manual') => api.post(`/positions/${id}/close`, { reason }).then(r => r.data)

// Risk
export const fetchRiskStatus      = () => api.get('/risk/status').then(r => r.data)
export const resumeAfterHalt      = () => api.post('/risk/resume').then(r => r.data)
export const fetchRiskConfig      = () => api.get('/risk/config').then(r => r.data)
export const updateRiskConfig     = (updates) => api.patch('/risk/config', updates).then(r => r.data)
export const fetchDecisionConfig  = () => api.get('/risk/decision-config').then(r => r.data)
export const updateDecisionConfig = (updates) => api.patch('/risk/decision-config', updates).then(r => r.data)

// Financials
export const fetchFinancialSummary = () => api.get('/financials/summary').then(r => r.data)
export const fetchTrades           = (limit = 50) => api.get('/financials/trades', { params: { limit } }).then(r => r.data)

// Logs
export const fetchLogs             = (limit = 200, level = '') => api.get('/logs', { params: { limit, level } }).then(r => r.data)
export const fetchTradingMode   = () => api.get('/trading/mode').then(r => r.data)
export const setTradingMode     = (mode, confirm=false) => api.post('/trading/mode', { mode, confirm }).then(r => r.data)
export const setExchangeTrading = (exchange, enabled) => api.post(`/trading/exchanges/${exchange}`, { enabled }).then(r => r.data)

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

// Config reload (v4)
export const reloadBrainConfig    = () => api.post('/config/reload/brain').then(r => r.data)
export const reloadWorkersConfig  = () => api.post('/config/reload/workers').then(r => r.data)
export const fetchCurrentConfig   = () => api.get('/config/current').then(r => r.data)

// CR daily state (v4)
export const fetchCRDailyState    = () => api.get('/cr/state').then(r => r.data)

// Graph config (v4.3)
export const fetchGraphConfig     = () => api.get('/graph/config').then(r => r.data)

// Financial events (v4.5)
export const fetchFinancialEvents = (category = '', level = '', limit = 300) =>
  api.get('/events', { params: { category, level, limit } }).then(r => r.data)
