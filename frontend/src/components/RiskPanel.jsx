import React, { useState } from 'react'
import { usePolling, fetchRiskStatus, fetchRiskConfig, fetchDecisionConfig,
         updateRiskConfig, updateDecisionConfig, resumeAfterHalt } from '../utils/api'
import { Card, Spinner } from './ui'
import { Tip, TipIcon } from './Tooltip'

function EditableField({ label, value, onSave, type = 'number', hint, tooltip }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal]         = useState(value)

  const save = async () => {
    await onSave(type === 'number' ? parseFloat(val) : val)
    setEditing(false)
  }

  return (
    <div className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0">
      <div>
        <p className="text-sm text-gray-300 flex items-center">
          {label}
          {tooltip && <TipIcon text={tooltip} pos="right" wide />}
        </p>
        {hint && <p className="text-xs text-gray-600">{hint}</p>}
      </div>
      {editing ? (
        <div className="flex items-center gap-2">
          <input
            type={type}
            value={val}
            onChange={e => setVal(e.target.value)}
            className="w-24 text-xs bg-gray-800 border border-gray-600 rounded px-2 py-1 text-gray-200"
            autoFocus
          />
          <button onClick={save} className="text-xs px-2 py-1 bg-green-700 text-white rounded">Save</button>
          <button onClick={() => { setVal(value); setEditing(false) }} className="text-xs text-gray-500">✕</button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-sm font-mono text-gray-200">{value}</span>
          <button onClick={() => setEditing(true)} className="text-xs text-gray-600 hover:text-gray-300">edit</button>
        </div>
      )}
    </div>
  )
}

