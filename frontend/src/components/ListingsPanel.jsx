/**
 * Listings Panel (v6.8)
 * Tracks new exchange listings for cross-exchange premium arbitrage.
 * - Manual watchlist management
 * - CoinGecko auto-discovery of new coins
 * - Live premium detection from MarketState prices
 * - Alert history
 */
import React, { useState } from 'react'
import { usePolling, fetchListingsWatchlist, fetchListingsNew, fetchListingsOpportunities, fetchListingsStatus } from '../utils/api'
import { Card, EmptyState, Spinner } from './ui'

const api = (path, opts = {}) => fetch('/api' + path, opts).then(r => r.json())

function spreadColor(pct) {
  if (pct >= 20) return 'text-green-300 font-bold'
  if (pct >= 10) return 'text-green-400 font-semibold'
  if (pct >= 5)  return 'text-yellow-400'
  return 'text-gray-400'
}

// ── Opportunity row ───────────────────────────────────────────────────────────
function OppRow({ opp }) {
  const age = opp.listing_age_hours
  return (
    <tr className="border-b border-gray-800/40 hover:bg-gray-800/20">
      <td className="py-2 px-3">
        <div className="flex items-center gap-2">
          <span className="font-bold text-white">{opp.symbol}</span>
          {opp.source === 'coingecko_auto' && (
            <span className="text-[9px] px-1.5 py-0.5 bg-blue-900/30 border border-blue-800/50 text-blue-400 rounded">CG</span>
          )}
        </div>
        <div className="text-[10px] text-gray-600 truncate max-w-[120px]">{opp.name}</div>
      </td>
      <td className={`py-2 px-3 font-mono text-lg ${spreadColor(opp.spread_pct)}`}>
        {opp.spread_pct.toFixed(1)}%
      </td>
      <td className="py-2 px-3 text-xs">
        <div className="text-green-500 font-semibold">BUY {opp.base_ex}</div>
        <div className="text-gray-500 font-mono text-[10px]">@ {opp.base_price?.toLocaleString(undefined, {maximumFractionDigits: 8})}</div>
      </td>
      <td className="py-2 px-3 text-xs">
        <div className="text-red-400 font-semibold">SELL {opp.premium_ex}</div>
        <div className="text-gray-500 font-mono text-[10px]">@ {opp.premium_price?.toLocaleString(undefined, {maximumFractionDigits: 8})}</div>
      </td>
      <td className="py-2 px-3 text-xs text-gray-500">
        {age != null ? `${age.toFixed(0)}h ago` : '—'}
      </td>
      <td className="py-2 px-3 text-xs text-gray-500 font-mono">
        {opp.capital_for_100_profit ? `$${opp.capital_for_100_profit.toLocaleString()}` : '—'}
      </td>
      <td className="py-2 px-3 text-[10px] text-gray-600">
        {new Date(opp.detected_at).toLocaleTimeString()}
      </td>
    </tr>
  )
}

