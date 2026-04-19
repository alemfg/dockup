/**
 * Orders Panel (v6.9)
 * Fixes:
 *  - Blink bug: usePolling was re-firing on every render (inline fn ref) — fixed in api.js
 *  - Empty pair column: graph_arb blocked orders store path in notes, not pair — now shown
 *  - "Denied" status: was showing log_notes as status — now status is correct, reason shown separately
 *  - Added mode filter (SIMULATE / LIVE / ALL) and source filter (graph_arb / manual / spatial / all)
 *  - Added status filter (all / blocked / simulate / live / filled / cancelled)
 */
import React, { useState, useMemo } from 'react'
import { usePolling, fetchOpenOrders, fetchOrderLog, fetchTradingMode } from '../utils/api'
import { useSortable, SortTh } from '../utils/useSortable.jsx'
import { Card, EmptyState, Spinner } from './ui'

const SECTIONS = [
  { id: 'open',    label: '📋 Open Orders' },
  { id: 'history', label: '📜 History' },
  { id: 'place',   label: '➕ Place Order' },
]

function statusColor(s) {
  if (['filled','closed'].includes(s))             return 'text-green-400'
  if (['pending','sent','partial'].includes(s))    return 'text-yellow-400'
  if (['failed','cancelled'].includes(s))          return 'text-red-400'
  if (s === 'blocked')                             return 'text-gray-500'
  if (s === 'simulate')                            return 'text-blue-400'
  return 'text-gray-500'
}

function pnlColor(v) {
  if (v > 0) return 'text-green-400'
  if (v < 0) return 'text-red-400'
  return 'text-gray-500'
}

function ModeBadge({ mode, status }) {
  // blocked orders: show "blocked" badge regardless of mode
  if (status === 'blocked') {
    return (
      <span className="text-[9px] px-1.5 py-0.5 rounded border text-gray-500 bg-gray-800 border-gray-700">
        blocked
      </span>
    )
  }
  if (mode === 'live') {
    return (
      <span className="text-[9px] px-1.5 py-0.5 rounded border text-red-400 border-red-800 bg-red-900/20">
        LIVE
      </span>
    )
  }
  return (
    <span className="text-[9px] px-1.5 py-0.5 rounded border text-blue-400 border-blue-800 bg-blue-900/20">
      sim
    </span>
  )
}

