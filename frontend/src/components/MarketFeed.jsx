import React, { useState } from 'react'
import { useWebSocket, usePolling } from '../utils/api'
import { useSortable, SortTh } from '../utils/useSortable.jsx'
import { Card, WsBadge, EmptyState } from './ui'
import { Tip, TipIcon } from './Tooltip'

export default function MarketFeed() {
  const { data, status } = useWebSocket('/ws/market')
  const [staleThreshold, setStaleThreshold] = useState(30)
  const { data: rejData } = usePolling(() => fetch('/api/market/rejected').then(r => r.json()), 15000)
  const rejectedCount = rejData?.total_rejections ?? 0

  const prices  = data?.prices  ?? []
  const summary = data?.summary ?? {}

  // Build rows
  const byPair = {}
  prices.forEach(p => {
    if (!byPair[p.pair]) byPair[p.pair] = {}
    byPair[p.pair][p.exchange] = { price: p.price, timestamp: p.timestamp }
  })

  function round(n, d) { return Math.round(n * 10**d) / 10**d }
  function ageStr(ts) {
    if (!ts) return '—'
    const secs = Math.floor((Date.now() - new Date(ts)) / 1000)
    if (secs <  60) return `${secs}s ago`
    if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
    return `${Math.floor(secs / 3600)}h ago`
  }

  const spreadRows = Object.entries(byPair).map(([pair, exData]) => {
    const vals   = Object.values(exData).map(d => d.price)
    const spread = vals.length > 1
      ? ((Math.max(...vals) - Math.min(...vals)) / Math.min(...vals)) * 100
      : 0
    const latestTs = Object.values(exData)
      .map(d => d.timestamp ? new Date(d.timestamp) : null)
      .filter(Boolean)
      .sort((a, b) => b - a)[0] ?? null
    const lastSeenMs = latestTs ? Date.now() - new Date(latestTs) : Infinity
    const isStale = lastSeenMs / 1000 > staleThreshold
    return { pair, exchanges: exData, spread: round(spread, 4), priceCount: vals.length, latestTs, lastSeenMs, isStale }
  })

  const { sorted, col, dir, toggle } = useSortable(spreadRows, 'spread', 'desc')

  const summaryCards = [
    { label: 'Price Contexts', value: summary.price_contexts ?? 0, color: 'text-blue-400',
      tip: 'Total (exchange × pair) combinations receiving live price data.' },
    { label: 'Pairs Tracked', value: Object.keys(byPair).length, color: 'text-white',
      tip: 'Unique trading pairs across all exchanges.' },
    { label: 'Stale Pairs', value: summary.stale_pairs ?? 0,
      color: (summary.stale_pairs ?? 0) > 0 ? 'text-red-400' : 'text-gray-600',
      tip: `Pairs with no update in >${staleThreshold}s. May indicate worker disconnect or exchange issue.` },
    { label: 'Filtered', value: rejectedCount,
      color: rejectedCount > 0 ? 'text-orange-400' : 'text-gray-600',
      tip: 'Prices rejected by data quality filter (zero prices, cross-unit outliers like LBank 100-unit prices).' },
    { label: 'Total USD', value: `$${(summary.total_usd ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
      color: 'text-green-400', tip: 'Approximate total value of tracked assets at last known prices.' },
  ]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {summaryCards.map(({ label, value, color, tip }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider flex items-center">
              {label}<TipIcon text={tip} pos="bottom" wide />
            </p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <Card
        title="Live Market Feed"
        subtitle="Cross-exchange spreads — click column headers to sort"
        action={
          <div className="flex items-center gap-3 flex-wrap justify-end">
            <WsBadge status={status} />
            <Tip text="Pairs not updated within this many seconds are dimmed." pos="left">
              <div className="flex items-center gap-1.5 cursor-help">
                <span className="text-xs text-gray-500">Stale &gt;</span>
                <input type="range" min="5" max="120" step="5"
                  value={staleThreshold}
                  onChange={e => setStaleThreshold(Number(e.target.value))}
                  className="w-20 accent-green-500" />
                <span className="text-xs text-gray-400 w-8">{staleThreshold}s</span>
              </div>
            </Tip>
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
                  <SortTh col="pair"       sortCol={col} sortDir={dir} onSort={toggle}>Pair</SortTh>
                  <SortTh col="spread"     sortCol={col} sortDir={dir} onSort={toggle}>
                    <Tip text="(max−min)/min × 100. Above 1% potentially actionable after fees." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Spread</span>
                    </Tip>
                  </SortTh>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">
                    <Tip text="Last known price per exchange." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Prices</span>
                    </Tip>
                  </th>
                  <SortTh col="lastSeenMs" sortCol={col} sortDir={dir} onSort={toggle}>
                    <Tip text="Time since most recent price update." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Last seen</span>
                    </Tip>
                  </SortTh>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row, i) => (
                  <tr key={i} className={`border-b border-gray-800/40 hover:bg-gray-800/20 ${row.isStale ? 'opacity-40' : ''}`}>
                    <td className="py-2.5 pr-4 font-medium text-gray-200">{row.pair}</td>
                    <td className="py-2.5 pr-4">
                      <span className={`${
                        row.spread > 1.0 ? 'text-green-400 font-bold' :
                        row.spread > 0.5 ? 'text-yellow-400' : 'text-gray-500'
                      }`}>
                        {row.spread.toFixed(4)}%
                      </span>
                    </td>
                    <td className="py-2.5 pr-4">
                      <div className="flex gap-3 flex-wrap">
                        {Object.entries(row.exchanges).map(([ex, d]) => (
                          <span key={ex} className="text-xs font-mono">
                            <span className="text-gray-500">{ex}: </span>
                            <span className="text-gray-200">
                              {d.price?.toLocaleString(undefined, { maximumFractionDigits: 6 })}
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