// ── Watchlist section ─────────────────────────────────────────────────────────
function WatchlistSection() {
  const { data, loading, refresh } = usePolling(fetchListingsWatchlist, 10000)
  const watchlist = data?.watchlist ?? []
  const [form, setForm] = useState({
    symbol: '', name: '', reference_exchange: 'binance',
    notes: '', listing_date: '',
  })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)
  const [showAdd, setShowAdd] = useState(false)

  const add = async () => {
    if (!form.symbol) { setStatus({ ok: false, msg: 'Symbol required' }); return }
    setSaving(true); setStatus(null)
    try {
      const r = await api('/listings/watchlist', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, symbol: form.symbol.toUpperCase() }),
      })
      if (r.ok) {
        setStatus({ ok: true, msg: `Added ${form.symbol.toUpperCase()} to watchlist` })
        setForm({ symbol: '', name: '', reference_exchange: 'binance', notes: '', listing_date: '' })
        setShowAdd(false); refresh()
      } else { setStatus({ ok: false, msg: r.detail ?? 'Failed' }) }
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  const remove = async (symbol) => {
    if (!confirm(`Remove ${symbol} from watchlist?`)) return
    await api(`/listings/watchlist/${symbol}`, { method: 'DELETE' })
    refresh()
  }

  return (
    <div className="space-y-3">
      {loading ? <Spinner /> : watchlist.length === 0 ? (
        <div className="text-center py-6 text-gray-600 text-sm">
          No tokens on watchlist. Add tokens you expect to list on major exchanges.
          <div className="text-xs text-gray-700 mt-1">CoinGecko tokens seen on active workers are auto-added.</div>
        </div>
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                {['Symbol','Name','Ref Exchange','Source','Listing Date','Notes',''].map(h => (
                  <th key={h} className="text-left py-2 px-3 text-gray-500 uppercase text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {watchlist.map(w => (
                <tr key={w.symbol} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-2 px-3 font-bold text-white">{w.symbol}</td>
                  <td className="py-2 px-3 text-gray-300">{w.name || '—'}</td>
                  <td className="py-2 px-3 text-gray-500 capitalize">{w.reference_exchange}</td>
                  <td className="py-2 px-3">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded border ${
                      w.source === 'coingecko_auto'
                        ? 'bg-blue-900/30 border-blue-800/50 text-blue-400'
                        : 'bg-gray-800 border-gray-700 text-gray-500'}`}>
                      {w.source === 'coingecko_auto' ? 'CoinGecko' : 'manual'}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-gray-600 font-mono text-[10px]">
                    {w.listing_date ? w.listing_date.slice(0, 10) : '—'}
                  </td>
                  <td className="py-2 px-3 text-gray-600 text-[10px] max-w-[160px] truncate" title={w.notes}>
                    {w.notes || '—'}
                  </td>
                  <td className="py-2 px-3">
                    <button onClick={() => remove(w.symbol)}
                      className="text-[10px] px-2 py-0.5 bg-red-900/30 text-red-400 rounded hover:bg-red-900/50">✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button onClick={() => setShowAdd(s => !s)}
        className="text-xs px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded-lg">
        {showAdd ? '▲ Hide' : '+ Add to Watchlist'}
      </button>

      {showAdd && (
        <div className="border border-gray-800 rounded-xl p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-300">Track a token for listing premium arb</p>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: 'Symbol (e.g. WIF)', key: 'symbol', placeholder: 'WIF' },
              { label: 'Name', key: 'name', placeholder: 'dogwifhat' },
              { label: 'Reference exchange', key: 'reference_exchange', placeholder: 'binance' },
              { label: 'Listing date (optional)', key: 'listing_date', placeholder: '2024-01-15', type: 'date' },
            ].map(f => (
              <div key={f.key} className="flex flex-col gap-1">
                <label className="text-[10px] text-gray-500 uppercase">{f.label}</label>
                <input type={f.type || 'text'} value={form[f.key]}
                  onChange={e => setForm(p => ({ ...p, [f.key]: e.target.value }))}
                  placeholder={f.placeholder}
                  className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500" />
              </div>
            ))}
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-500 uppercase">Notes</label>
            <input value={form.notes} onChange={e => setForm(p => ({ ...p, notes: e.target.value }))}
              placeholder="e.g. Binance listing announced 2024-01-10"
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500" />
          </div>
          {status && (
            <div className={`text-xs px-3 py-2 rounded border ${
              status.ok ? 'bg-green-900/20 border-green-800 text-green-300' : 'bg-red-900/20 border-red-800 text-red-300'}`}>
              {status.ok ? '✓' : '✗'} {status.msg}
            </div>
          )}
          <button onClick={add} disabled={saving}
            className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Adding...' : 'Add to Watchlist'}
          </button>
          <p className="text-[10px] text-gray-600">
            Tip: Buy the token on Gate.io/MEXC, transfer to Binance BEFORE the listing, then sell when the Binance premium appears.
          </p>
        </div>
      )}
    </div>
  )
}

// ── CoinGecko new listings ────────────────────────────────────────────────────
function CGListingsSection() {
  const { data, loading, refresh } = usePolling(fetchListingsNew, 30000)
  const listings = data?.listings ?? []
  const [refreshing, setRefreshing] = useState(false)

  const forceRefresh = async () => {
    setRefreshing(true)
    await api('/listings/refresh', { method: 'POST' })
    setTimeout(() => { setRefreshing(false); refresh() }, 3000)
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">
          Recently added coins from CoinGecko. Tokens detected on active workers are auto-added to the watchlist.
          {data?.fetched_at && (
            <span className="ml-2 text-gray-700">
              Updated: {new Date(data.fetched_at * 1000).toLocaleTimeString()}
            </span>
          )}
        </p>
        <button onClick={forceRefresh} disabled={refreshing}
          className="text-xs px-3 py-1 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded border border-gray-700 disabled:opacity-50">
          {refreshing ? '⟳ Refreshing...' : '⟳ Refresh'}
        </button>
      </div>

      {loading ? <Spinner /> : listings.length === 0 ? (
        <EmptyState icon="🆕" message="No new listings fetched yet. CoinGecko data refreshes every 30 minutes." />
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden max-h-96 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-900 border-b border-gray-800">
              <tr>
                {['Symbol','Name','CoinGecko ID','Activated'].map(h => (
                  <th key={h} className="text-left py-2 px-3 text-gray-500 uppercase text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {listings.map((c, i) => (
                <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-1.5 px-3 font-bold text-white uppercase">{c.symbol}</td>
                  <td className="py-1.5 px-3 text-gray-300">{c.name}</td>
                  <td className="py-1.5 px-3 text-gray-600 font-mono text-[10px]">{c.id}</td>
                  <td className="py-1.5 px-3 text-gray-600 text-[10px]">
                    {c.activated_at ? new Date(c.activated_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────
const SECTIONS = [
  { id: 'opportunities', label: '💰 Opportunities' },
  { id: 'watchlist',     label: '👁 Watchlist' },
  { id: 'new_listings',  label: '🆕 New on CoinGecko' },
]

export default function ListingsPanel() {
  const [section, setSection] = useState('opportunities')
  const { data: oppData, loading: oppLoading } = usePolling(fetchListingsOpportunities, 10000)
  const { data: statusData } = usePolling(fetchListingsStatus, 30000)

  const opportunities = oppData?.opportunities ?? []
  const above5   = opportunities.filter(o => o.spread_pct >= 5).length
  const above10  = opportunities.filter(o => o.spread_pct >= 10).length
  const above20  = opportunities.filter(o => o.spread_pct >= 20).length

  return (
    <div className="space-y-3">
      {/* Summary */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">Watched</p>
          <p className="text-2xl font-bold text-white mt-1">{statusData?.watchlist_count ?? 0}</p>
        </div>
        <div className="bg-gray-900 border border-yellow-900/30 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">&gt;5% spread</p>
          <p className="text-2xl font-bold text-yellow-400 mt-1">{above5}</p>
        </div>
        <div className="bg-gray-900 border border-green-900/30 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">&gt;10% spread</p>
          <p className="text-2xl font-bold text-green-400 mt-1">{above10}</p>
        </div>
        <div className="bg-gray-900 border border-green-700/30 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase">&gt;20% spread</p>
          <p className="text-2xl font-bold text-green-300 mt-1">{above20}</p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1">
        {SECTIONS.map(({ id, label }) => (
          <button key={id} onClick={() => setSection(id)}
            className={`text-xs px-3 py-1.5 rounded transition-colors
              ${section === id ? 'bg-indigo-700 text-white font-medium' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {label}
          </button>
        ))}
        {statusData && (
          <span className="ml-auto text-[10px] text-gray-600 self-center">
            {statusData.total_scans} scans · {statusData.alerts_sent} alerts sent
          </span>
        )}
      </div>

      {/* Opportunities */}
      {section === 'opportunities' && (
        <Card
          title="Listing Premium Opportunities"
          subtitle={`Detected cross-exchange premiums above ${statusData?.alert_threshold_pct ?? 5}% — sorted by spread`}
        >
          {oppLoading ? <Spinner /> : opportunities.length === 0 ? (
            <EmptyState icon="💰"
              message="No listing premiums detected yet. Add tokens to the watchlist or wait for CoinGecko auto-discovery." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-gray-900 border-b border-gray-800">
                  <tr>
                    {['Token','Spread','Buy','Sell','Listed','Capital for $100','Time'].map(h => (
                      <th key={h} className="text-left py-2 px-3 text-gray-500 uppercase text-[10px]">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...opportunities]
                    .sort((a, b) => b.spread_pct - a.spread_pct)
                    .map((opp, i) => <OppRow key={i} opp={opp} />)}
                </tbody>
              </table>
            </div>
          )}

          <div className="mt-3 pt-3 border-t border-gray-800 text-[10px] text-gray-600 space-y-1">
            <p>💡 Strategy: Pre-position tokens on both exchanges BEFORE the listing. Then fire both legs simultaneously when ARBX detects the premium.</p>
            <p>⚠ These spreads are real but short-lived (hours to days). Verify order book depth before trading. Slippage on low-liquidity tokens can erase the spread.</p>
          </div>
        </Card>
      )}

      {section === 'watchlist' && (
        <Card title="Watchlist" subtitle="Tokens monitored for cross-exchange premiums">
          <WatchlistSection />
        </Card>
      )}

      {section === 'new_listings' && (
        <Card title="New on CoinGecko" subtitle="Recently added coins — potential listing arbitrage candidates">
          <CGListingsSection />
        </Card>
      )}
    </div>
  )
}
