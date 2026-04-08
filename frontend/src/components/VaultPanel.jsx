/**
 * Vault Panel (v6.5)
 * API Keys    — full-detail table with key preview, test status, last-tested timestamp
 * Wallets     — grouped by exchange; each exchange shows all its asset/network addresses
 * Taker Fees  — sortable, inline edit
 * Withdrawal  — sortable table
 * Transfer    — planner + execute
 */
import React, { useState } from 'react'
import { usePolling } from '../utils/api'
import { useSortable, SortTh } from '../utils/useSortable.jsx'
import { Card, Spinner } from './ui'

const api = (path, opts = {}) =>
  fetch('/api' + path, opts).then(r => r.json())

const SECTIONS = [
  { id: 'apikeys',    label: '🔑 API Keys' },
  { id: 'wallets',    label: '💳 Wallets' },
  { id: 'fees',       label: '💸 Taker Fees' },
  { id: 'withdrawal', label: '📤 Withdrawal Fees' },
  { id: 'transfer',   label: '🔄 Transfer Planner' },
]

function StatusMsg({ ok, msg }) {
  if (!msg) return null
  return (
    <div className={`mt-2 text-xs px-3 py-2 rounded-lg border ${
      ok ? 'bg-green-900/20 border-green-800 text-green-300'
         : 'bg-red-900/20 border-red-800 text-red-300'}`}>
      {ok ? '✓' : '✗'} {msg}
    </div>
  )
}

function InlineField({ label, value, onChange, type = 'text', placeholder = '', secret = false }) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-[10px] text-gray-500 uppercase tracking-wider">{label}</label>
      <input
        type={secret ? 'password' : type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500"
      />
    </div>
  )
}