// ── Open Orders ───────────────────────────────────────────────────────────────
function OpenOrdersSection() {
  const { data, loading, refresh } = usePolling(fetchOpenOrders, 5000)
  const orders = data?.orders ?? []
  const [cancelling, setCancelling] = useState({})
  const [syncing, setSyncing] = useState(false)
  const [syncMsg, setSyncMsg] = useState(null)

  const { sorted, col, dir, toggle } = useSortable(orders, 'pair', 'asc')

  const cancel = async (id) => {
    setCancelling(c => ({ ...c, [id]: true }))
    try {
      await fetch(`/api/orders/${id}/cancel`, { method: 'POST' })
      refresh()
    } finally {
      setCancelling(c => ({ ...c, [id]: false }))
    }
  }

  const syncNow = async () => {
    setSyncing(true); setSyncMsg(null)
    try {
      const r = await fetch('/api/orders/sync', { method: 'POST' }).then(x => x.json())
      setSyncMsg(r.message)
      setTimeout(() => { setSyncMsg(null); refresh() }, 5000)
    } catch(e) { setSyncMsg(e.message) }
    finally { setSyncing(false) }
  }

  if (loading) return <Spinner />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-gray-500">{orders.length} open order{orders.length !== 1 ? 's' : ''}</span>
        <div className="flex items-center gap-2">
          {syncMsg && <span className="text-[10px] text-blue-400">{syncMsg}</span>}
          <button onClick={syncNow} disabled={syncing}
            className="text-xs px-3 py-1.5 bg-blue-800/60 hover:bg-blue-700 text-blue-300 border border-blue-700/50 rounded-lg disabled:opacity-50 transition-colors">
            {syncing ? '⟳ Syncing...' : '⟳ Sync from Exchanges'}
          </button>
        </div>
      </div>

      {orders.length === 0 ? (
        <EmptyState icon="📋" message="No open orders. Place one below or wait for a signal." />
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                <SortTh col="pair"         sortCol={col} sortDir={dir} onSort={toggle}>Pair</SortTh>
                <SortTh col="exchange"     sortCol={col} sortDir={dir} onSort={toggle}>Exchange</SortTh>
                <SortTh col="side"         sortCol={col} sortDir={dir} onSort={toggle}>Side</SortTh>
                <SortTh col="order_type"   sortCol={col} sortDir={dir} onSort={toggle}>Type</SortTh>
                <SortTh col="volume"       sortCol={col} sortDir={dir} onSort={toggle}>Volume</SortTh>
                <SortTh col="price"        sortCol={col} sortDir={dir} onSort={toggle}>Price</SortTh>
                <SortTh col="trading_mode" sortCol={col} sortDir={dir} onSort={toggle}>Mode</SortTh>
                <SortTh col="status"       sortCol={col} sortDir={dir} onSort={toggle}>Status</SortTh>
                <th className="py-2 px-2 text-gray-500 uppercase text-[10px]">Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(o => (
                <tr key={o.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-2 px-2 font-medium text-gray-200">{o.pair}</td>
                  <td className="py-2 px-2 text-gray-400 capitalize">{o.exchange}</td>
                  <td className={`py-2 px-2 font-semibold ${o.side === 'buy' ? 'text-green-400' : 'text-red-400'}`}>{o.side?.toUpperCase()}</td>
                  <td className="py-2 px-2 text-gray-500 capitalize">{o.order_type}</td>
                  <td className="py-2 px-2 font-mono text-gray-300">{o.volume}</td>
                  <td className="py-2 px-2 font-mono text-gray-300">{o.price > 0 ? o.price.toFixed(4) : 'market'}</td>
                  <td className="py-2 px-2"><ModeBadge mode={o.trading_mode} status={o.status} /></td>
                  <td className={`py-2 px-2 capitalize ${statusColor(o.status)}`}>{o.status}</td>
                  <td className="py-2 px-2">
                    <button onClick={() => cancel(o.id)} disabled={cancelling[o.id]}
                      className="text-[10px] px-2 py-0.5 bg-red-900/30 text-red-400 rounded hover:bg-red-900/50 disabled:opacity-50">
                      {cancelling[o.id] ? '⟳' : '✕ Cancel'}
                    </button>
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

// ── Order History ─────────────────────────────────────────────────────────────
function OrderHistorySection() {
  const { data, loading } = usePolling(fetchOrderLog, 15000)
  const orders = data?.orders ?? []
  const stats  = data?.stats  ?? {}

  // Filter state
  const [modeFilter,   setModeFilter]   = useState('all')   // all | simulate | live
  const [sourceFilter, setSourceFilter] = useState('all')   // all | graph_arb | spatial_arb | manual
  const [statusFilter, setStatusFilter] = useState('all')   // all | blocked | simulate | live | filled | cancelled

  const filtered = useMemo(() => {
    return orders.filter(o => {
      if (modeFilter !== 'all' && o.trading_mode !== modeFilter) return false
      if (sourceFilter !== 'all' && o.source !== sourceFilter)   return false
      if (statusFilter !== 'all') {
        if (statusFilter === 'blocked'  && o.status !== 'blocked')  return false
        if (statusFilter === 'simulate' && o.status !== 'simulate') return false
        if (statusFilter === 'live'     && o.status !== 'live')     return false
        if (statusFilter === 'filled'   && !['filled','closed'].includes(o.status)) return false
        if (statusFilter === 'cancelled'&& o.status !== 'cancelled') return false
      }
      return true
    })
  }, [orders, modeFilter, sourceFilter, statusFilter])

  const { sorted, col, dir, toggle } = useSortable(filtered, 'created_at', 'desc')

  // Derive unique sources for filter
  const sources = useMemo(() => {
    const s = new Set(orders.map(o => o.source).filter(Boolean))
    return ['all', ...Array.from(s).sort()]
  }, [orders])

  if (loading) return <Spinner />

  // Counts for badges
  const blockedCount  = orders.filter(o => o.status === 'blocked').length
  const simCount      = orders.filter(o => o.trading_mode === 'simulate' && o.status !== 'blocked').length
  const liveCount     = orders.filter(o => o.trading_mode === 'live').length

  return (
    <div className="space-y-4">
      {/* Stats summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total decisions', value: stats.total_decisions ?? orders.length },
          { label: 'Simulated',       value: simCount,     color: 'text-blue-400' },
          { label: 'Live',            value: liveCount,    color: 'text-red-400' },
          { label: 'Blocked',         value: blockedCount, color: 'text-gray-500' },
        ].map(s => (
          <div key={s.label} className="bg-gray-900 border border-gray-800 rounded-xl p-3">
            <p className="text-[10px] text-gray-500 uppercase">{s.label}</p>
            <p className={`text-xl font-bold mt-1 ${s.color ?? 'text-white'}`}>{s.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center bg-gray-900 border border-gray-800 rounded-xl p-3">
        {/* Mode filter */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-600 uppercase">Mode:</span>
          {['all','simulate','live'].map(m => (
            <button key={m} onClick={() => setModeFilter(m)}
              className={`text-[10px] px-2 py-0.5 rounded transition-colors capitalize ${
                modeFilter === m ? 'bg-indigo-700 text-white' : 'bg-gray-800 text-gray-500 hover:bg-gray-700'}`}>
              {m}
            </button>
          ))}
        </div>

        <div className="w-px h-4 bg-gray-700" />

        {/* Status filter */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-gray-600 uppercase">Status:</span>
          {['all','blocked','simulate','live','filled','cancelled'].map(s => (
            <button key={s} onClick={() => setStatusFilter(s)}
              className={`text-[10px] px-2 py-0.5 rounded transition-colors capitalize ${
                statusFilter === s ? 'bg-indigo-700 text-white' : 'bg-gray-800 text-gray-500 hover:bg-gray-700'}`}>
              {s}
            </button>
          ))}
        </div>

        <div className="w-px h-4 bg-gray-700" />

        {/* Source filter */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-gray-600 uppercase">Source:</span>
          {sources.map(s => (
            <button key={s} onClick={() => setSourceFilter(s)}
              className={`text-[10px] px-2 py-0.5 rounded transition-colors font-mono ${
                sourceFilter === s ? 'bg-indigo-700 text-white' : 'bg-gray-800 text-gray-500 hover:bg-gray-700'}`}>
              {s}
            </button>
          ))}
        </div>

        <span className="ml-auto text-[10px] text-gray-600">
          Showing {filtered.length} / {orders.length}
        </span>
      </div>

      {filtered.length === 0 ? (
        <EmptyState icon="📜" message="No orders match current filters." />
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                <SortTh col="pair"         sortCol={col} sortDir={dir} onSort={toggle}>Pair / Path</SortTh>
                <SortTh col="exchange"     sortCol={col} sortDir={dir} onSort={toggle}>Exchange</SortTh>
                <SortTh col="side"         sortCol={col} sortDir={dir} onSort={toggle}>Side</SortTh>
                <SortTh col="source"       sortCol={col} sortDir={dir} onSort={toggle}>Source</SortTh>
                <SortTh col="status"       sortCol={col} sortDir={dir} onSort={toggle}>Status</SortTh>
                <SortTh col="pnl_usd"      sortCol={col} sortDir={dir} onSort={toggle}>P&L</SortTh>
                <th className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">Mode</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">Reason / Notes</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(o => {
                const pnl = o.pnl_usd ?? 0
                // For graph_arb blocked orders: pair may be empty; show path from notes
                const displayPair = o.pair || o.log_notes?.match(/path=([^\s|]+)/)?.[1] || '—'
                // Reason is log_notes for blocked, or notes for others
                const reason = o.status === 'blocked'
                  ? (o.log_notes || o.notes || '—')
                  : (o.notes || o.log_notes || '—')
                return (
                  <tr key={o.id} className={`border-b border-gray-800/40 hover:bg-gray-800/20 ${o.status === 'blocked' ? 'opacity-60' : ''}`}>
                    <td className="py-1.5 px-2 font-medium text-gray-200 max-w-[140px] truncate" title={displayPair}>
                      {displayPair}
                    </td>
                    <td className="py-1.5 px-2 text-gray-400 capitalize">{o.exchange || '—'}</td>
                    <td className={`py-1.5 px-2 font-semibold ${o.side === 'buy' ? 'text-green-400' : o.side === 'sell' ? 'text-red-400' : 'text-gray-600'}`}>
                      {o.side?.toUpperCase() || '—'}
                    </td>
                    <td className="py-1.5 px-2 text-gray-500 font-mono text-[10px]">{o.source || '—'}</td>
                    <td className={`py-1.5 px-2 capitalize font-medium ${statusColor(o.status)}`}>{o.status}</td>
                    <td className={`py-1.5 px-2 font-mono font-semibold ${pnlColor(pnl)}`}>
                      {pnl !== 0 ? `${pnl > 0 ? '+' : ''}$${pnl.toFixed(2)}` : '—'}
                    </td>
                    <td className="py-1.5 px-2">
                      <ModeBadge mode={o.trading_mode} status={o.status} />
                    </td>
                    <td className="py-1.5 px-2 text-gray-600 text-[10px] max-w-[180px] truncate" title={reason}>
                      {reason}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function PlaceOrderSection() {
  const [form, setForm] = useState({
    exchange: '', pair: 'BTC/USDT', side: 'buy',
    order_type: 'market', volume: '', price: '', stop_loss: '',
    take_profit: '', notes: 'manual', confirm: false,
  })
  const [busy,   setBusy]   = useState(false)
  const [result, setResult] = useState(null)

  const { data: modeData } = usePolling(fetchTradingMode, 5000)
  const mode = modeData?.mode ?? 'disabled'

  const place = async () => {
    if (!form.exchange || !form.pair || !form.volume) {
      setResult({ ok: false, message: 'Exchange, pair, and volume are required' }); return
    }
    if (mode === 'disabled') {
      setResult({ ok: false, message: 'Trading is DISABLED. Go to Trading Mode tab to enable.' }); return
    }
    if (mode === 'live' && !form.confirm) {
      setResult({ ok: false, message: 'Check "Confirm LIVE order" before placing a real order.' }); return
    }
    setBusy(true); setResult(null)
    try {
      const r = await fetch('/api/orders/place', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          volume:       parseFloat(form.volume),
          price:        parseFloat(form.price || 0),
          stop_loss:    parseFloat(form.stop_loss || 0),
          take_profit:  parseFloat(form.take_profit || 0),
        })
      }).then(x => x.json())
      setResult(r)
    } catch(e) { setResult({ ok: false, message: e.message }) }
    finally { setBusy(false) }
  }

  const F = ({ label, id, type = 'text', placeholder = '' }) => (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] text-gray-500 uppercase">{label}</label>
      <input type={type} value={form[id]} onChange={e => setForm(f => ({ ...f, [id]: e.target.value }))}
        placeholder={placeholder}
        className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500" />
    </div>
  )

  return (
    <div className="space-y-4">
      <div className={`border rounded-lg p-3 text-xs flex items-center gap-2 ${
        mode === 'live'     ? 'border-red-800 bg-red-900/10 text-red-300' :
        mode === 'simulate' ? 'border-blue-800 bg-blue-900/10 text-blue-300' :
                              'border-gray-700 bg-gray-800/50 text-gray-500'}`}>
        <span>{mode === 'live' ? '🔴' : mode === 'simulate' ? '🔵' : '⬛'}</span>
        <span className="font-semibold capitalize">{mode}</span>
        <span className="text-gray-500">—</span>
        <span>{modeData?.description ?? 'Trading is disabled'}</span>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <F label="Exchange" id="exchange" placeholder="binance" />
        <F label="Pair"     id="pair"     placeholder="BTC/USDT" />
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase">Side</label>
          <div className="flex gap-2">
            {['buy','sell'].map(s => (
              <button key={s} onClick={() => setForm(f => ({ ...f, side: s }))}
                className={`flex-1 text-xs py-2 rounded font-semibold capitalize transition-colors ${
                  form.side === s
                    ? s === 'buy' ? 'bg-green-700 text-white' : 'bg-red-700 text-white'
                    : 'bg-gray-800 text-gray-500 hover:bg-gray-700'}`}>
                {s}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-gray-500 uppercase">Order Type</label>
          <div className="flex gap-2">
            {['market','limit'].map(t => (
              <button key={t} onClick={() => setForm(f => ({ ...f, order_type: t }))}
                className={`flex-1 text-xs py-2 rounded capitalize transition-colors ${
                  form.order_type === t ? 'bg-indigo-700 text-white' : 'bg-gray-800 text-gray-500 hover:bg-gray-700'}`}>
                {t}
              </button>
            ))}
          </div>
        </div>
        <F label="Volume (base asset)" id="volume" type="number" placeholder="0.001" />
        {form.order_type === 'limit' && <F label="Limit Price" id="price" type="number" placeholder="45000" />}
        <F label="Stop Loss (optional)"   id="stop_loss"   type="number" placeholder="0" />
        <F label="Take Profit (optional)" id="take_profit" type="number" placeholder="0" />
        <div className="col-span-2"><F label="Notes" id="notes" placeholder="manual entry" /></div>
      </div>

      {mode === 'live' && (
        <label className="flex items-center gap-2 cursor-pointer text-xs text-red-400 bg-red-900/10 border border-red-800 rounded-lg p-3">
          <input type="checkbox" checked={form.confirm} onChange={e => setForm(f => ({ ...f, confirm: e.target.checked }))} />
          I confirm this will place a REAL order on {form.exchange || 'the exchange'} using real funds
        </label>
      )}

      {result && (
        <div className={`text-xs px-3 py-2 rounded-lg border ${
          result.ok ? 'bg-green-900/20 border-green-800 text-green-300' : 'bg-red-900/20 border-red-800 text-red-300'}`}>
          {result.ok ? `✓ ${result.message} — ID: ${result.order_id?.slice(0,8)}` : `✗ ${result.message}`}
        </div>
      )}

      <button onClick={place} disabled={busy || mode === 'disabled'}
        className={`text-xs px-6 py-2.5 rounded-lg font-semibold disabled:opacity-40 transition-colors ${
          mode === 'live' ? 'bg-red-700 hover:bg-red-600 text-white' :
          mode === 'simulate' ? 'bg-blue-700 hover:bg-blue-600 text-white' :
          'bg-gray-700 text-gray-400'}`}>
        {busy ? '⟳ Placing...' :
          mode === 'live' ? '🔴 Place LIVE Order' :
          mode === 'simulate' ? '🔵 Simulate Order' : '⬛ Trading Disabled'}
      </button>
    </div>
  )
}

// Missing import that was in original
// ── Main ──────────────────────────────────────────────────────────────────────
export default function OrdersPanel() {
  const [section, setSection] = useState('open')
  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        {SECTIONS.map(({ id, label }) => (
          <button key={id} onClick={() => setSection(id)}
            className={`text-xs px-3 py-1.5 rounded transition-colors
              ${section === id ? 'bg-indigo-700 text-white font-medium' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {label}
          </button>
        ))}
      </div>
      {section === 'open'    && <Card title="Open Orders"   subtitle="Live and simulated positions in flight"><OpenOrdersSection /></Card>}
      {section === 'history' && <Card title="Order History" subtitle="All decisions — use filters to focus on simulate/live/blocked"><OrderHistorySection /></Card>}
      {section === 'place'   && <Card title="Place Order"   subtitle="Manual order entry — LIVE requires API key in Vault"><PlaceOrderSection /></Card>}
    </div>
  )
}