export default function RiskPanel() {
  const { data: status, loading: sLoad } = usePolling(fetchRiskStatus,     5000)
  const { data: rCfg,   loading: rLoad } = usePolling(fetchRiskConfig,     15000)
  const { data: dCfg,   loading: dLoad } = usePolling(fetchDecisionConfig, 15000)
  const [resuming, setResuming]          = useState(false)

  const handleResume = async () => {
    setResuming(true)
    try { await resumeAfterHalt() } finally { setResuming(false) }
  }

  if (sLoad || rLoad || dLoad) return <Card title="Risk & Decision"><Spinner /></Card>

  return (
    <div className="space-y-4">
      {/* Halt banner */}
      {status?.halted && (
        <div className="bg-red-900/40 border border-red-600 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-red-300 font-semibold text-sm">⛔ System Halted</p>
            <p className="text-xs text-red-400 mt-0.5">{status.halt_reason}</p>
          </div>
          <button
            onClick={handleResume}
            disabled={resuming}
            className="text-xs px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded-lg disabled:opacity-50"
          >
            {resuming ? '...' : 'Resume'}
          </button>
        </div>
      )}

      {/* Live circuit breaker gauges */}
      <Card title="Circuit Breaker Status">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
          {[
            {
              label:  'Daily Loss',
              val:    `$${status?.daily_loss_usd ?? 0}`,
              limit:  `/ $${status?.max_daily_loss_usd ?? 0}`,
              pct:    status?.daily_loss_pct ?? 0,
              col:    'bg-red-500',
              tip:    'Total realised losses today. Resets at midnight UTC. When this bar is full, all new orders are halted automatically until midnight or manual resume.',
            },
            {
              label:  'Drawdown',
              val:    `${status?.drawdown_pct ?? 0}%`,
              limit:  `/ ${status?.max_drawdown_pct ?? 0}%`,
              pct:    ((status?.drawdown_pct ?? 0) / Math.max(status?.max_drawdown_pct ?? 10, 0.1)) * 100,
              col:    'bg-orange-500',
              tip:    'Portfolio drawdown from peak. Calculated as (peak_balance − current_balance) / peak_balance × 100. When full, system halts until manually resumed.',
            },
            {
              label:  'Consec. Losses',
              val:    status?.consecutive_losses ?? 0,
              limit:  `/ ${status?.max_consecutive ?? 5}`,
              pct:    ((status?.consecutive_losses ?? 0) / Math.max(status?.max_consecutive ?? 5, 1)) * 100,
              col:    'bg-yellow-500',
              tip:    'Streak of consecutive losing trades. Resets to 0 when a trade closes in profit. When full, system halts. Useful for detecting strategy breakdown quickly.',
            },
          ].map(g => (
            <div key={g.label}>
              <div className="flex justify-between text-xs mb-1">
                <span className="text-gray-400 flex items-center">
                  {g.label}
                  <TipIcon text={g.tip} pos="top" wide />
                </span>
                <span className="text-gray-300">
                  {g.val} <span className="text-gray-600">{g.limit}</span>
                </span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2">
                <div
                  className={`h-2 rounded-full ${g.col} transition-all`}
                  style={{ width: `${Math.min(g.pct, 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-600 flex items-center">
          Peak balance: ${status?.peak_balance_usd ?? 0}
          <TipIcon
            text="The highest portfolio balance recorded since startup. Used as the reference point for drawdown calculation. Resets on brain restart."
            pos="right" wide
          />
        </p>
      </Card>

      {/* Risk limits — live-editable */}
      <Card title="Risk Limits" subtitle="Changes apply immediately without restart">
        {rCfg && (
          <div>
            <EditableField
              label="Max Daily Loss (USD)"
              value={rCfg.max_daily_loss_usd}
              onSave={v => updateRiskConfig({ max_daily_loss_usd: v })}
              hint="System halts when daily losses hit this"
              tooltip="Hard stop on daily losses in USD. Once cumulative realised losses exceed this value, the system halts and will not place new orders. Resets automatically at midnight UTC."
            />
            <EditableField
              label="Max Drawdown (%)"
              value={rCfg.max_drawdown_pct}
              onSave={v => updateRiskConfig({ max_drawdown_pct: v })}
              hint="% drop from peak balance"
              tooltip="Maximum allowed drawdown as a percentage of the peak portfolio balance. e.g. 10 means the system halts if the portfolio drops 10% below its highest recorded value."
            />
            <EditableField
              label="Max Consecutive Losses"
              value={rCfg.max_consecutive_losses}
              onSave={v => updateRiskConfig({ max_consecutive_losses: v })}
              tooltip="Number of back-to-back losing trades allowed before the system halts. Helps detect when the strategy is no longer working in current market conditions. Resets on any winning trade."
            />
            <EditableField
              label="Max Pair Exposure (USD)"
              value={rCfg.max_pair_exposure_usd}
              onSave={v => updateRiskConfig({ max_pair_exposure_usd: v })}
              hint="Max open position size per pair"
              tooltip="Maximum total open position value on any single trading pair at once. Prevents over-concentration. Applies across all strategies and exchanges for that pair combined."
            />
          </div>
        )}
      </Card>

      {/* Decision engine rules — live-editable */}
      <Card title="Decision Engine Rules" subtitle="Controls when signals become orders">
        {dCfg && (
          <div>
            <EditableField
              label="CR Min Score"
              value={dCfg.cr_min_score}
              onSave={v => updateDecisionConfig({ cr_min_score: v })}
              hint="0.0 – 1.0. Signal score must exceed this"
              tooltip="The 9AM CR signal score must exceed this value for the decision engine to create an order. Score is built from BOS strength, sweep quality, FVG presence, and H4 check. Raise this to be more selective; lower it to get more (but lower quality) setups."
            />
            <EditableField
              label="CR Min Risk/Reward"
              value={dCfg.cr_min_rr}
              onSave={v => updateDecisionConfig({ cr_min_rr: v })}
              hint="e.g. 1.5 = TP must be 1.5× the SL distance"
              tooltip="Minimum acceptable Risk/Reward ratio. A value of 1.5 means the potential profit (TP1 distance) must be at least 1.5× the risk (SL distance). Setups with lower R:R are skipped, even if the signal score is high."
            />
            <EditableField
              label="Max Capital / Trade (USD)"
              value={dCfg.max_capital_per_trade}
              onSave={v => updateDecisionConfig({ max_capital_per_trade: v })}
              tooltip="Hard cap on the USD value committed to a single trade. Acts as a position size ceiling — actual size may be smaller based on exchange balance and pair liquidity."
            />
            <EditableField
              label="Max Concurrent Orders"
              value={dCfg.max_concurrent_orders}
              onSave={v => updateDecisionConfig({ max_concurrent_orders: v })}
              type="number"
              tooltip="Maximum number of open trades across all pairs at the same time. Once this limit is hit, new signals are discarded (not queued) until existing positions close."
            />
            <EditableField
              label="Cooldown (seconds)"
              value={dCfg.cooldown_seconds}
              onSave={v => updateDecisionConfig({ cooldown_seconds: v })}
              hint="Min time between orders on same pair"
              tooltip="After an order is placed on a pair, this many seconds must pass before another order on the same pair is allowed. Prevents rapid re-entry on choppy signals."
            />
            <EditableField
              label="Graph Min Profit (%)"
              value={dCfg.graph_min_profit_pct}
              onSave={v => updateDecisionConfig({ graph_min_profit_pct: v })}
              tooltip="Minimum net profit percentage required before a graph arbitrage cycle triggers an order. Net = after all fees and gas costs across all legs of the cycle."
            />
          </div>
        )}
      </Card>
    </div>
  )
}
