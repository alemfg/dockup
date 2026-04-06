/**
 * Balances Panel (v6.2)
 * - Balance breakdown by exchange and asset with % allocation
 * - Target allocation editor (saved to DB)
 * - Rebalance suggestions with network routing from Vault
 * - Transfer execution with confirmation
 * - P&L summary: realized + unrealized
 */
import React, { useState } from 'react'
import {
  usePolling, fetchBalances, fetchBalanceSummary,
  fetchBalanceTargets, saveBalanceTargets,
  suggestRebalance, executeRebalance,
} from '../utils/api'
import { useSortable } from '../utils/useSortable'
import { Card, EmptyState, Spinner } from './ui'

const EXCHANGE_COLORS = {
  binance:  '#F0B90B', kraken:   '#5B4FE8', bybit:    '#F7A600',
  mexc:     '#2BB8EB', kucoin:   '#00A3B4', gateio:   '#12C4B4',
  okx:      '#000000', whitebit: '#1BA6FB', coinbase: '#0052FF',
}

function dot(exchange) {
  return EXCHANGE_COLORS[exchange] ?? '#6B7280'
}

// ── P&L Summary strip ─────────────────────────────────────────────────────────
function PnlStrip({ pnl }) {
  if (!pnl) return null
  const total = pnl.total_usd ?? 0
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
      {[
        { label: 'Realized P&L',   value: `${pnl.realized_usd >= 0 ? '+' : ''}$${(pnl.realized_usd ?? 0).toFixed(2)}`,   color: pnl.realized_usd >= 0 ? 'text-green-400' : 'text-red-400' },
        { label: 'Unrealized',     value: `${pnl.unrealized_usd >= 0 ? '+' : ''}$${(pnl.unrealized_usd ?? 0).toFixed(2)}`,color: pnl.unrealized_usd >= 0 ? 'text-green-400' : 'text-red-400' },
        { label: 'Win Rate',       value: `${pnl.win_rate ?? 0}%`,    color: 'text-blue-400' },
        { label: 'Fees Paid',      value: `$${(pnl.total_fees_usd ?? 0).toFixed(2)}`, color: 'text-yellow-400' },
      ].map(s => (
        <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-xl p-3">
          <p className="text-[10px] text-gray-500 uppercase">{s.label}</p>
          <p className={`text-lg font-bold mt-1 ${s.color}`}>{s.value}</p>
        </div>
      ))}
    </div>
  )
}

