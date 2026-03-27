import React, { useState } from 'react'
import { useWebSocket } from '../utils/api'
import { Card, WsBadge, EmptyState } from './ui'
import { Tip, TipIcon } from './Tooltip'

export default function MarketFeed() {
  const { data, status } = useWebSocket('/ws/market')
  const [sortBy, setSortBy]                   = useState('spread')
  const [staleThreshold, setStaleThreshold]   = useState(30)

  const prices  = data?.prices  ?? []
  const summary = data?.summary ?? {}

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
    const latestTs = Object.values(exData)
      .map(d => d.timestamp ? new Date(d.timestamp) : null)
      .filter(Boolean)
      .sort((a, b) => b - a)[0] ?? null
    const isStale = latestTs ? (Date.now() - new Date(latestTs)) / 1000 > staleThreshold : false
    return { pair, exchanges: exData, spread: round(spread, 4), priceCount: vals.length, latestTs, isStale }
  })

  const sorted = [...spreadRows].sort((a, b) =>
    sortBy === 'spread' ? b.spread - a.spread : a.pair.localeCompare(b.pair)
  )

  function round(n, d) { return Math.round(n * 10**d) / 10**d }
  function ageStr(ts) {
    if (!ts) return '—'
    const secs = Math.floor((Date.now() - new Date(ts)) / 1000)
    if (secs <  60) return `${secs}s ago`
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
    return `${Math.floor(secs / 3600)}h ago`
  }

  const summaryCards = [
    {
      label: 'Price Contexts',
      value: summary.price_contexts ?? 0,
      color: 'text-blue-400',
      tip: 'Total number of (exchange × pair) combinations currently receiving live price data from workers. One context per worker stream.',
    },
    {
      label: 'Pairs Tracked',
      value: Object.keys(byPair).length,
      color: 'text-white',
      tip: 'Unique trading pairs visible across all connected exchanges. The same pair on two exchanges counts as one pair here.',
    },
    {
      label: 'Stale Pairs',
      value: summary.stale_pairs ?? 0,
      color: (summary.stale_pairs ?? 0) > 0 ? 'text-red-400' : 'text-gray-600',
      tip: `Pairs that haven't received a price update in more than the stale threshold (currently ${staleThreshold}s). These may indicate a worker disconnect or exchange issue.`,
    },
    {
      label: 'Total USD',
      value: `$${(summary.total_usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      color: 'text-green-400',
      tip: 'Approximate total value of all tracked assets at last known prices. Useful for a quick snapshot of coverage scope.',
    },
  ]

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {summaryCards.map(({ label, value, color, tip }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider flex items-center">
              {label}
              <TipIcon text={tip} pos="bottom" wide />
            </p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Spreads table */}
      <Card
        title="Live Market Feed"
        subtitle="Cross-exchange spreads from worker data"
        action={
          <div className="flex items-center gap-3 flex-wrap justify-end">
            <WsBadge status={status} />
            <Tip text="Pairs that haven't updated within this many seconds are dimmed in the table below. Use the slider to adjust the threshold." pos="left">
              <div className="flex items-center gap-1.5 cursor-help">
                <span className="text-xs text-gray-500">Stale &gt;</span>
                <input
                  type="range" min="5" max="120" step="5"
                  value={staleThreshold}
                  onChange={e => setStaleThreshold(Number(e.target.value))}
                  className="w-20 accent-green-500"
                />
                <span className="text-xs text-gray-400 w-8">{staleThreshold}s</span>
              </div>
            </Tip>
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
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">
                    <Tip text="Cross-exchange spread: (max_price - min_price) / min_price × 100. Values above 1% are potentially actionable arbitrage opportunities after fees." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Spread</span>
                    </Tip>
                  </th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">
                    <Tip text="Last known price per exchange. Format: exchange_name: price. Multiple exchanges indicate cross-exchange arbitrage potential." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Prices</span>
                    </Tip>
                  </th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2">
                    <Tip text="Time since the most recent price update across all exchanges for this pair. Rows dimmed when beyond the stale threshold." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Last seen</span>
                    </Tip>
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row, i) => (
                  <tr key={i} className={`border-b border-gray-800/40 hover:bg-gray-800/20 ${row.isStale ? 'opacity-40' : ''}`}>
                    <td className="py-2.5 pr-4 font-medium text-gray-200">{row.pair}</td>
                    <td className="py-2.5 pr-4">
                      <Tip text={
                        row.spread > 1.0
                          ? `${row.spread.toFixed(4)}% spread — potentially profitable after fees (~0.1–0.3% per leg). Verify liquidity before acting.`
                          : row.spread > 0.5
                          ? `${row.spread.toFixed(4)}% spread — marginal. May cover fees on high-volume pairs with low slippage.`
                          : `${row.spread.toFixed(4)}% spread — below typical fee cost. Not actionable.`
                      } pos="right">
                        <span className={`cursor-help ${
                          row.spread > 1.0 ? 'text-green-400 font-bold' :
                          row.spread > 0.5 ? 'text-yellow-400' : 'text-gray-500'
                        }`}>
                          {row.spread.toFixed(4)}%
                        </span>
                      </Tip>
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
