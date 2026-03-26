import React, { useState } from 'react'
import { useWebSocket } from '../utils/api'
import { Card, WsBadge, EmptyState } from './ui'

export default function MarketFeed() {
  const { data, status } = useWebSocket('/ws/market')
  const [sortBy, setSortBy] = useState('spread')

  const prices  = data?.prices  ?? []
  const summary = data?.summary ?? {}

  // Group by pair → compute spreads, carry timestamps
  const byPair = {}
  prices.forEach(p => {
    if (!byPair[p.pair]) byPair[p.pair] = {}
    byPair[p.pair][p.exchange] = { price: p.price, timestamp: p.timestamp }
  })

  const spreadRows = Object.entries(byPair).map(([pair, exData]) => {
    const vals   = Object.values(exData).map(d => d.price)
    const spread = vals.length > 1
      ? ((Math.max(...vals) - Math.min(...vals)) / Math.min(...vals)) * 100
      : 0
    // Most recent timestamp across exchanges for this pair
    const latestTs = Object.values(exData)
      .map(d => d.timestamp ? new Date(d.timestamp) : null)
      .filter(Boolean)
      .sort((a, b) => b - a)[0] ?? null
    return { pair, exchanges: exData, spread: round(spread, 4), priceCount: vals.length, latestTs }
  })

  const sorted = [...spreadRows].sort((a, b) =>
    sortBy === 'spread' ? b.spread - a.spread
    : a.pair.localeCompare(b.pair)
  )

  function round(n, d) { return Math.round(n * 10**d) / 10**d }

  function ageStr(ts) {
    if (!ts) return '—'
    const secs = Math.floor((Date.now() - new Date(ts)) / 1000)
    if (secs <  60) return `${secs}s ago`
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
    return `${Math.floor(secs / 3600)}h ago`
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          ['Price Contexts', summary.price_contexts ?? 0, 'text-blue-400'],
          ['Pairs Tracked',  Object.keys(byPair).length, 'text-white'],
          ['Stale Pairs',    summary.stale_pairs ?? 0,   summary.stale_pairs > 0 ? 'text-red-400' : 'text-gray-600'],
          ['Total USD',      `$${(summary.total_usd ?? 0).toLocaleString(undefined, {maximumFractionDigits: 0})}`, 'text-green-400'],
        ].map(([label, value, color]) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Spreads table */}
      <Card
        title="Live Market Feed"
        subtitle="Cross-exchange spreads from worker data"
        action={
          <div className="flex items-center gap-2">
            <WsBadge status={status} />
            <select
              value={sortBy}
              onChange={e => setSortBy(e.target.value)}
              className="text-xs bg-gray-800 border border-gray-700 rounded px-2 py-1 text-gray-300"
            >
              <option value="spread">Sort: Spread</option>
              <option value="pair">Sort: Pair</option>
            </select>
          </div>
        }
      >
        {sorted.length === 0 ? (
          <EmptyState message="Waiting for worker price data..." icon="📊" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Pair</th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Spread</th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Prices</th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2">Last seen</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row, i) => (
                  <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                    <td className="py-2.5 pr-4 font-medium text-gray-200">{row.pair}</td>
                    <td className="py-2.5 pr-4">
                      <span className={
                        row.spread > 1.0 ? 'text-green-400 font-bold' :
                        row.spread > 0.5 ? 'text-yellow-400' : 'text-gray-500'
                      }>
                        {row.spread.toFixed(4)}%
                      </span>
                    </td>
                    <td className="py-2.5 pr-4">
                      <div className="flex gap-3 flex-wrap">
                        {Object.entries(row.exchanges).map(([ex, d]) => (
                          <span key={ex} className="text-xs font-mono">
                            <span className="text-gray-500">{ex}: </span>
                            <span className="text-gray-200">
                              {d.price?.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                            </span>
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-2.5 text-xs text-gray-500 whitespace-nowrap">
                      {ageStr(row.latestTs)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