// ── Exchange allocation bar ───────────────────────────────────────────────────
function ExchangeBar({ exchange, balances, totalUsd, targetPct }) {
  const exTotal  = balances.reduce((s, b) => s + (b.usd_value || 0), 0)
  const actualPct = totalUsd > 0 ? (exTotal / totalUsd * 100) : 0
  const target    = targetPct ?? null
  const diff      = target !== null ? actualPct - target : null
  const color     = dot(exchange)

  return (
    <div className="mb-4">
      <div className="flex justify-between items-center mb-1">
        <div className="flex items-center gap-2">
          <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
          <span className="text-sm font-medium text-gray-200 capitalize">{exchange}</span>
        </div>
        <div className="flex items-center gap-3 text-xs">
          {diff !== null && (
            <span className={`font-mono ${Math.abs(diff) > 5 ? (diff > 0 ? 'text-yellow-400' : 'text-red-400') : 'text-gray-500'}`}>
              {diff > 0 ? '+' : ''}{diff.toFixed(1)}% vs target
            </span>
          )}
          <span className="text-gray-500">{actualPct.toFixed(1)}%</span>
          <span className="text-gray-200 font-semibold">
            ${exTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        </div>
      </div>
      {/* Bar: actual vs target */}
      <div className="relative w-full h-2 bg-gray-800 rounded-full">
        <div className="h-2 rounded-full transition-all"
          style={{ width: `${Math.min(actualPct, 100)}%`, backgroundColor: color, opacity: 0.8 }} />
        {target !== null && (
          <div className="absolute top-0 h-2 w-0.5 bg-white/40 rounded"
            style={{ left: `${Math.min(target, 100)}%` }} title={`Target: ${target}%`} />
        )}
      </div>
      {/* Asset breakdown */}
      <div className="flex gap-3 flex-wrap mt-1">
        {balances.map(b => (
          <span key={b.asset} className="text-xs text-gray-600">
            {b.asset}: <span className="text-gray-400">{(b.free ?? 0).toFixed(4)}</span>
            {(b.locked ?? 0) > 0 && <span className="text-gray-700"> +{b.locked.toFixed(4)} locked</span>}
          </span>
        ))}
      </div>
    </div>
  )
}

// ── Target allocation editor ──────────────────────────────────────────────────
function TargetEditor({ exchanges, onSave }) {
  const { data: savedTargets } = usePolling(fetchBalanceTargets, 30000)
  const [targets, setTargets]  = useState(null)
  const [saving, setSaving]    = useState(false)
  const [status, setStatus]    = useState(null)

  // Initialize from saved targets once loaded
  React.useEffect(() => {
    if (savedTargets?.targets && !targets) {
      setTargets(savedTargets.targets)
    } else if (!targets && exchanges.length > 0) {
      const equal = parseFloat((100 / exchanges.length).toFixed(1))
      setTargets(Object.fromEntries(exchanges.map(ex => [ex, equal])))
    }
  }, [savedTargets, exchanges])

  const total = targets ? Object.values(targets).reduce((s, v) => s + (parseFloat(v) || 0), 0) : 0

  const save = async () => {
    setSaving(true)
    try {
      await saveBalanceTargets(Object.fromEntries(
        Object.entries(targets).map(([k, v]) => [k, parseFloat(v) || 0])
      ))
      setStatus({ ok: true, msg: 'Targets saved' })
      if (onSave) onSave(targets)
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  const distribute = () => {
    const equal = parseFloat((100 / exchanges.length).toFixed(1))
    setTargets(Object.fromEntries(exchanges.map(ex => [ex, equal])))
  }

  if (!targets) return <Spinner />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">Set target % per exchange (must sum to 100%)</p>
        <button onClick={distribute} className="text-xs px-2 py-1 bg-gray-800 text-gray-400 rounded hover:bg-gray-700">
          Equal split
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2">
        {exchanges.map(ex => (
          <div key={ex} className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: dot(ex) }} />
            <span className="text-xs text-gray-300 capitalize w-20 shrink-0">{ex}</span>
            <input type="number" min="0" max="100" step="1"
              value={targets[ex] ?? ''}
              onChange={e => setTargets(t => ({ ...t, [ex]: e.target.value }))}
              className="w-16 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs font-mono text-gray-200 focus:outline-none focus:border-blue-500" />
            <span className="text-xs text-gray-600">%</span>
          </div>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <span className={`text-xs font-mono ${Math.abs(total - 100) > 1 ? 'text-red-400' : 'text-green-400'}`}>
          Total: {total.toFixed(1)}%
        </span>
        {Math.abs(total - 100) > 1 && <span className="text-xs text-red-400">Must be 100%</span>}
      </div>
      {status && (
        <p className={`text-xs ${status.ok ? 'text-green-400' : 'text-red-400'}`}>
          {status.ok ? '✓' : '✗'} {status.msg}
        </p>
      )}
      <button onClick={save} disabled={saving || Math.abs(total - 100) > 1}
        className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-40">
        {saving ? 'Saving...' : 'Save Targets'}
      </button>
    </div>
  )
}

// ── Rebalance panel ───────────────────────────────────────────────────────────
function RebalancePanel({ totalUsd, exchanges }) {
  const [suggestions, setSuggestions] = useState(null)
  const [loading,     setLoading]     = useState(false)
  const [threshold,   setThreshold]   = useState(5)
  const [coin,        setCoin]        = useState('USDT')
  const [executing,   setExecuting]   = useState({})
  const [results,     setResults]     = useState({})

  const analyse = async () => {
    setLoading(true); setSuggestions(null)
    try {
      const data = await suggestRebalance({ threshold_pct: threshold, coin })
      setSuggestions(data)
    } catch(e) { setSuggestions({ error: e.message }) }
    finally { setLoading(false) }
  }

  const execute = async (s) => {
    const key = s.exchange
    if (!confirm(
      `Transfer ${s.amount_usd.toFixed(2)} ${coin} from ${s.exchange} to ${s.transfer_to}\n` +
      `via ${s.network} | Fee: ~$${s.fee_usd?.toFixed(2) ?? '?'}\n\nThis is IRREVERSIBLE.`
    )) return

    setExecuting(e => ({ ...e, [key]: true }))
    try {
      const r = await executeRebalance({
        from_exchange: s.exchange,
        to_exchange:   s.transfer_to,
        coin,
        amount:        s.amount_usd / (totalUsd > 0 ? 1 : 1), // convert USD → coin amount
        confirm:       true,
      })
      setResults(r2 => ({ ...r2, [key]: r }))
    } catch(e) { setResults(r2 => ({ ...r2, [key]: { ok: false, message: e.message } })) }
    finally { setExecuting(e => ({ ...e, [key]: false })) }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3 flex-wrap">
        <select value={threshold} onChange={e => setThreshold(Number(e.target.value))}
          className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300">
          {[2,5,10,15,20].map(v => <option key={v} value={v}>Threshold: {v}%</option>)}
        </select>
        <select value={coin} onChange={e => setCoin(e.target.value)}
          className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-gray-300">
          {['USDT','USDC','BTC','ETH'].map(c => <option key={c}>{c}</option>)}
        </select>
        <button onClick={analyse} disabled={loading || totalUsd === 0}
          className="text-xs px-4 py-1.5 bg-indigo-700 hover:bg-indigo-600 text-white rounded-lg disabled:opacity-40">
          {loading ? '⟳ Analysing...' : '📊 Analyse Rebalance'}
        </button>
      </div>

      {suggestions?.error && (
        <p className="text-xs text-red-400">✗ {suggestions.error}</p>
      )}

      {suggestions && !suggestions.error && (
        <>
          {suggestions.suggestions.length === 0 ? (
            <div className="text-xs text-green-400 bg-green-900/20 border border-green-800 rounded-lg p-3">
              ✅ All exchanges are within the {threshold}% threshold — no rebalancing needed.
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-yellow-400">
                ⚠ Review each suggestion carefully. Transfers require API keys in Vault.
              </p>
              {suggestions.suggestions.map((s, i) => {
                const result = results[s.exchange]
                return (
                  <div key={i} className={`border rounded-xl p-4 space-y-2 ${
                    s.action === 'withdraw' ? 'border-orange-800/40 bg-orange-900/10' : 'border-blue-800/40 bg-blue-900/10'}`}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full" style={{ backgroundColor: dot(s.exchange) }} />
                        <span className="text-sm font-semibold text-gray-200 capitalize">{s.exchange}</span>
                        <span className={`text-xs px-1.5 py-0.5 rounded ${
                          s.action === 'withdraw' ? 'bg-orange-900/40 text-orange-300' : 'bg-blue-900/40 text-blue-300'}`}>
                          {s.action === 'withdraw' ? '▼ send' : '▲ receive'}
                        </span>
                      </div>
                      <span className="text-sm font-bold text-gray-200">${s.amount_usd.toLocaleString()}</span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 text-xs text-gray-500">
                      <div>Current: <span className="text-gray-300">{s.current_pct}%</span></div>
                      <div>Target:  <span className="text-gray-300">{s.target_pct}%</span></div>
                      <div>Diff:    <span className={s.diff_pct > 0 ? 'text-yellow-400' : 'text-orange-400'}>{s.diff_pct > 0 ? '+' : ''}{s.diff_pct}%</span></div>
                    </div>

                    {s.action === 'withdraw' && s.transfer_to && (
                      <div className="text-xs space-y-1">
                        <div className="flex gap-2 flex-wrap text-gray-500">
                          <span>To: <span className="text-gray-300 capitalize">{s.transfer_to}</span></span>
                          <span>Via: <span className="text-blue-400">{s.network}</span></span>
                          {s.fee_usd != null && <span>Fee: <span className="text-yellow-400">~${s.fee_usd.toFixed(2)}</span></span>}
                          {s.net_amount_usd != null && <span>Net: <span className="text-green-400">${s.net_amount_usd.toFixed(2)}</span></span>}
                        </div>
                        {s.destination && (
                          <div className="text-[10px] text-gray-700 font-mono truncate" title={s.destination}>
                            → {s.destination}
                          </div>
                        )}
                      </div>
                    )}

                    {s.action === 'withdraw' && !s.transfer_to && (
                      <p className="text-xs text-gray-600">
                        No wallet found for destination. Add one in Vault → Wallets.
                      </p>
                    )}

                    {result && (
                      <div className={`text-xs p-2 rounded ${result.ok ? 'bg-green-900/20 text-green-300' : 'bg-red-900/20 text-red-300'}`}>
                        {result.ok ? `✓ TX submitted: ${result.tx_id || 'pending'}` : `✗ ${result.message}`}
                      </div>
                    )}

                    {s.action === 'withdraw' && s.executable && !result && (
                      <button onClick={() => execute(s)} disabled={executing[s.exchange]}
                        className="text-xs px-3 py-1.5 bg-red-800 hover:bg-red-700 text-white rounded-lg disabled:opacity-50 font-semibold">
                        {executing[s.exchange] ? '⟳ Executing...' : '🚀 Execute Transfer'}
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
const SECTIONS = [
  { id: 'overview',  label: '💰 Overview' },
  { id: 'targets',   label: '🎯 Targets' },
  { id: 'rebalance', label: '⚖ Rebalance' },
]

export default function BalancesPanel() {
  const [section, setSection] = useState('overview')
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState(null)

  const { data: summary, loading: sLoad, refresh: refreshSummary } = usePolling(fetchBalanceSummary, 10000)
  const { data: balData,  loading: bLoad, refresh: refreshBal }    = usePolling(fetchBalances, 10000)
  const { data: targets }                  = usePolling(fetchBalanceTargets, 30000)

  const loading    = sLoad || bLoad
  const totalUsd   = summary?.total_usd ?? 0
  const byExchange = balData?.exchanges ?? {}
  const exchanges  = Object.keys(byExchange)
  const targetMap  = targets?.targets ?? {}

  const syncNow = async () => {
    setSyncing(true); setSyncMsg(null)
    try {
      const r = await fetch('/api/balances/sync', { method: 'POST' }).then(x => x.json())
      setSyncMsg(r.message)
      setTimeout(() => { setSyncMsg(null); refreshSummary(); refreshBal() }, 5000)
    } catch(e) { setSyncMsg(e.message) }
    finally { setSyncing(false) }
  }

  if (loading && !summary) return <Card title="Balances"><Spinner /></Card>

  return (
    <div className="space-y-3">
      {/* Tabs + total + sync */}
      <div className="flex gap-1 items-center flex-wrap">
        {SECTIONS.map(({ id, label }) => (
          <button key={id} onClick={() => setSection(id)}
            className={`text-xs px-3 py-1.5 rounded transition-colors
              ${section === id ? 'bg-indigo-700 text-white font-medium' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {label}
          </button>
        ))}
        <div className="ml-auto flex items-center gap-3">
          {syncMsg && <span className="text-[10px] text-blue-400">{syncMsg}</span>}
          <button onClick={syncNow} disabled={syncing}
            className="text-xs px-3 py-1.5 bg-blue-800/60 hover:bg-blue-700 text-blue-300 border border-blue-700/50 rounded-lg disabled:opacity-50 transition-colors">
            {syncing ? '⟳ Syncing...' : '⟳ Sync Balances'}
          </button>
          <span className="text-lg font-bold text-green-400">
            ${totalUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        </div>
      </div>

      {/* P&L strip — always visible */}
      <PnlStrip pnl={summary?.pnl} />

      {section === 'overview' && (
        <Card title="Fund Balances" subtitle="Allocation across all connected exchanges">
          {exchanges.length === 0 ? (
            <EmptyState message="No balance data yet — workers need API keys to fetch balances" icon="💰" />
          ) : (
            exchanges.map(ex => (
              <ExchangeBar
                key={ex}
                exchange={ex}
                balances={byExchange[ex] ?? []}
                totalUsd={totalUsd}
                targetPct={targetMap[ex] ?? null}
              />
            ))
          )}
          {summary?.open_positions > 0 && (
            <div className="mt-3 pt-3 border-t border-gray-800 text-xs text-gray-500">
              {summary.open_positions} open position{summary.open_positions !== 1 ? 's' : ''} —
              <span className="text-gray-300 ml-1">${summary.open_positions_value?.toLocaleString()} deployed</span>
            </div>
          )}
        </Card>
      )}

      {section === 'targets' && (
        <Card title="Target Allocation" subtitle="Saved to DB — used by Rebalance analyser">
          {exchanges.length === 0 ? (
            <EmptyState message="No exchanges with balances yet" icon="🎯" />
          ) : (
            <TargetEditor exchanges={exchanges} />
          )}
        </Card>
      )}

      {section === 'rebalance' && (
        <Card title="Rebalance" subtitle="Requires API keys and wallet addresses in Vault">
          <RebalancePanel totalUsd={totalUsd} exchanges={exchanges} />
        </Card>
      )}
    </div>
  )
}
