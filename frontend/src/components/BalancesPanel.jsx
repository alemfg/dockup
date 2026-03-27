import React, { useState } from 'react'
import { usePolling, fetchBalances, suggestRebalance } from '../utils/api'
import { Card, EmptyState, Spinner } from './ui'

const EXCHANGE_COLORS = {
  binance:  'bg-yellow-500',
  kraken:   'bg-blue-500',
  coinbase: 'bg-blue-400',
  bybit:    'bg-orange-500',
}

function RebalancePanel({ totalUsd }) {
  const [suggestions, setSuggestions] = useState(null)
  const [loading, setLoading]         = useState(false)
  const [threshold, setThreshold]     = useState(5)
  const [error, setError]             = useState(null)

  const fetchSuggestions = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await suggestRebalance(threshold)
      setSuggestions(data)
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="mt-4 border-t border-gray-800 pt-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-gray-300">Rebalance Suggestions</p>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">Threshold:</label>
          <select
            value={threshold}
            onChange={e => setThreshold(Number(e.target.value))}
            className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300"
          >
            {[2, 5, 10, 15, 20].map(v => (
              <option key={v} value={v}>{v}%</option>
            ))}
          </select>
          <button
            onClick={fetchSuggestions}
            disabled={loading || totalUsd === 0}
            className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-200 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-40"
          >
            {loading ? '...' : 'Analyse'}
          </button>
        </div>
      </div>

      {error && <p className="text-xs text-red-400 mb-2">{error}</p>}

      {suggestions && suggestions.suggestions.length === 0 && (
        <p className="text-xs text-green-400 bg-green-900/20 border border-green-800 rounded-lg p-3">
          ✅ Balances are within the {threshold}% threshold — no rebalancing needed.
        </p>
      )}

      {suggestions && suggestions.suggestions.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs text-yellow-400 mb-2">
            ⚠️ Suggestions only — no transfers will happen without your approval.
          </p>
          {suggestions.suggestions.map((s, i) => (
            <div key={i} className="bg-gray-800/60 border border-gray-700 rounded-lg p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium text-gray-200 capitalize">{s.exchange}</span>
                <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${
                  s.action === 'deposit' ? 'bg-green-900/40 text-green-300' : 'bg-orange-900/40 text-orange-300'
                }`}>
                  {s.action === 'deposit' ? '▲ Add funds' : '▼ Withdraw funds'}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-gray-400">
                <div>
                  <p className="text-gray-600">Current</p>
                  <p className="text-gray-200">{s.current_pct}% (${s.current_usd.toLocaleString()})</p>
                </div>
                <div>
                  <p className="text-gray-600">Target</p>
                  <p className="text-gray-200">{s.target_pct}%</p>
                </div>
                <div>
                  <p className="text-gray-600">Amount</p>
                  <p className="text-white font-semibold">${s.amount_usd.toLocaleString()}</p>
                </div>
              </div>
              <p className="text-xs text-gray-600 mt-2 italic">
                Manual transfer required — automatic execution not available in v3.2
              </p>
            </div>
          ))}
        </div>
      )}

      {!suggestions && !loading && (
        <p className="text-xs text-gray-600">
          Click Analyse to compute equal-distribution suggestions based on current balances.
        </p>
      )}
    </div>
  )
}

export default function BalancesPanel() {
  const { data, loading } = usePolling(fetchBalances, 10000)
  if (loading) return <Card title="Balances"><Spinner /></Card>

  const totalUsd   = data?.total_usd ?? 0
  const byExchange = data?.exchanges ?? {}

  return (
    <Card
      title="Fund Balances"
      subtitle="Across all connected exchanges"
      action={
        <span className="text-lg font-bold text-green-400">
          ${totalUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
        </span>
      }
    >
      {Object.keys(byExchange).length === 0 ? (
        <EmptyState message="No balance data yet — workers not reporting balances" icon="💰" />
      ) : (
        Object.entries(byExchange).map(([exchange, balances]) => {
          const exTotal = balances.reduce((s, b) => s + (b.usd_value || 0), 0)
          const pct     = totalUsd > 0 ? (exTotal / totalUsd * 100) : 0
          const color   = EXCHANGE_COLORS[exchange] || 'bg-gray-500'
          const lastSeen = balances[0]?.timestamp
            ? new Date(balances[0].timestamp).toLocaleTimeString()
            : null

          return (
            <div key={exchange} className="mb-4">
              <div className="flex justify-between items-center mb-1.5">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${color}`} />
                  <span className="text-sm font-medium text-gray-200 capitalize">{exchange}</span>
                  {lastSeen && <span className="text-xs text-gray-600">· {lastSeen}</span>}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">{pct.toFixed(1)}%</span>
                  <span className="text-sm font-semibold text-gray-200">
                    ${exTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                </div>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 mb-1.5">
                <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>
              <div className="flex gap-3 flex-wrap">
                {balances.map(b => (
                  <span key={b.asset} className="text-xs text-gray-500">
                    {b.asset}: <span className="text-gray-300">{b.free?.toFixed(4)}</span>
                    {b.locked > 0 && <span className="text-gray-600"> (+{b.locked?.toFixed(4)} locked)</span>}
                  </span>
                ))}
              </div>
            </div>
          )
        })
      )}
      <RebalancePanel totalUsd={totalUsd} />
    </Card>
  )
}
