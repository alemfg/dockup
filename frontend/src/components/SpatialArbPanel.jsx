/**
 * Spatial Arbitrage Panel (v6.4)
 * Shows cross-exchange price spreads with fee-adjusted net profit.
 * v6.4: Diagnostic empty state, per-exchange rate-limit throttle control.
 */
import React, { useState } from 'react'
import { usePolling } from '../utils/api'
import { Card, EmptyState, Spinner } from './ui'

const fetchSpreads    = () => fetch('/api/market/spreads').then(r => r.json())
const fetchRateLimits = () => fetch('/api/workers/rate-limits').then(r => r.json())

function spreadColor(pct) {
  if (pct >= 2.0) return 'text-green-300'
  if (pct >= 1.0) return 'text-green-400'
  if (pct >= 0.5) return 'text-yellow-400'
  return 'text-gray-400'
}

function netColor(pct) {
  if (pct > 0) return 'text-green-400'
  if (pct < 0) return 'text-red-400'
  return 'text-gray-500'
}

function spreadBg(pct) {
  if (pct >= 2.0) return 'border-green-700/50 bg-green-900/20'
  if (pct >= 1.0) return 'border-green-800/40 bg-green-900/10'
  if (pct >= 0.5) return 'border-yellow-800/40 bg-yellow-900/10'
  return 'border-gray-800 bg-gray-900/30'
}

function rlStatusColor(status) {
  if (status === 'throttled')  return 'text-red-400'
  if (status === 'recovering') return 'text-yellow-400'
  if (status === 'warning')    return 'text-yellow-500'
  return 'text-green-400'
}

