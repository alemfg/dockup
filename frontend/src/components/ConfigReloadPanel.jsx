import React, { useState } from 'react'
import { usePolling, fetchCurrentConfig, reloadBrainConfig, reloadWorkersConfig } from '../utils/api'
import { Card, Spinner } from './ui'

function ReloadButton({ label, description, onReload, color = 'green' }) {
  const [loading,  setLoading]  = useState(false)
  const [result,   setResult]   = useState(null)
  const [error,    setError]    = useState(null)

  const handle = async () => {
    setLoading(true); setResult(null); setError(null)
    try {
      const r = await onReload()
      setResult(r)
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    } finally {
      setLoading(false)
    }
  }

  const btnColor = color === 'blue'
    ? 'bg-blue-700 hover:bg-blue-600'
    : 'bg-green-700 hover:bg-green-600'

  return (
    <div className="border border-gray-800 rounded-xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-gray-200">{label}</p>
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
        </div>
        <button
          onClick={handle}
          disabled={loading}
          className={`shrink-0 text-xs px-4 py-2 rounded-lg text-white font-medium transition-colors ${btnColor} disabled:opacity-50`}
        >
          {loading ? '⟳ Reloading...' : '↺ Reload'}
        </button>
      </div>

      {result && (
        <div className="mt-3 bg-green-900/20 border border-green-800 rounded-lg p-3 text-xs text-green-300">
          ✅ {result.message}
          {result.trading_mode && (
            <span className="ml-2 text-gray-400">trading_mode: {result.trading_mode}</span>
          )}
          {result.workers && (
            <span className="ml-2 text-gray-400">
              {result.workers.length} workers notified
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="mt-3 bg-red-900/20 border border-red-800 rounded-lg p-3 text-xs text-red-300">
          ⚠️ {error}
        </div>
      )}
    </div>
  )
}

function ConfigValue({ label, value }) {
  const display = Array.isArray(value)
    ? value.join(', ')
    : typeof value === 'object'
    ? JSON.stringify(value)
    : String(value ?? '—')

  return (
    <div className="flex justify-between items-start py-1.5 border-b border-gray-800 last:border-0">
      <span className="text-xs text-gray-500 w-48 shrink-0">{label}</span>
      <span className="text-xs text-gray-300 text-right font-mono break-all">{display}</span>
    </div>
  )
}

export default function ConfigReloadPanel() {
  const { data: cfg, loading } = usePolling(fetchCurrentConfig, 10000)

  if (loading) return <Card title="Config & Reload"><Spinner /></Card>

  return (
    <div className="space-y-4">
      {/* Reload buttons */}
      <Card
        title="Hot Reload"
        subtitle="Apply config.yaml changes without restarting — ports and Redis host require restart"
      >
        <div className="space-y-3">
          <ReloadButton
            label="Reload Brain Config"
            description="Re-reads config.yaml + env vars. Updates decision rules, risk limits, CR plugin config, trading mode, and analysis weights instantly."
            onReload={reloadBrainConfig}
            color="green"
          />
          <ReloadButton
            label="Reload Workers Config"
            description="Broadcasts a reload command to all connected workers via Redis. Workers re-read PAIRS, TICK_INTERVAL_MS, CANDLE_TIMEFRAMES and other env vars."
            onReload={reloadWorkersConfig}
            color="blue"
          />
        </div>

        <p className="text-xs text-gray-600 mt-4 border-t border-gray-800 pt-3">
          Changes that always require restart: BRAIN_API_PORT, BRAIN_METRICS_PORT,
          REDIS_HOST, POSTGRES_HOST, EXCHANGE, WORKER_ID.
        </p>
      </Card>

      {/* Live config snapshot */}
      {cfg && (
        <Card title="Active Config Snapshot" subtitle="Current values in memory">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Brain</p>
              <ConfigValue label="Version"       value={cfg.version} />
              <ConfigValue label="Trading Mode"  value={cfg.trading_mode} />
              <ConfigValue label="Dry Run"       value={String(cfg.dry_run)} />
              <ConfigValue label="Log Level"     value={cfg.log_level} />
              <ConfigValue label="Heartbeat TTL" value={`${cfg.heartbeat_ttl}s`} />
              <ConfigValue label="Stale Threshold" value={`${cfg.stale_threshold_s}s`} />
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Decision</p>
              <ConfigValue label="CR Min Score"      value={cfg.decision?.cr_min_score} />
              <ConfigValue label="CR Min RR"         value={cfg.decision?.cr_min_rr} />
              <ConfigValue label="Max Capital/Trade" value={`$${cfg.decision?.max_capital_per_trade}`} />
              <ConfigValue label="Cooldown"          value={`${cfg.decision?.cooldown_seconds}s`} />
              <ConfigValue label="Max Concurrent"    value={cfg.decision?.max_concurrent_orders} />
            </div>
            <div className="mt-4">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Risk</p>
              <ConfigValue label="Max Daily Loss"    value={`$${cfg.risk?.max_daily_loss_usd}`} />
              <ConfigValue label="Max Drawdown"      value={`${cfg.risk?.max_drawdown_pct}%`} />
              <ConfigValue label="Max Consec. Losses" value={cfg.risk?.max_consecutive_losses} />
            </div>
            <div className="mt-4">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">CRT Model</p>
              <ConfigValue label="Timezone"       value={cfg.cr_9am?.timezone} />
              <ConfigValue label="Active Window"  value={`${cfg.cr_9am?.active_from}:00–${cfg.cr_9am?.active_to}:00`} />
              <ConfigValue label="Reversal Range" value={cfg.cr_9am?.reversal_range ?? '5am'} />
              <ConfigValue label="Continuation"   value={cfg.cr_9am?.continuation_range ?? '1am'} />
              <ConfigValue label="TP1 %"          value={`${((cfg.cr_9am?.tp1_pct_of_range ?? 0.5) * 100).toFixed(0)}%`} />
              <ConfigValue label="Min Score"      value={cfg.cr_9am?.min_setup_score} />
              <ConfigValue label="Pairs"          value={cfg.cr_9am?.pairs} />
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
