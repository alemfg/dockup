import React, { useState } from 'react'
import { usePolling, fetchCurrentConfig, reloadBrainConfig, reloadWorkersConfig } from '../utils/api'
import { Card, Spinner } from './ui'
import { Tip, TipIcon } from './Tooltip'

function ReloadButton({ label, description, onReload, color = 'green', tooltip }) {
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
          <div className="flex items-center">
            <p className="text-sm font-semibold text-gray-200">{label}</p>
            {tooltip && <TipIcon text={tooltip} pos="right" wide />}
          </div>
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
          {result.trading_mode && <span className="ml-2 text-gray-400">trading_mode: {result.trading_mode}</span>}
          {result.workers && <span className="ml-2 text-gray-400">{result.workers.length} workers notified</span>}
          {result.graph && (
            <span className="ml-2 text-gray-400">
              graph: {result.graph.algorithm} · max_hops={result.graph.max_hops} · min_profit={result.graph.min_profit_pct}%
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

function ConfigValue({ label, value, tooltip }) {
  const display = Array.isArray(value)
    ? value.join(', ')
    : typeof value === 'object'
    ? JSON.stringify(value)
    : String(value ?? '—')
  return (
    <div className="flex justify-between items-start py-1.5 border-b border-gray-800 last:border-0">
      <span className="text-xs text-gray-500 w-48 shrink-0 flex items-center">
        {label}
        {tooltip && <TipIcon text={tooltip} pos="right" wide />}
      </span>
      <span className="text-xs text-gray-300 text-right font-mono break-all">{display}</span>
    </div>
  )
}

export default function ConfigReloadPanel() {
  const { data: cfg, loading } = usePolling(fetchCurrentConfig, 10000)
  if (loading) return <Card title="Config & Reload"><Spinner /></Card>
  return (
    <div className="space-y-4">
      <Card title="Hot Reload" subtitle="Apply config.yaml changes without restarting — ports and Redis host require restart">
        <div className="space-y-3">
          <ReloadButton
            label="Reload Brain Config"
            description="Re-reads config.yaml + .env. Updates decision rules, risk limits, CR plugin config, trading mode, and analysis weights instantly."
            onReload={reloadBrainConfig}
            color="green"
            tooltip="Applies all config.yaml AND .env changes immediately — including new API keys added to .env after startup. Changes to BRAIN_API_PORT, REDIS_HOST, or POSTGRES_HOST still require a full container restart."
          />
          <ReloadButton
            label="Reload Workers Config"
            description="Broadcasts a reload command to all connected workers via Redis. Workers re-read PAIRS, TICK_INTERVAL_MS, CANDLE_TIMEFRAMES and other env vars."
            onReload={reloadWorkersConfig}
            color="blue"
            tooltip="Sends a soft reload signal over Redis Streams to every live worker. Each worker re-reads its .env (including new exchange API keys), then re-applies PAIRS, TICK_INTERVAL_MS, CANDLE_TIMEFRAMES without restarting. Workers that are offline when this fires won't receive it until they reconnect."
          />
        </div>
        <p className="text-xs text-gray-600 mt-4 border-t border-gray-800 pt-3">
          Changes that always require restart: BRAIN_API_PORT, BRAIN_METRICS_PORT, REDIS_HOST, POSTGRES_HOST, EXCHANGE, WORKER_ID.
        </p>
      </Card>
      {cfg && (
        <Card title="Active Config Snapshot" subtitle="Current values loaded in memory">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Brain</p>
              <ConfigValue label="Version"         value={cfg.version}
                tooltip="ARBX version string read from the VERSION file at startup." />
              <ConfigValue label="Trading Mode"    value={cfg.trading_mode}
                tooltip="dry_run: no real orders, all trades simulated. live: real orders sent to exchanges. paper: real market prices with simulated fills." />
              <ConfigValue label="Dry Run"         value={String(cfg.dry_run)}
                tooltip="Secondary safety switch. When true, blocks order submission even if trading_mode is live. Both must be off for real trading." />
              <ConfigValue label="Log Level"       value={cfg.log_level}
                tooltip="Minimum log severity. DEBUG logs everything including every price tick (very noisy). INFO is normal operation. WARNING only logs problems." />
              <ConfigValue label="Heartbeat TTL"   value={`${cfg.heartbeat_ttl}s`}
                tooltip="Seconds after the last heartbeat before a worker is marked dead. Default 45s = 3x the 15s heartbeat interval plus a 10s buffer." />
              <ConfigValue label="Stale Threshold" value={`${cfg.stale_threshold_s}s`}
                tooltip="Seconds without a price tick before a coverage context is flagged as stale. Stale contexts are highlighted in the Coverage Map." />
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Decision Engine</p>
              <ConfigValue label="CR Min Score"        value={cfg.decision?.cr_min_score}
                tooltip="Minimum signal score (0–1) a 9AM CR setup must reach before the engine creates an order. Score is built from BOS strength, sweep quality, FVG presence, and R:R. Higher = more selective." />
              <ConfigValue label="CR Min R:R"          value={cfg.decision?.cr_min_rr}
                tooltip="Minimum Risk/Reward ratio. e.g. 1.5 means take-profit must be 1.5x the stop-loss distance away. Setups with worse R:R are skipped entirely." />
              <ConfigValue label="Max Capital / Trade" value={`$${cfg.decision?.max_capital_per_trade}`}
                tooltip="Hard cap on USD value per trade. Applies to both simulated and live modes regardless of exchange balance." />
              <ConfigValue label="Cooldown"            value={`${cfg.decision?.cooldown_seconds}s`}
                tooltip="Minimum seconds between two orders on the same pair. Prevents stacking multiple entries on a single fast-moving signal." />
              <ConfigValue label="Max Concurrent"      value={cfg.decision?.max_concurrent_orders}
                tooltip="Maximum simultaneous open positions across all pairs. New signals are ignored once this limit is reached." />
            </div>
            <div className="mt-4">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Risk Manager</p>
              <ConfigValue label="Max Daily Loss"       value={`$${cfg.risk?.max_daily_loss_usd}`}
                tooltip="Circuit breaker: if total realised losses today exceed this USD amount, all new orders are halted. Resets at midnight UTC." />
              <ConfigValue label="Max Drawdown"         value={`${cfg.risk?.max_drawdown_pct}%`}
                tooltip="Circuit breaker: if the portfolio drops this % below its peak balance, the system halts until manually resumed via Risk & Rules." />
              <ConfigValue label="Max Consec. Losses"   value={cfg.risk?.max_consecutive_losses}
                tooltip="Circuit breaker: halts after this many consecutive losing trades. Detects strategy failure or adverse market conditions early." />
            </div>
            <div className="mt-4">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">CRT 9AM Model</p>
              <ConfigValue label="Timezone"        value={cfg.cr_9am?.timezone}
                tooltip="Timezone used to identify 1AM, 5AM, and 9AM session boundaries. All candle timestamps are converted to this timezone before range detection." />
              <ConfigValue label="Active Window"   value={`${cfg.cr_9am?.active_from}:00–${cfg.cr_9am?.active_to}:00`}
                tooltip="Local-time window when the CR plugin analyses candles and generates signals. Outside this window it is dormant unless Force Active is on." />
              <ConfigValue label="Reversal Range"  value={cfg.cr_9am?.reversal_range ?? '5am'}
                tooltip="Session candle used as the range for a NY Reversal setup. The 5AM candle (Asia session close) is the standard CRT reference. High = resistance, Low = support." />
              <ConfigValue label="Continuation"    value={cfg.cr_9am?.continuation_range ?? '1am'}
                tooltip="Session candle used for a NY Continuation setup. The 1AM candle (London open) is standard. Direction aligns with the overnight trend." />
              <ConfigValue label="TP1 %"           value={`${((cfg.cr_9am?.tp1_pct_of_range ?? 0.5) * 100).toFixed(0)}%`}
                tooltip="Take-Profit 1 is at this percentage of the range candle's size. 50% = midpoint (equilibrium). TP2 is always the full opposite side of the range." />
              <ConfigValue label="Min Score"       value={cfg.cr_9am?.min_setup_score}
                tooltip="Minimum quality score to emit a CR signal. Built from: BOS confirmation, sweep quality, FVG presence, H4 manipulation check, and range size vs ATR." />
              <ConfigValue label="Pairs"           value={cfg.cr_9am?.pairs}
                tooltip="Pairs monitored by the CR plugin. Only pairs being streamed by a live worker are relevant. Add more in config.yaml under analysis.cr_9am.pairs." />
            </div>
          </div>
        </Card>
      )}
    </div>
  )
}