// ── API Keys ──────────────────────────────────────────────────────────────────
function ApiKeysSection() {
  const { data, loading, error, refresh } = usePolling(() => api('/vault/apikeys'), 15000)
  const keys = data?.keys ?? []

  const { sorted, col, dir, toggle } = useSortable(keys, 'exchange', 'asc')

  const [form, setForm]     = useState({ exchange: '', api_key: '', api_secret: '', passphrase: '', label: 'main', sandbox: false })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)
  const [testState, setTestState] = useState({}) // exchange+label → { state, msg, tested_at }
  const [showAdd, setShowAdd]  = useState(false)

  const save = async () => {
    if (!form.exchange || !form.api_key || !form.api_secret) {
      setStatus({ ok: false, msg: 'Exchange, API key and secret are required' }); return
    }
    setSaving(true); setStatus(null)
    try {
      const r = await api('/vault/apikeys', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form)
      })
      if (r.ok) {
        setStatus({ ok: true, msg: `Saved API key for ${form.exchange}` })
        setForm({ exchange: '', api_key: '', api_secret: '', passphrase: '', label: 'main', sandbox: false })
        setShowAdd(false)
        refresh()
      } else {
        setStatus({ ok: false, msg: r.detail ?? 'Save failed' })
      }
    } catch (e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  const test = async (exchange, label) => {
    const key = `${exchange}:${label}`
    setTestState(t => ({ ...t, [key]: { state: 'testing', msg: '', tested_at: null } }))
    try {
      const r = await api(`/vault/apikeys/${exchange}/test?label=${label}`, { method: 'POST' })
      setTestState(t => ({ ...t, [key]: {
        state: r.ok ? 'ok' : 'error',
        msg: r.message ?? '',
        tested_at: new Date().toLocaleTimeString(),
      }}))
    } catch(e) {
      setTestState(t => ({ ...t, [key]: { state: 'error', msg: e.message, tested_at: new Date().toLocaleTimeString() } }))
    }
  }

  const del = async (exchange, label) => {
    if (!confirm(`Delete API key for ${exchange}/${label}?`)) return
    await api(`/vault/apikeys/${exchange}?label=${label}`, { method: 'DELETE' })
    refresh()
  }

  const maskKey = (k) => k ? `${k.slice(0,4)}${'●'.repeat(8)}${k.slice(-4)}` : '—'

  return (
    <div className="space-y-4">
      {loading ? <Spinner /> : error ? (
        <div className="text-xs text-red-400 bg-red-900/10 border border-red-800 rounded-lg p-3">
          ⚠ Vault unavailable: {error} — PostgreSQL may be starting up. Retrying…
        </div>
      ) : keys.length === 0 ? (
        <p className="text-xs text-gray-600 py-4 text-center">No API keys stored yet.</p>
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                <SortTh col="exchange" sortCol={col} sortDir={dir} onSort={toggle}>Exchange</SortTh>
                <SortTh col="label" sortCol={col} sortDir={dir} onSort={toggle}>Label</SortTh>
                <th className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">API Key</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">Secret</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">Passphrase</th>
                <SortTh col="sandbox" sortCol={col} sortDir={dir} onSort={toggle}>Mode</SortTh>
                <SortTh col="created_at" sortCol={col} sortDir={dir} onSort={toggle}>Created</SortTh>
                <th className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">Test</th>
                <th className="py-2 px-2"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(k => {
                const key = `${k.exchange}:${k.label}`
                const ts  = testState[key]
                return (
                  <tr key={k.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                    <td className="py-2 px-2 font-semibold text-gray-200 capitalize">{k.exchange}</td>
                    <td className="py-2 px-2 text-gray-400 font-mono">{k.label}</td>
                    <td className="py-2 px-2 font-mono text-gray-500 text-[10px]">{maskKey(k.api_key_preview)}</td>
                    <td className="py-2 px-2 font-mono text-gray-600 text-[10px]">{'●'.repeat(12)}</td>
                    <td className="py-2 px-2 text-gray-600 text-[10px]">{k.has_passphrase ? '●●●●' : '—'}</td>
                    <td className="py-2 px-2">
                      {k.sandbox
                        ? <span className="text-[9px] px-1.5 py-0.5 bg-yellow-900/30 border border-yellow-800/50 text-yellow-400 rounded">sandbox</span>
                        : <span className="text-[9px] px-1.5 py-0.5 bg-green-900/20 border border-green-800/40 text-green-500 rounded">live</span>}
                    </td>
                    <td className="py-2 px-2 text-gray-600 text-[10px]">{k.created_at?.slice(0,10)}</td>
                    <td className="py-2 px-2">
                      <div className="flex flex-col gap-0.5">
                        <button onClick={() => test(k.exchange, k.label)}
                          disabled={ts?.state === 'testing'}
                          className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
                            ts?.state === 'ok'      ? 'bg-green-900/40 text-green-400' :
                            ts?.state === 'error'   ? 'bg-red-900/40 text-red-400' :
                            ts?.state === 'testing' ? 'bg-gray-700 text-gray-400' :
                            'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                          {ts?.state === 'testing' ? '⟳' : '🔌 Test'}
                        </button>
                        {ts?.tested_at && (
                          <span className={`text-[9px] ${ts.state === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                            {ts.state === 'ok' ? '✓' : '✗'} {ts.tested_at}
                          </span>
                        )}
                        {ts?.msg && (
                          <span className="text-[9px] text-gray-600 truncate max-w-[120px]" title={ts.msg}>{ts.msg.slice(0,40)}</span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 px-2">
                      <button onClick={() => del(k.exchange, k.label)}
                        className="text-[10px] px-2 py-0.5 bg-red-900/30 text-red-400 rounded hover:bg-red-900/50">✕</button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <button onClick={() => setShowAdd(s => !s)}
        className="text-xs px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded-lg">
        {showAdd ? '▲ Hide Form' : '+ Add API Key'}
      </button>

      {showAdd && (
        <div className="border border-gray-800 rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <InlineField label="Exchange" value={form.exchange} onChange={v => setForm(f=>({...f,exchange:v}))} placeholder="binance" />
            <InlineField label="Label"    value={form.label}    onChange={v => setForm(f=>({...f,label:v}))}    placeholder="main" />
            <InlineField label="API Key"    value={form.api_key}    onChange={v=>setForm(f=>({...f,api_key:v}))}    placeholder="●●●●" secret />
            <InlineField label="API Secret" value={form.api_secret} onChange={v=>setForm(f=>({...f,api_secret:v}))} placeholder="●●●●" secret />
            <InlineField label="Passphrase (if required)" value={form.passphrase} onChange={v=>setForm(f=>({...f,passphrase:v}))} placeholder="optional" secret />
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-xs text-gray-400 cursor-pointer">
                <input type="checkbox" checked={form.sandbox} onChange={e=>setForm(f=>({...f,sandbox:e.target.checked}))} />
                Sandbox mode
              </label>
            </div>
          </div>
          <StatusMsg ok={status?.ok} msg={status?.msg} />
          <button onClick={save} disabled={saving}
            className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Saving...' : 'Save API Key'}
          </button>
          <p className="text-[10px] text-gray-600">Keys are encrypted at rest using ARBX_MASTER_KEY. Never sent to the browser in plaintext.</p>
        </div>
      )}
    </div>
  )
}

// ── Wallets ───────────────────────────────────────────────────────────────────
// Grouped by exchange → each exchange shows all its asset/network addresses as rows
function WalletsSection() {
  const { data, loading, refresh } = usePolling(() => api('/vault/wallets'), 15000)
  const wallets = data?.wallets ?? []

  const [form, setForm]     = useState({ exchange: '', coin: 'USDT', network: 'TRC20', address: '', tag: '', label: '' })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)
  const [showAdd, setShowAdd] = useState(false)
  const [copied, setCopied]   = useState(null)
  const [expandedEx, setExpandedEx] = useState(new Set())

  const NETWORKS = ['TRC20','BEP20','ERC20','SOL','MATIC','AVAX','BTC','ARB','OP','LTC','XRP','ALGO']
  const COINS    = ['USDT','USDC','BTC','ETH','BNB','SOL','XRP','ADA','DOGE','TRX','MATIC','AVAX']

  // Group wallets by exchange
  const byExchange = wallets.reduce((acc, w) => {
    const ex = w.exchange || 'unknown'
    if (!acc[ex]) acc[ex] = []
    acc[ex].push(w)
    return acc
  }, {})
  const exchanges = Object.keys(byExchange).sort()

  const toggleEx = (ex) => setExpandedEx(s => {
    const n = new Set(s)
    n.has(ex) ? n.delete(ex) : n.add(ex)
    return n
  })

  const copyAddr = (addr, id) => {
    navigator.clipboard.writeText(addr).then(() => {
      setCopied(id)
      setTimeout(() => setCopied(null), 2000)
    })
  }

  const save = async () => {
    if (!form.exchange || !form.coin || !form.network || !form.address) {
      setStatus({ ok: false, msg: 'All fields required' }); return
    }
    setSaving(true)
    try {
      const r = await api('/vault/wallets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      if (r.ok) {
        setStatus({ ok: true, msg: 'Wallet saved' })
        setShowAdd(false)
        // Auto-expand the exchange we just added to
        setExpandedEx(s => new Set([...s, form.exchange]))
        refresh()
      } else { setStatus({ ok: false, msg: r.detail }) }
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  const del = async (id) => {
    if (!confirm('Delete this wallet address?')) return
    await api(`/vault/wallets/${id}`, { method: 'DELETE' }); refresh()
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">
        Grouped by exchange. Each exchange can have multiple assets, each with its own deposit address and network.
      </p>

      {loading ? <Spinner /> : wallets.length === 0 ? (
        <p className="text-xs text-gray-600 py-4 text-center">No wallets stored. Add addresses for cross-exchange transfers.</p>
      ) : (
        <div className="space-y-2">
          {exchanges.map(ex => {
            const rows = byExchange[ex]
            const open = expandedEx.has(ex)
            return (
              <div key={ex} className="border border-gray-800 rounded-xl overflow-hidden">
                {/* Exchange header row */}
                <div
                  className="flex items-center justify-between px-4 py-2.5 bg-gray-900 cursor-pointer hover:bg-gray-800/60 select-none"
                  onClick={() => toggleEx(ex)}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-gray-200 capitalize">{ex}</span>
                    <span className="text-[10px] text-gray-600">{rows.length} address{rows.length !== 1 ? 'es' : ''}</span>
                    {/* Coin badges */}
                    <div className="flex gap-1">
                      {[...new Set(rows.map(r => r.coin))].slice(0,5).map(c => (
                        <span key={c} className="text-[9px] px-1.5 py-0.5 bg-yellow-900/30 border border-yellow-800/40 text-yellow-400 rounded font-mono">{c}</span>
                      ))}
                    </div>
                  </div>
                  <span className="text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
                </div>

                {/* Per-asset rows */}
                {open && (
                  <table className="w-full text-xs">
                    <thead className="border-b border-gray-800 bg-gray-950/40">
                      <tr>
                        {['Asset','Network','Deposit Address','Memo/Tag','Label',''].map(h => (
                          <th key={h} className="text-left py-1.5 px-3 text-gray-600 uppercase text-[9px]">{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(w => (
                        <tr key={w.id} className="border-b border-gray-800/30 hover:bg-gray-800/20">
                          <td className="py-2 px-3 font-mono font-semibold text-yellow-400">{w.coin}</td>
                          <td className="py-2 px-3 text-blue-400 font-mono text-[10px]">{w.network}</td>
                          <td className="py-2 px-3">
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono text-gray-400 text-[10px] truncate max-w-[200px]" title={w.address}>
                                {w.address.length > 20
                                  ? `${w.address.slice(0,8)}…${w.address.slice(-6)}`
                                  : w.address}
                              </span>
                              <button
                                onClick={() => copyAddr(w.address, w.id)}
                                className="shrink-0 text-[9px] px-1.5 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-500 rounded transition-colors"
                                title="Copy full address"
                              >
                                {copied === w.id ? '✓' : '⎘'}
                              </button>
                            </div>
                          </td>
                          <td className="py-2 px-3 font-mono text-gray-500 text-[10px]">{w.tag || '—'}</td>
                          <td className="py-2 px-3 text-gray-600 text-[10px]">{w.label || '—'}</td>
                          <td className="py-2 px-3">
                            <button onClick={() => del(w.id)}
                              className="text-[10px] px-2 py-0.5 bg-red-900/30 text-red-400 rounded hover:bg-red-900/50">✕</button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )
          })}
        </div>
      )}

      <button onClick={() => setShowAdd(s => !s)}
        className="text-xs px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded-lg">
        {showAdd ? '▲ Hide Form' : '+ Add Wallet Address'}
      </button>

      {showAdd && (
        <div className="border border-gray-800 rounded-xl p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-300">Add Wallet Address</p>
          <div className="grid grid-cols-2 gap-3">
            <InlineField label="Exchange (receiver)" value={form.exchange} onChange={v=>setForm(f=>({...f,exchange:v}))} placeholder="kucoin" />
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-gray-500 uppercase">Asset</label>
              <select value={form.coin} onChange={e=>setForm(f=>({...f,coin:e.target.value}))}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 focus:outline-none">
                {COINS.map(c => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] text-gray-500 uppercase">Network</label>
              <select value={form.network} onChange={e=>setForm(f=>({...f,network:e.target.value}))}
                className="bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 focus:outline-none">
                {NETWORKS.map(n => <option key={n}>{n}</option>)}
              </select>
            </div>
            <InlineField label="Label (optional)" value={form.label} onChange={v=>setForm(f=>({...f,label:v}))} placeholder="main deposit" />
          </div>
          <InlineField label="Deposit Address" value={form.address} onChange={v=>setForm(f=>({...f,address:v}))} placeholder="T... / 0x..." />
          <InlineField label="Memo / Tag (if required)" value={form.tag} onChange={v=>setForm(f=>({...f,tag:v}))} placeholder="optional — XRP tag, Binance memo, etc." />
          <StatusMsg ok={status?.ok} msg={status?.msg} />
          <button onClick={save} disabled={saving}
            className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Saving...' : 'Save Wallet'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Taker Fees ────────────────────────────────────────────────────────────────
function FeesSection() {
  const { data, loading, refresh } = usePolling(() => api('/vault/fees'), 15000)
  const fees = data?.fees ?? []
  const { sorted, col, dir, toggle } = useSortable(fees, 'exchange', 'asc')
  const [editing, setEditing] = useState({})
  const [status, setStatus]   = useState(null)

  const save = async (exchange, taker, maker) => {
    try {
      const r = await api(`/vault/fees/${exchange}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ taker_pct: parseFloat(taker), maker_pct: parseFloat(maker ?? taker) })
      })
      if (r.ok) { setStatus({ ok: true, msg: `Saved fees for ${exchange}` }); setEditing(e=>({...e,[exchange]:null})); refresh() }
      else       { setStatus({ ok: false, msg: r.detail }) }
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-gray-500">Taker fees used in net profit calculations. Click a row to edit.</p>
      {loading ? <Spinner /> : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                <SortTh col="exchange" sortCol={col} sortDir={dir} onSort={toggle}>Exchange</SortTh>
                <SortTh col="taker_pct" sortCol={col} sortDir={dir} onSort={toggle}>Taker %</SortTh>
                <SortTh col="maker_pct" sortCol={col} sortDir={dir} onSort={toggle}>Maker %</SortTh>
                <th className="py-2 px-2"></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map(f => {
                const ed = editing[f.exchange]
                return (
                  <tr key={f.exchange} className="border-b border-gray-800/40 hover:bg-gray-800/20 group cursor-pointer"
                    onClick={() => !ed && setEditing(e=>({...e,[f.exchange]:true}))}>
                    <td className="py-2 px-2 capitalize font-medium text-gray-200">{f.exchange}</td>
                    <td className="py-2 px-2 font-mono text-green-400">
                      {ed ? <input type="number" step="0.001" defaultValue={f.taker_pct}
                        id={`taker-${f.exchange}`} onClick={e=>e.stopPropagation()}
                        className="w-20 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs font-mono focus:outline-none" />
                        : `${f.taker_pct}%`}
                    </td>
                    <td className="py-2 px-2 font-mono text-blue-400">
                      {ed ? <input type="number" step="0.001" defaultValue={f.maker_pct}
                        id={`maker-${f.exchange}`} onClick={e=>e.stopPropagation()}
                        className="w-20 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs font-mono focus:outline-none" />
                        : `${f.maker_pct}%`}
                    </td>
                    <td className="py-2 px-2">
                      {ed ? (
                        <div className="flex gap-1" onClick={e=>e.stopPropagation()}>
                          <button onClick={() => save(f.exchange,
                            document.getElementById(`taker-${f.exchange}`).value,
                            document.getElementById(`maker-${f.exchange}`).value)}
                            className="text-[10px] px-2 py-0.5 bg-green-700 text-white rounded">✓</button>
                          <button onClick={() => setEditing(e=>({...e,[f.exchange]:null}))}
                            className="text-[10px] px-2 py-0.5 bg-gray-700 text-gray-400 rounded">✕</button>
                        </div>
                      ) : (
                        <span className="opacity-0 group-hover:opacity-100 text-[10px] text-gray-500 transition-opacity">✏ Edit</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <StatusMsg ok={status?.ok} msg={status?.msg} />
    </div>
  )
}

// ── Withdrawal Fees ───────────────────────────────────────────────────────────
function WithdrawalFeesSection() {
  const { data, loading, refresh } = usePolling(() => api('/vault/withdrawal-fees'), 15000)
  const fees = data?.fees ?? []
  const { sorted, col, dir, toggle } = useSortable(fees, 'exchange', 'asc')
  const [form, setForm]     = useState({ exchange: '', coin: 'USDT', network: 'TRC20', fee_amount: '', fee_usd: '', min_amount: '' })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)
  const [showAdd, setShowAdd] = useState(false)

  const save = async () => {
    setSaving(true)
    try {
      const r = await api('/vault/withdrawal-fees', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, fee_amount: parseFloat(form.fee_amount), fee_usd: parseFloat(form.fee_usd), min_amount: parseFloat(form.min_amount || 0) })
      })
      if (r.ok) { setStatus({ ok: true, msg: 'Saved' }); setShowAdd(false); refresh() }
      else       { setStatus({ ok: false, msg: r.detail }) }
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">Withdrawal fees determine cheapest network for transfers.</p>
      {loading ? <Spinner /> : (
        <div className="border border-gray-800 rounded-xl overflow-hidden max-h-96 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-900 border-b border-gray-800">
              <tr>
                <SortTh col="exchange" sortCol={col} sortDir={dir} onSort={toggle}>Exchange</SortTh>
                <SortTh col="coin" sortCol={col} sortDir={dir} onSort={toggle}>Coin</SortTh>
                <SortTh col="network" sortCol={col} sortDir={dir} onSort={toggle}>Network</SortTh>
                <SortTh col="fee_amount" sortCol={col} sortDir={dir} onSort={toggle}>Fee (coin)</SortTh>
                <SortTh col="fee_usd" sortCol={col} sortDir={dir} onSort={toggle}>Fee (USD)</SortTh>
                <SortTh col="min_amount" sortCol={col} sortDir={dir} onSort={toggle}>Min</SortTh>
              </tr>
            </thead>
            <tbody>
              {sorted.map(f => (
                <tr key={f.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-1.5 px-2 capitalize text-gray-300">{f.exchange}</td>
                  <td className="py-1.5 px-2 font-mono text-yellow-400">{f.coin}</td>
                  <td className="py-1.5 px-2 text-blue-400 font-mono text-[10px]">{f.network}</td>
                  <td className="py-1.5 px-2 font-mono text-gray-400">{f.fee_amount}</td>
                  <td className="py-1.5 px-2 font-mono text-gray-300">${f.fee_usd}</td>
                  <td className="py-1.5 px-2 font-mono text-gray-600">{f.min_amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <button onClick={() => setShowAdd(s => !s)}
        className="text-xs px-3 py-1.5 bg-gray-700 hover:bg-gray-600 text-gray-200 rounded-lg">
        {showAdd ? '▲ Hide Form' : '+ Add / Update Fee'}
      </button>

      {showAdd && (
        <div className="border border-gray-800 rounded-xl p-4 space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <InlineField label="Exchange" value={form.exchange} onChange={v=>setForm(f=>({...f,exchange:v}))} placeholder="binance" />
            <InlineField label="Coin"     value={form.coin}     onChange={v=>setForm(f=>({...f,coin:v}))}     placeholder="USDT" />
            <InlineField label="Network"  value={form.network}  onChange={v=>setForm(f=>({...f,network:v}))}  placeholder="TRC20" />
            <InlineField label="Fee (coin)" value={form.fee_amount} onChange={v=>setForm(f=>({...f,fee_amount:v}))} placeholder="1.0" />
            <InlineField label="Fee (USD)"  value={form.fee_usd}    onChange={v=>setForm(f=>({...f,fee_usd:v}))}    placeholder="1.0" />
            <InlineField label="Min withdrawal" value={form.min_amount} onChange={v=>setForm(f=>({...f,min_amount:v}))} placeholder="10.0" />
          </div>
          <StatusMsg ok={status?.ok} msg={status?.msg} />
          <button onClick={save} disabled={saving}
            className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
            {saving ? 'Saving...' : 'Save Fee'}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Transfer Planner ──────────────────────────────────────────────────────────
function TransferPlannerSection() {
  const [form, setForm]         = useState({ from_exchange: '', to_exchange: '', coin: 'USDT', amount: '' })
  const [plan, setPlan]         = useState(null)
  const [planning, setPlanning] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [result, setResult]     = useState(null)

  const planTransfer = async () => {
    setPlanning(true); setPlan(null); setResult(null)
    try {
      const r = await api('/vault/transfer/plan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, amount: parseFloat(form.amount) })
      })
      setPlan(r)
    } catch(e) { setPlan({ ok: false, message: e.message }) }
    finally { setPlanning(false) }
  }

  const execute = async () => {
    if (!confirm(`EXECUTE transfer of ${plan.amount} ${plan.coin} from ${plan.from} to ${plan.to} via ${plan.network}?\n\nFee: ${plan.fee_amount} ${plan.coin} (~$${plan.fee_usd})\nDestination: ${plan.destination}\n\nThis is IRREVERSIBLE.`)) return
    setExecuting(true)
    try {
      const r = await api('/vault/transfer/execute?confirm=true', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, amount: parseFloat(form.amount) })
      })
      setResult(r)
    } catch(e) { setResult({ ok: false, message: e.message }) }
    finally { setExecuting(false) }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">
        Plans the cheapest route using stored wallet addresses and withdrawal fees.
        Requires API key for source exchange and wallet address for destination.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <InlineField label="From exchange" value={form.from_exchange} onChange={v=>setForm(f=>({...f,from_exchange:v}))} placeholder="binance" />
        <InlineField label="To exchange"   value={form.to_exchange}   onChange={v=>setForm(f=>({...f,to_exchange:v}))}   placeholder="mexc" />
        <InlineField label="Coin"          value={form.coin}          onChange={v=>setForm(f=>({...f,coin:v}))}          placeholder="USDT" />
        <InlineField label="Amount"        value={form.amount}        onChange={v=>setForm(f=>({...f,amount:v}))}        placeholder="500" type="number" />
      </div>
      <button onClick={planTransfer} disabled={planning || !form.from_exchange || !form.to_exchange || !form.amount}
        className="text-xs px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white rounded-lg disabled:opacity-50">
        {planning ? '⟳ Planning...' : '🔍 Plan Transfer'}
      </button>

      {plan && (
        <div className={`border rounded-xl p-4 space-y-3 ${plan.ok ? 'border-green-800 bg-green-900/10' : 'border-red-800 bg-red-900/10'}`}>
          {plan.ok ? (
            <>
              <p className="text-xs font-semibold text-green-300">Transfer Plan</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div><span className="text-gray-500">Route:</span> <span className="font-mono text-gray-200">{plan.from} → {plan.network} → {plan.to}</span></div>
                <div><span className="text-gray-500">Amount:</span> <span className="font-mono text-gray-200">{plan.amount} {plan.coin}</span></div>
                <div><span className="text-gray-500">Fee:</span> <span className="text-yellow-400 font-mono">{plan.fee_amount} {plan.coin} (≈${plan.fee_usd})</span></div>
                <div><span className="text-gray-500">Net received:</span> <span className="text-green-400 font-mono font-bold">{plan.net_amount} {plan.coin}</span></div>
                <div className="col-span-2"><span className="text-gray-500">Destination:</span> <span className="text-gray-400 font-mono text-[10px] break-all">{plan.destination}</span></div>
              </div>
              {plan.executable ? (
                <>
                  <div className="bg-red-900/20 border border-red-800/50 rounded p-2 text-xs text-red-300">⚠ {plan.note}</div>
                  <button onClick={execute} disabled={executing}
                    className="text-xs px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded-lg disabled:opacity-50 font-semibold">
                    {executing ? '⟳ Executing...' : '🚀 Execute Transfer (Irreversible)'}
                  </button>
                </>
              ) : (
                <p className="text-xs text-red-400">Amount is below the minimum withdrawal ({plan.min_amount} {plan.coin})</p>
              )}
            </>
          ) : (
            <p className="text-xs text-red-300">✗ {plan.message}</p>
          )}
        </div>
      )}

      {result && (
        <div className={`border rounded-xl p-4 text-xs ${result.ok ? 'border-green-800 bg-green-900/10 text-green-300' : 'border-red-800 bg-red-900/10 text-red-300'}`}>
          {result.ok ? `✓ Transfer submitted — TX: ${result.result?.id ?? 'pending'}` : `✗ ${result.message}`}
        </div>
      )}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function VaultPanel() {
  const [section, setSection] = useState('apikeys')
  return (
    <div className="space-y-3">
      <div className="flex gap-1 flex-wrap">
        {SECTIONS.map(({ id, label }) => (
          <button key={id} onClick={() => setSection(id)}
            className={`text-xs px-3 py-1.5 rounded transition-colors
              ${section === id ? 'bg-indigo-700 text-white font-medium' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {label}
          </button>
        ))}
      </div>
      {section === 'apikeys'    && <Card title="API Keys"          subtitle="Exchange credentials — encrypted at rest · click column headers to sort"><ApiKeysSection /></Card>}
      {section === 'wallets'    && <Card title="Wallet Addresses"  subtitle="Grouped by exchange — each asset has its own deposit address"><WalletsSection /></Card>}
      {section === 'fees'       && <Card title="Taker Fees"        subtitle="Used in all net profit calculations · click to edit"><FeesSection /></Card>}
      {section === 'withdrawal' && <Card title="Withdrawal Fees"   subtitle="Per-exchange, per-coin, per-network transfer costs · click headers to sort"><WithdrawalFeesSection /></Card>}
      {section === 'transfer'   && <Card title="Transfer Planner"  subtitle="Plan and execute cross-exchange transfers"><TransferPlannerSection /></Card>}
    </div>
  )
}
