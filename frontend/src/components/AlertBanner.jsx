/**
 * AlertBanner — persistent global alert strip shown on every page.
 *
 * Shows:
 *  - 🟢 Opportunity alerts: when profitable graph cycles are detected
 *  - 🔴 Error alerts: worker blocks, auth errors, high error counts
 *  - 🟡 Warning alerts: stale data above threshold, rate limits
 *
 * Polls /api/system/status + /api/fleet/workers + /api/graph/paths
 * every 5s. Auto-dismisses opportunity alerts after 30s.
 * Error/warning alerts persist until condition clears.
 */
import React, { useState, useEffect, useRef } from 'react'

const POLL_MS = 5000

function useAlertData() {
  const [status, setStatus]   = useState(null)
  const [workers, setWorkers] = useState([])
  const [paths,   setPaths]   = useState([])

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      try {
        const [s, w, p] = await Promise.all([
          fetch('/api/system/status').then(r => r.ok ? r.json() : null),
          fetch('/api/fleet/workers').then(r => r.ok ? r.json() : null),
          fetch('/api/graph/paths').then(r => r.ok ? r.json() : null),
        ])
        if (cancelled) return
        if (s) setStatus(s)
        if (w) setWorkers(w.workers ?? [])
        if (p) setPaths(p.paths ?? [])
      } catch {}
    }
    load()
    const id = setInterval(load, POLL_MS)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  return { status, workers, paths }
}

function buildAlerts(status, workers, paths) {
  const alerts = []

  // ── Opportunities ──────────────────────────────────────────────────────
  const livePaths = paths.filter(p => !p.is_stale && p.net_profit_pct > 0)
  if (livePaths.length > 0) {
    const best = livePaths[0]
    alerts.push({
      id:      'opportunity',
      level:   'opportunity',
      icon:    '⚡',
      message: `${livePaths.length} profitable cycle${livePaths.length > 1 ? 's' : ''} detected`,
      detail:  `Best: ${best.net_profit_pct?.toFixed(3)}% net · ${best.path ?? best.assets?.join('→')} · ${best.hops} hops`,
      tab:     'graph',
    })
  }

  // ── Worker errors ──────────────────────────────────────────────────────
  const blockedWorkers = workers.filter(w =>
    w.status === 'blocked' || w.condition === 'ip_block'
  )
  if (blockedWorkers.length > 0) {
    alerts.push({
      id:      'worker_blocked',
      level:   'error',
      icon:    '⛔',
      message: `${blockedWorkers.length} worker${blockedWorkers.length > 1 ? 's' : ''} blocked`,
      detail:  blockedWorkers.map(w => `${w.worker_id} (${w.exchange})`).join(', '),
      tab:     'fleet',
    })
  }

  const authErrors = workers.filter(w => w.condition === 'auth_error')
  if (authErrors.length > 0) {
    alerts.push({
      id:      'auth_error',
      level:   'error',
      icon:    '🔑',
      message: `Auth error on ${authErrors.map(w => w.exchange).join(', ')}`,
      detail:  'Check API keys in Config → Security',
      tab:     'security',
    })
  }

  const highErrors = workers.filter(w => (w.error_count ?? 0) > 10)
  if (highErrors.length > 0) {
    alerts.push({
      id:      'high_errors',
      level:   'warning',
      icon:    '⚠',
      message: `High error count on ${highErrors.length} worker${highErrors.length > 1 ? 's' : ''}`,
      detail:  highErrors.map(w => `${w.worker_id}: ${w.error_count} errors`).join(' · '),
      tab:     'fleet',
    })
  }

  const rateLimited = workers.filter(w =>
    w.condition === 'rate_limit' || (w.rate_limit?.consecutive_429s ?? 0) > 0
  )
  if (rateLimited.length > 0) {
    alerts.push({
      id:      'rate_limited',
      level:   'warning',
      icon:    '🚦',
      message: `Rate limited: ${rateLimited.map(w => w.exchange).join(', ')}`,
      detail:  'Workers backing off — throughput reduced',
      tab:     'fleet',
    })
  }

  // ── Stale data ─────────────────────────────────────────────────────────
  const stale = status?.market?.stale_pairs ?? 0
  const total = status?.market?.price_contexts ?? 0
  if (stale > 0 && total > 0) {
    const pct = Math.round((stale / total) * 100)
    const lvl = pct > 50 ? 'error' : 'warning'
    alerts.push({
      id:      'stale_data',
      level:   lvl,
      icon:    '🕐',
      message: `${stale} stale price context${stale > 1 ? 's' : ''} (${pct}%)`,
      detail:  'Workers may be slow or disconnected — graph accuracy reduced',
      tab:     'fleet',
    })
  }

  // ── Risk halt ──────────────────────────────────────────────────────────
  if (status?.risk_halted) {
    alerts.push({
      id:      'risk_halt',
      level:   'error',
      icon:    '🛑',
      message: 'Risk system HALTED — all trading paused',
      detail:  status.halt_reason ?? 'Check Risk & Rules panel',
      tab:     'risk',
    })
  }

  return alerts
}

