/**
 * Spatial Arbitrage Panel
 * Shows cross-exchange price spreads: same pair, different price on different exchanges.
 * Buy cheap on exchange A, sell higher on exchange B.
 * Similar to ArbiHunt app — focused on real executable opportunities.
 */
import React, { useState } from 'react'
import { usePolling } from '../utils/api'
import { Card, EmptyState, Spinner } from './ui'
import { Tip } from './Tooltip'

const fetchSpreads = () =>
  fetch('/api/market/spreads').then(r => r.json())

const fetchPrices = () =>
  fetch('/api/market/prices').then(r => r.json())

// ── Colour helpers ────────────────────────────────────────────────────────────
function spreadColor(pct) {
  if (pct >= 2.0) return 'text-green-300'
  if (pct >= 1.0) return 'text-green-400'
  if (pct >= 0.5) return 'text-yellow-400'
  return 'text-gray-400'
}

function spreadBg(pct) {
  if (pct >= 2.0) return 'border-green-700/50 bg-green-900/20'
  if (pct >= 1.0) return 'border-green-800/40 bg-green-900/10'
  if (pct >= 0.5) return 'border-yellow-800/40 bg-yellow-900/10'
  return 'border-gray-800 bg-gray-900/30'
}

// ── Spread row ────────────────────────────────────────────────────────────────
function SpreadRow({ item, allPrices }) {
  const [open, setOpen] = useState(false)

  const pair      = item.pair
  const spreadPct = item.spread_pct
  const prices    = item.prices   // { exchange: price }

  // Find buy (lowest) and sell (highest) exchange
  const entries   = Object.entries(prices).sort((a, b) => a[1] - b[1])
  const [buyEx, buyPrice]   = entries[0]   ?? ['?', 0]
  const [sellEx, sellPrice] = entries[entries.length - 1] ?? ['?', 0]

  // Estimate capital needed for $100 of profit at this spread
  // profit_pct = spread_pct, so capital = $100 / (spread_pct/100)
  const capitalFor100 = spreadPct > 0 ? Math.round(100 / (spreadPct / 100)) : '∞'

  const base = pair.split('/')[0]

  return (
    <div
      className={`border rounded-lg px-3 py-2.5 mb-1.5 cursor-pointer transition-all ${spreadBg(spreadPct)}`}
      onClick={() => setOpen(o => !o)}
    >
      <div className="flex items-center gap-3">
        {/* Spread % */}
        <span className={`text-xl font-bold font-mono w-16 shrink-0 ${spreadColor(spreadPct)}`}>
          {spreadPct.toFixed(2)}%
        </span>

        {/* Pair + exchanges */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-white">{pair}</span>
            <span className="text-[10px] text-gray-500">{Object.keys(prices).length} exchanges</span>
          </div>
          <div className="text-xs text-gray-400 mt-0.5">
            <span className="text-green-500">BUY</span>
            <span className="ml-1 text-gray-300">{buyEx}</span>
            <span className="mx-1.5 text-gray-600">→</span>
            <span className="text-red-400">SELL</span>
            <span className="ml-1 text-gray-300">{sellEx}</span>
          </div>
        </div>

        {/* Capital needed */}
        <div className="text-right shrink-0">
          <div className="text-[10px] text-gray-600">for $100 profit</div>
          <div className="text-xs text-gray-400 font-mono">${capitalFor100.toLocaleString()}</div>
        </div>

        <span className="text-gray-600 text-[10px]">{open ? '▲' : '▼'}</span>
      </div>

      {/* Expanded: all exchange prices */}
      {open && (
        <div className="mt-2 pt-2 border-t border-gray-700/40">
          <div className="grid grid-cols-2 gap-1 text-xs">
            {entries.map(([ex, price]) => (
              <div key={ex} className="flex justify-between bg-gray-900/60 rounded px-2 py-1">
                <span className="text-gray-400">{ex}</span>
                <span className={`font-mono ${ex === buyEx ? 'text-green-400' : ex === sellEx ? 'text-red-400' : 'text-gray-300'}`}>
                  {price < 0.01 ? price.toFixed(8) : price < 1 ? price.toFixed(6) : price.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-2 text-[10px] text-gray-600 text-center">
            Tap to execute — check liquidity on exchange before trading
          </div>
        </div>
      )}
    </div>
  )
}

// ── Filter bar ────────────────────────────────────────────────────────────────
const FILTERS = [
  { label: 'All',    min: 0 },
  { label: '>0.5%',  min: 0.5 },
  { label: '>1%',    min: 1.0 },
  { label: '>2%',    min: 2.0 },
]

// ── Main panel ────────────────────────────────────────────────────────────────
export default function SpatialArbPanel() {
  const [minSpread, setMinSpread] = useState(0.5)
  const [search,    setSearch]    = useState('')
  const [sortBy,    setSortBy]    = useState('spread')   // spread | pair

  const { data: spreadData, loading } = usePolling(fetchSpreads, 5000)
  const { data: priceData }           = usePolling(fetchPrices,  5000)

  if (loading) return <Card title="Spatial Arbitrage"><Spinner /></Card>

  const rawSpreads = spreadData?.spreads ?? []

  const filtered = rawSpreads
    .filter(s => s.spread_pct >= minSpread)
    .filter(s => !search || s.pair.toLowerCase().includes(search.toLowerCase()))
    .sort((a, b) => sortBy === 'spread'
      ? b.spread_pct - a.spread_pct
      : a.pair.localeCompare(b.pair)
    )

  const above1pct = rawSpreads.filter(s => s.spread_pct >= 1.0).length
  const above2pct = rawSpreads.filter(s => s.spread_pct >= 2.0).length

  return (
    <div className="space-y-3">
      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider">Pairs with spread</p>
          <p className="text-2xl font-bold text-white mt-1">{rawSpreads.length}</p>
        </div>
        <div className="bg-gray-900 border border-green-900/40 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider">&gt;1% spread</p>
          <p className="text-2xl font-bold text-green-400 mt-1">{above1pct}</p>
        </div>
        <div className="bg-gray-900 border border-green-800/60 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider">&gt;2% spread</p>
          <p className="text-2xl font-bold text-green-300 mt-1">{above2pct}</p>
        </div>
      </div>

      {/* Controls */}
      <Card>
        <div className="flex gap-2 flex-wrap items-center">
          {/* Min spread filter */}
          <div className="flex gap-1">
            {FILTERS.map(f => (
              <button key={f.label} onClick={() => setMinSpread(f.min)}
                className={`text-xs px-2.5 py-1 rounded transition-colors
                  ${minSpread === f.min
                    ? 'bg-green-700 text-white font-medium'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                {f.label}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-gray-700 mx-1" />

          {/* Sort */}
          <div className="flex gap-1">
            {[['spread', '% Spread'], ['pair', 'Pair A-Z']].map(([v, l]) => (
              <button key={v} onClick={() => setSortBy(v)}
                className={`text-xs px-2.5 py-1 rounded transition-colors
                  ${sortBy === v
                    ? 'bg-indigo-700 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                {l}
              </button>
            ))}
          </div>

          {/* Search */}
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Filter pair…"
            className="ml-auto bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-500 w-28"
          />
        </div>
      </Card>

      {/* Spread list */}
      <Card
        title="Cross-Exchange Spreads"
        subtitle={`${filtered.length} opportunities — tap any row for price breakdown`}
      >
        <div className="text-[10px] text-gray-600 mb-2 flex gap-4">
          <span className="text-green-400">●</span> ≥2% excellent
          <span className="text-yellow-400">●</span> ≥0.5% viable
          <span className="text-gray-500">●</span> &lt;0.5% marginal
        </div>

        <div className="max-h-[600px] overflow-y-auto pr-1">
          {filtered.length === 0 ? (
            <EmptyState
              icon="📊"
              message={rawSpreads.length === 0
                ? 'No cross-exchange price data yet. Workers need to stream the same pair from multiple exchanges.'
                : `No spreads above ${minSpread}% — try lowering the filter.`}
            />
          ) : (
            filtered.map(item => (
              <SpreadRow
                key={item.pair}
                item={item}
                allPrices={priceData?.prices ?? {}}
              />
            ))
          )}
        </div>
      </Card>
    </div>
  )
}