function SpreadRow({ item }) {
  const [open, setOpen] = useState(false)

  const pair       = item.pair
  const spreadPct  = item.spread_pct ?? 0
  const netPct     = item.net_pct    ?? spreadPct
  const feePct     = item.fee_pct    ?? 0
  const buyEx      = item.buy_ex     ?? '?'
  const sellEx     = item.sell_ex    ?? '?'
  const buyPrice   = item.buy_price  ?? 0
  const sellPrice  = item.sell_price ?? 0
  const prices     = item.prices     ?? {}
  const profitable = item.profitable ?? netPct > 0

  const capitalFor100 = netPct > 0.001 ? Math.round(100 / (netPct / 100)) : null
  const entries = Object.entries(prices).sort((a, b) => a[1] - b[1])

  return (
    <div
      className={`border rounded-lg px-3 py-2.5 mb-1.5 cursor-pointer transition-all ${spreadBg(spreadPct)}`}
      onClick={() => setOpen(o => !o)}
    >
      <div className="flex items-center gap-3">
        {/* Spread column */}
        <div className="shrink-0 w-20">
          <div className={`text-lg font-bold font-mono leading-tight ${spreadColor(spreadPct)}`}>
            {spreadPct.toFixed(2)}%
          </div>
          <div className={`text-[10px] font-mono ${netColor(netPct)}`}>
            net {netPct.toFixed(2)}%
          </div>
        </div>

        {/* Pair + route */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-white">{pair}</span>
            <span className="text-[10px] text-gray-600">{Object.keys(prices).length} exchanges</span>
            {profitable && (
              <span className="text-[9px] px-1.5 py-0.5 bg-green-900/40 border border-green-800/50 text-green-400 rounded">
                profitable
              </span>
            )}
          </div>
          <div className="text-xs text-gray-400 mt-0.5 flex items-center gap-1">
            <span className="text-green-500 font-semibold">BUY</span>
            <span className="text-gray-300">{buyEx}</span>
            <span className="text-gray-600">@{buyPrice > 0 ? buyPrice.toFixed(4) : '?'}</span>
            <span className="text-gray-600 mx-0.5">→</span>
            <span className="text-red-400 font-semibold">SELL</span>
            <span className="text-gray-300">{sellEx}</span>
            <span className="text-gray-600">@{sellPrice > 0 ? sellPrice.toFixed(4) : '?'}</span>
          </div>
        </div>

        {/* Capital needed */}
        <div className="text-right shrink-0">
          {capitalFor100 ? (
            <>
              <div className="text-[10px] text-gray-600">for $100 profit</div>
              <div className="text-xs text-gray-400 font-mono">${capitalFor100.toLocaleString()}</div>
            </>
          ) : (
            <div className="text-[10px] text-red-400">unprofitable after fees</div>
          )}
          {feePct > 0 && (
            <div className="text-[9px] text-gray-600 font-mono">fee {feePct.toFixed(2)}%</div>
          )}
        </div>

        <span className="text-gray-600 text-[10px] shrink-0">{open ? '▲' : '▼'}</span>
      </div>

      {/* Expanded: all exchange prices */}
      {open && (
        <div className="mt-2 pt-2 border-t border-gray-700/40">
          <div className="grid grid-cols-2 gap-1 text-xs">
            {entries.map(([ex, price]) => (
              <div key={ex} className="flex justify-between bg-gray-900/60 rounded px-2 py-1">
                <span className={`capitalize ${ex === buyEx ? 'text-green-400 font-semibold' : ex === sellEx ? 'text-red-400 font-semibold' : 'text-gray-400'}`}>
                  {ex === buyEx ? '↑ ' : ex === sellEx ? '↓ ' : ''}{ex}
                </span>
                <span className={`font-mono ${ex === buyEx ? 'text-green-400' : ex === sellEx ? 'text-red-400' : 'text-gray-300'}`}>
                  {price < 0.01 ? price.toFixed(8) : price < 1 ? price.toFixed(6) : price.toFixed(4)}
                </span>
              </div>
            ))}
          </div>
          <div className="mt-2 text-[10px] text-gray-600 text-center">
            Net profit accounts for taker fees · Verify liquidity before trading
          </div>
        </div>
      )}
    </div>
  )
}

const FILTERS = [
  { label: 'All',   min: 0   },
  { label: '>0.5%', min: 0.5 },
  { label: '>1%',   min: 1.0 },
  { label: '>2%',   min: 2.0 },
]

// ── Rate limit panel ─────────────────────────────────────────────────────────

function RateLimitPanel({ rlData }) {
  const [throttleMs, setThrottleMs] = useState(4000)
  const [throttling, setThrottling] = useState(false)

  if (!rlData?.exchanges?.length) return null

  const handleThrottle = async (exchange) => {
    setThrottling(true)
    try {
      await fetch('/api/workers/throttle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exchange, interval_ms: throttleMs }),
      })
    } finally {
      setThrottling(false)
    }
  }

  const hasIssues = rlData.exchanges.some(e => e.status !== 'ok')

  return (
    <Card
      title="Rate Limit Monitor"
      subtitle={`${rlData.total_429s} total 429s across all exchanges`}
    >
      <div className="space-y-2">
        {rlData.exchanges.map(ex => (
          <div key={ex.exchange} className="flex items-center gap-3 bg-gray-900/50 rounded-lg px-3 py-2">
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-sm font-semibold text-white capitalize">{ex.exchange}</span>
                <span className={`text-[10px] font-semibold uppercase ${rlStatusColor(ex.status)}`}>
                  {ex.status}
                </span>
                {ex.max_backoff_s > 0 && (
                  <span className="text-[10px] text-red-400 font-mono">
                    back-off {ex.max_backoff_s.toFixed(0)}s
                  </span>
                )}
              </div>
              <div className="flex gap-3 text-[10px] text-gray-500 mt-0.5 font-mono">
                <span>{ex.rpm_limit} rpm limit</span>
                <span>{ex.workers} worker{ex.workers !== 1 ? 's' : ''}</span>
                <span>{ex.total_requests.toLocaleString()} reqs</span>
                {ex.total_throttled > 0 && (
                  <span className="text-yellow-600">{ex.total_throttled} throttled</span>
                )}
                {ex.total_429s > 0 && (
                  <span className="text-red-500">{ex.total_429s} × 429</span>
                )}
              </div>
            </div>
            {ex.status !== 'ok' && (
              <button
                onClick={() => handleThrottle(ex.exchange)}
                disabled={throttling}
                className="text-[10px] px-2 py-1 bg-yellow-900/40 border border-yellow-700/50 text-yellow-400 rounded hover:bg-yellow-900/60 transition-colors disabled:opacity-50"
              >
                Slow to {throttleMs}ms
              </button>
            )}
          </div>
        ))}

        {hasIssues && (
          <div className="flex items-center gap-2 pt-1">
            <span className="text-[10px] text-gray-500">Throttle interval:</span>
            {[2000, 4000, 6000, 10000].map(ms => (
              <button key={ms}
                onClick={() => setThrottleMs(ms)}
                className={`text-[10px] px-2 py-0.5 rounded transition-colors
                  ${throttleMs === ms ? 'bg-indigo-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                {ms / 1000}s
              </button>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}

// ── Diagnostic empty state ────────────────────────────────────────────────────

function DiagEmptyState({ diag }) {
  if (!diag) {
    return (
      <EmptyState icon="📊" message="No market data yet. Are workers running?" />
    )
  }

  const { active_exchanges, total_pairs, pairs_single_exchange, single_exchange_examples } = diag

  if (active_exchanges.length === 0) {
    return (
      <EmptyState
        icon="⚠️"
        message="No workers streaming data. Add at least 2 exchanges in EXCHANGES= config (e.g. EXCHANGES=binance,kraken)."
      />
    )
  }

  if (active_exchanges.length === 1) {
    return (
      <div className="rounded-lg border border-yellow-800/40 bg-yellow-900/10 p-4 text-sm text-yellow-300 space-y-2">
        <div className="font-semibold">Only 1 exchange active: <span className="capitalize">{active_exchanges[0]}</span></div>
        <div className="text-yellow-500 text-xs">
          Spatial arbitrage requires prices from 2+ exchanges for the same pair.
          Add a second exchange to <code className="bg-black/30 px-1 rounded">EXCHANGES=</code> in your .env.
        </div>
        <div className="text-xs text-gray-400">
          {total_pairs} pair{total_pairs !== 1 ? 's' : ''} tracked — all on a single exchange.
        </div>
      </div>
    )
  }

  // Multiple exchanges but no overlap
  return (
    <div className="rounded-lg border border-blue-800/40 bg-blue-900/10 p-4 text-sm text-blue-300 space-y-2">
      <div className="font-semibold">
        {active_exchanges.length} exchanges active — no overlapping pairs yet
      </div>
      <div className="text-blue-400 text-xs">
        Exchanges: <span className="capitalize">{active_exchanges.join(', ')}</span>
      </div>
      <div className="text-xs text-gray-400">
        {pairs_single_exchange} pair{pairs_single_exchange !== 1 ? 's' : ''} tracked across all exchanges,
        but none appear on 2+ exchanges simultaneously.
        Workers may still be warming up, or the exchanges track different pairs.
      </div>
      {single_exchange_examples?.length > 0 && (
        <div className="text-xs text-gray-500">
          Example single-exchange pairs: {single_exchange_examples.map(p =>
            `${p.pair} (${p.exchanges[0]})`
          ).join(', ')}
        </div>
      )}
      <div className="text-[10px] text-gray-600 pt-1">
        Tip: Set <code className="bg-black/30 px-1 rounded">BINANCE_PAIRS=BTC/USDT,ETH/USDT</code> and the same pairs on your second exchange.
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const SORT_SPREAD = 'spread'
const SORT_PAIR   = 'pair'

export default function SpatialArbPanel() {
  const [minSpread, setMinSpread] = useState(0.5)
  const [search,    setSearch]    = useState('')
  const [sortBy,    setSortBy]    = useState(SORT_SPREAD)
  const [profOnly,  setProfOnly]  = useState(false)
  const [showRL,    setShowRL]    = useState(false)

  const { data: spreadData, loading }   = usePolling(fetchSpreads, 5000)
  const { data: rlData }                = usePolling(fetchRateLimits, 10000)

  if (loading) return <Card title="Spatial Arbitrage"><Spinner /></Card>

  const rawSpreads = spreadData?.spreads ?? []
  const diag       = spreadData?.diag    ?? null

  const filtered = rawSpreads
    .filter(s => s.spread_pct >= minSpread)
    .filter(s => !search || s.pair.toLowerCase().includes(search.toLowerCase()))
    .filter(s => !profOnly || (s.profitable ?? false))
    .sort((a, b) => sortBy === SORT_SPREAD
      ? b.spread_pct - a.spread_pct
      : a.pair.localeCompare(b.pair))

  const profitable = rawSpreads.filter(s => s.profitable).length
  const above1pct  = rawSpreads.filter(s => s.spread_pct >= 1.0).length
  const above2pct  = rawSpreads.filter(s => s.spread_pct >= 2.0).length
  const has429s    = (rlData?.total_429s ?? 0) > 0

  return (
    <div className="space-y-3">
      {/* Summary */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">Pairs tracked</p>
          <p className="text-2xl font-bold text-white mt-1">{rawSpreads.length}</p>
        </div>
        <div className="bg-gray-900 border border-green-900/30 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">Profitable (net)</p>
          <p className="text-2xl font-bold text-green-400 mt-1">{profitable}</p>
        </div>
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">&gt;1% gross</p>
          <p className="text-2xl font-bold text-green-400 mt-1">{above1pct}</p>
        </div>
        <div
          className={`bg-gray-900 rounded-xl p-4 cursor-pointer transition-colors border
            ${has429s ? 'border-red-800/60 hover:border-red-700' : 'border-gray-800'}`}
          onClick={() => setShowRL(r => !r)}
          title="Click to toggle rate limit monitor"
        >
          <p className="text-xs text-gray-500 uppercase">&gt;2% gross</p>
          <div className="flex items-end justify-between mt-1">
            <p className="text-2xl font-bold text-green-300">{above2pct}</p>
            {has429s && (
              <span className="text-[10px] text-red-400 font-semibold mb-0.5">
                {rlData.total_429s} 429s
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Rate limit monitor — shown when there are 429s or toggled */}
      {(showRL || has429s) && rlData && (
        <RateLimitPanel rlData={rlData} />
      )}

      {/* Controls */}
      <Card>
        <div className="flex gap-2 flex-wrap items-center">
          <div className="flex gap-1">
            {FILTERS.map(f => (
              <button key={f.label} onClick={() => setMinSpread(f.min)}
                className={`text-xs px-2.5 py-1 rounded transition-colors
                  ${minSpread === f.min ? 'bg-green-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="w-px h-5 bg-gray-700 mx-1" />
          <label className="flex items-center gap-1.5 text-xs text-gray-400 cursor-pointer">
            <input type="checkbox" checked={profOnly} onChange={e => setProfOnly(e.target.checked)} />
            Profitable only
          </label>
          <div className="w-px h-5 bg-gray-700 mx-1" />
          {[[SORT_SPREAD,'% Spread'],[SORT_PAIR,'Pair A-Z']].map(([v,l]) => (
            <button key={v} onClick={() => setSortBy(v)}
              className={`text-xs px-2.5 py-1 rounded transition-colors
                ${sortBy === v ? 'bg-indigo-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
              {l}
            </button>
          ))}
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Filter pair…"
            className="ml-auto bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 focus:outline-none focus:border-gray-500 w-28" />
        </div>
      </Card>

      {/* Spread list */}
      <Card
        title="Cross-Exchange Spreads"
        subtitle={`${filtered.length} shown — gross spread | net after taker fees | tap for price breakdown`}
      >
        <div className="flex gap-4 text-[10px] text-gray-600 mb-2">
          <span><span className="text-green-400">●</span> ≥2% excellent</span>
          <span><span className="text-yellow-400">●</span> ≥0.5% viable</span>
          <span><span className="text-gray-500">●</span> low spread</span>
          <span className="ml-auto text-gray-700">Fees from Vault → Taker Fees</span>
        </div>
        <div className="max-h-[600px] overflow-y-auto pr-1">
          {rawSpreads.length === 0 ? (
            <DiagEmptyState diag={diag} />
          ) : filtered.length === 0 ? (
            <EmptyState icon="📊" message={`No spreads above ${minSpread}% — try lowering the filter.`} />
          ) : (
            filtered.map(item => <SpreadRow key={item.pair} item={item} />)
          )}
        </div>
      </Card>
    </div>
  )
}