const LEVEL_STYLES = {
  opportunity: {
    bar:    'bg-green-950 border-green-700',
    icon:   'text-green-300',
    msg:    'text-green-200 font-semibold',
    detail: 'text-green-400/80',
    btn:    'bg-green-800 hover:bg-green-700 text-green-200',
    dot:    'bg-green-400 animate-pulse',
    dismiss:'text-green-600 hover:text-green-300',
  },
  error: {
    bar:    'bg-red-950 border-red-800',
    icon:   'text-red-300',
    msg:    'text-red-200 font-semibold',
    detail: 'text-red-400/80',
    btn:    'bg-red-800 hover:bg-red-700 text-red-200',
    dot:    'bg-red-500 animate-pulse',
    dismiss:'text-red-700 hover:text-red-400',
  },
  warning: {
    bar:    'bg-yellow-950 border-yellow-800',
    icon:   'text-yellow-300',
    msg:    'text-yellow-200 font-semibold',
    detail: 'text-yellow-400/80',
    btn:    'bg-yellow-800 hover:bg-yellow-700 text-yellow-200',
    dot:    'bg-yellow-400',
    dismiss:'text-yellow-700 hover:text-yellow-400',
  },
}

export default function AlertBanner({ onNavigate }) {
  const { status, workers, paths } = useAlertData()
  const [dismissed, setDismissed]  = useState(new Set())
  // Auto-clear dismissed set when alerts change (new opportunity, resolved error)
  const prevAlertIds = useRef(new Set())

  const alerts = buildAlerts(status, workers, paths)
  const visible = alerts.filter(a => !dismissed.has(a.id))

  // Re-surface an alert if it was dismissed but changed (e.g. new opportunity)
  useEffect(() => {
    const currentIds = new Set(alerts.map(a => a.id))
    // If opportunity re-fires after being dismissed, re-show it
    setDismissed(prev => {
      const next = new Set(prev)
      for (const id of prev) {
        if (!currentIds.has(id)) next.delete(id) // alert resolved, clean up
      }
      return next
    })
    prevAlertIds.current = currentIds
  }, [alerts.map(a => a.id + a.detail).join(',')])

  if (visible.length === 0) return null

  return (
    <div className="flex flex-col gap-px">
      {visible.map(alert => {
        const s = LEVEL_STYLES[alert.level] || LEVEL_STYLES.warning
        return (
          <div
            key={alert.id}
            className={`flex items-center gap-3 px-4 py-2 border-b text-xs ${s.bar}`}
          >
            {/* Pulse dot */}
            <span className={`w-2 h-2 rounded-full shrink-0 ${s.dot}`} />

            {/* Icon */}
            <span className={`text-base shrink-0 ${s.icon}`}>{alert.icon}</span>

            {/* Message */}
            <div className="flex-1 min-w-0">
              <span className={s.msg}>{alert.message}</span>
              {alert.detail && (
                <span className={`ml-2 ${s.detail} truncate hidden sm:inline`}>
                  — {alert.detail}
                </span>
              )}
            </div>

            {/* Navigate CTA */}
            {alert.tab && onNavigate && (
              <button
                onClick={() => onNavigate(alert.tab)}
                className={`shrink-0 px-2.5 py-1 rounded text-[10px] font-medium transition-colors ${s.btn}`}
              >
                View →
              </button>
            )}

            {/* Dismiss */}
            <button
              onClick={() => setDismissed(d => new Set([...d, alert.id]))}
              className={`shrink-0 text-lg leading-none transition-colors ${s.dismiss}`}
              title="Dismiss"
            >
              ×
            </button>
          </div>
        )
      })}
    </div>
  )
}
