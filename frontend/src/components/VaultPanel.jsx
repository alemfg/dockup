/**
 * Vault Panel (v6.0)
 * DB-backed: API keys, wallet addresses, fee tables, transfer planning.
 */
import React, { useState } from 'react'
import { usePolling } from '../utils/api'
import { Card, Spinner } from './ui'

const api = (path, opts = {}) =>
  fetch('/api' + path, opts).then(r => r.json())

// ── Section tabs ──────────────────────────────────────────────────────────────
const SECTIONS = [
  { id: 'apikeys',   label: '🔑 API Keys' },
  { id: 'wallets',   label: '💳 Wallets' },
  { id: 'fees',      label: '💸 Taker Fees' },
  { id: 'withdrawal',label: '📤 Withdrawal Fees' },
  { id: 'transfer',  label: '🔄 Transfer Planner' },
]

// ── Shared ────────────────────────────────────────────────────────────────────
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
  const { data, loading, refresh } = usePolling(() => api('/vault/apikeys'), 15000)
  const keys = data?.keys ?? []

  const [form, setForm]   = useState({ exchange: '', api_key: '', api_secret: '', passphrase: '', label: 'main', sandbox: false })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)
  const [testing, setTesting] = useState({})

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
      if (r.ok) { setStatus({ ok: true, msg: `Saved API key for ${form.exchange}` }); setForm({ exchange: '', api_key: '', api_secret: '', passphrase: '', label: 'main', sandbox: false }); refresh() }
      else       { setStatus({ ok: false, msg: r.detail ?? 'Save failed' }) }
    } catch (e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  const test = async (exchange, label) => {
    setTesting(t => ({ ...t, [exchange]: 'testing' }))
    try {
      const r = await api(`/vault/apikeys/${exchange}/test?label=${label}`, { method: 'POST' })
      setTesting(t => ({ ...t, [exchange]: r.ok ? 'ok' : 'error' }))
      setStatus({ ok: r.ok, msg: r.message })
    } catch { setTesting(t => ({ ...t, [exchange]: 'error' })) }
  }

  const del = async (exchange, label) => {
    if (!confirm(`Delete API key for ${exchange}/${label}?`)) return
    await api(`/vault/apikeys/${exchange}?label=${label}`, { method: 'DELETE' })
    refresh()
  }

  return (
    <div className="space-y-4">
      {/* Existing keys */}
      {loading ? <Spinner /> : keys.length === 0 ? (
        <p className="text-xs text-gray-600 py-4 text-center">No API keys stored yet.</p>
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                {['Exchange','Label','Sandbox','Created','Actions'].map(h => (
                  <th key={h} className="text-left py-2 px-3 text-gray-500 uppercase text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {keys.map(k => (
                <tr key={k.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-2 px-3 font-semibold text-gray-200 capitalize">{k.exchange}</td>
                  <td className="py-2 px-3 text-gray-500 font-mono">{k.label}</td>
                  <td className="py-2 px-3">{k.sandbox ? <span className="text-yellow-400">sandbox</span> : <span className="text-gray-600">live</span>}</td>
                  <td className="py-2 px-3 text-gray-600">{k.created_at?.slice(0,10)}</td>
                  <td className="py-2 px-3">
                    <div className="flex gap-1.5">
                      <button onClick={() => test(k.exchange, k.label)}
                        className={`text-[10px] px-2 py-0.5 rounded ${
                          testing[k.exchange] === 'ok' ? 'bg-green-900/40 text-green-400' :
                          testing[k.exchange] === 'error' ? 'bg-red-900/40 text-red-400' :
                          'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                        {testing[k.exchange] === 'testing' ? '⟳' : '🔌 Test'}
                      </button>
                      <button onClick={() => del(k.exchange, k.label)}
                        className="text-[10px] px-2 py-0.5 bg-red-900/30 text-red-400 rounded hover:bg-red-900/50">✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add new */}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-300">Add API Key</p>
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
    </div>
  )
}

// ── Wallets ───────────────────────────────────────────────────────────────────
function WalletsSection() {
  const { data, loading, refresh } = usePolling(() => api('/vault/wallets'), 15000)
  const wallets = data?.wallets ?? []
  const [form, setForm]     = useState({ exchange: '', coin: 'USDT', network: 'TRC20', address: '', tag: '', label: '' })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)

  const NETWORKS = ['TRC20','BEP20','ERC20','SOL','MATIC','AVAX','BTC','ARB']
  const COINS    = ['USDT','USDC','BTC','ETH','BNB','SOL','XRP']

  const save = async () => {
    if (!form.exchange || !form.coin || !form.network || !form.address) {
      setStatus({ ok: false, msg: 'All fields required' }); return
    }
    setSaving(true)
    try {
      const r = await api('/vault/wallets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) })
      if (r.ok) { setStatus({ ok: true, msg: 'Wallet saved' }); refresh() }
      else       { setStatus({ ok: false, msg: r.detail }) }
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  const del = async (id) => {
    await api(`/vault/wallets/${id}`, { method: 'DELETE' }); refresh()
  }

  return (
    <div className="space-y-4">
      {loading ? <Spinner /> : wallets.length === 0 ? (
        <p className="text-xs text-gray-600 py-4 text-center">No wallets stored. Add addresses for cross-exchange transfers.</p>
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                {['Exchange','Coin','Network','Address','Actions'].map(h=>(
                  <th key={h} className="text-left py-2 px-3 text-gray-500 uppercase text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {wallets.map(w => (
                <tr key={w.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-2 px-3 capitalize text-gray-200">{w.exchange}</td>
                  <td className="py-2 px-3 font-mono text-yellow-400">{w.coin}</td>
                  <td className="py-2 px-3 text-blue-400">{w.network}</td>
                  <td className="py-2 px-3 font-mono text-gray-400 text-[10px] truncate max-w-[160px]" title={w.address}>{w.address}</td>
                  <td className="py-2 px-3">
                    <button onClick={() => del(w.id)} className="text-[10px] px-2 py-0.5 bg-red-900/30 text-red-400 rounded">✕</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-300">Add Wallet (deposit address)</p>
        <div className="grid grid-cols-2 gap-3">
          <InlineField label="Exchange (receiver)" value={form.exchange} onChange={v=>setForm(f=>({...f,exchange:v}))} placeholder="kucoin" />
          <div className="flex flex-col gap-1">
            <label className="text-[10px] text-gray-500 uppercase">Coin</label>
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
          <InlineField label="Label" value={form.label} onChange={v=>setForm(f=>({...f,label:v}))} placeholder="optional" />
        </div>
        <InlineField label="Deposit Address" value={form.address} onChange={v=>setForm(f=>({...f,address:v}))} placeholder="T... / 0x..." />
        <InlineField label="Memo / Tag (if required)" value={form.tag} onChange={v=>setForm(f=>({...f,tag:v}))} placeholder="optional" />
        <StatusMsg ok={status?.ok} msg={status?.msg} />
        <button onClick={save} disabled={saving}
          className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
          {saving ? 'Saving...' : 'Save Wallet'}
        </button>
      </div>
    </div>
  )
}

// ── Taker Fees ────────────────────────────────────────────────────────────────
function FeesSection() {
  const { data, loading, refresh } = usePolling(() => api('/vault/fees'), 15000)
  const fees = data?.fees ?? []
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
      <p className="text-xs text-gray-500">Taker fees used in net profit calculations for Spatial Arb and Graph Arb. Hover to edit.</p>
      {loading ? <Spinner /> : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                {['Exchange','Taker %','Maker %',''].map(h=>(
                  <th key={h} className="text-left py-2 px-3 text-gray-500 uppercase text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fees.map(f => {
                const ed = editing[f.exchange]
                return (
                  <tr key={f.exchange} className="border-b border-gray-800/40 hover:bg-gray-800/20 group">
                    <td className="py-2 px-3 capitalize font-medium text-gray-200">{f.exchange}</td>
                    <td className="py-2 px-3 font-mono text-green-400">
                      {ed ? <input type="number" step="0.001" defaultValue={f.taker_pct}
                        id={`taker-${f.exchange}`}
                        className="w-20 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs font-mono focus:outline-none" />
                        : `${f.taker_pct}%`}
                    </td>
                    <td className="py-2 px-3 font-mono text-blue-400">
                      {ed ? <input type="number" step="0.001" defaultValue={f.maker_pct}
                        id={`maker-${f.exchange}`}
                        className="w-20 bg-gray-800 border border-gray-600 rounded px-1 py-0.5 text-xs font-mono focus:outline-none" />
                        : `${f.maker_pct}%`}
                    </td>
                    <td className="py-2 px-3">
                      {ed ? (
                        <div className="flex gap-1">
                          <button onClick={() => save(f.exchange,
                            document.getElementById(`taker-${f.exchange}`).value,
                            document.getElementById(`maker-${f.exchange}`).value)}
                            className="text-[10px] px-2 py-0.5 bg-green-700 text-white rounded">✓</button>
                          <button onClick={() => setEditing(e=>({...e,[f.exchange]:null}))}
                            className="text-[10px] px-2 py-0.5 bg-gray-700 text-gray-400 rounded">✕</button>
                        </div>
                      ) : (
                        <button onClick={() => setEditing(e=>({...e,[f.exchange]:true}))}
                          className="opacity-0 group-hover:opacity-100 text-[10px] px-2 py-0.5 bg-gray-800 text-gray-400 rounded transition-opacity">Edit</button>
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
  const [form, setForm]     = useState({ exchange: '', coin: 'USDT', network: 'TRC20', fee_amount: '', fee_usd: '', min_amount: '' })
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState(null)

  const save = async () => {
    setSaving(true)
    try {
      const r = await api('/vault/withdrawal-fees', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, fee_amount: parseFloat(form.fee_amount), fee_usd: parseFloat(form.fee_usd), min_amount: parseFloat(form.min_amount || 0) })
      })
      if (r.ok) { setStatus({ ok: true, msg: 'Saved' }); refresh() }
      else       { setStatus({ ok: false, msg: r.detail }) }
    } catch(e) { setStatus({ ok: false, msg: e.message }) }
    finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-gray-500">Withdrawal fees determine cheapest network for transfers. Pre-populated with typical values — update for your VIP tier.</p>
      {loading ? <Spinner /> : (
        <div className="border border-gray-800 rounded-xl overflow-hidden max-h-80 overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-900 border-b border-gray-800">
              <tr>
                {['Exchange','Coin','Network','Fee (coin)','Fee (USD)','Min'].map(h=>(
                  <th key={h} className="text-left py-2 px-2 text-gray-500 uppercase text-[10px]">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fees.map(f => (
                <tr key={f.id} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                  <td className="py-1.5 px-2 capitalize text-gray-300">{f.exchange}</td>
                  <td className="py-1.5 px-2 font-mono text-yellow-400">{f.coin}</td>
                  <td className="py-1.5 px-2 text-blue-400">{f.network}</td>
                  <td className="py-1.5 px-2 font-mono text-gray-400">{f.fee_amount}</td>
                  <td className="py-1.5 px-2 font-mono text-gray-300">${f.fee_usd}</td>
                  <td className="py-1.5 px-2 font-mono text-gray-600">{f.min_amount}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <p className="text-xs font-semibold text-gray-300">Add / Update Withdrawal Fee</p>
        <div className="grid grid-cols-3 gap-2">
          <InlineField label="Exchange" value={form.exchange} onChange={v=>setForm(f=>({...f,exchange:v}))} placeholder="binance" />
          <InlineField label="Coin"     value={form.coin}     onChange={v=>setForm(f=>({...f,coin:v}))}     placeholder="USDT" />
          <InlineField label="Network"  value={form.network}  onChange={v=>setForm(f=>({...f,network:v}))}  placeholder="TRC20" />
          <InlineField label="Fee (coin amount)" value={form.fee_amount} onChange={v=>setForm(f=>({...f,fee_amount:v}))} placeholder="1.0" />
          <InlineField label="Fee (USD)"         value={form.fee_usd}    onChange={v=>setForm(f=>({...f,fee_usd:v}))}    placeholder="1.0" />
          <InlineField label="Min withdrawal"    value={form.min_amount} onChange={v=>setForm(f=>({...f,min_amount:v}))} placeholder="10.0" />
        </div>
        <StatusMsg ok={status?.ok} msg={status?.msg} />
        <button onClick={save} disabled={saving}
          className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
          {saving ? 'Saving...' : 'Save Fee'}
        </button>
      </div>
    </div>
  )
}

// ── Transfer Planner ──────────────────────────────────────────────────────────
function TransferPlannerSection() {
  const [form, setForm]       = useState({ from_exchange: '', to_exchange: '', coin: 'USDT', amount: '' })
  const [plan, setPlan]       = useState(null)
  const [planning, setPlanning] = useState(false)
  const [executing, setExecuting] = useState(false)
  const [result, setResult]   = useState(null)

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
      const r = await api(`/vault/transfer/execute?confirm=true`, {
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
        Plans the cheapest route for a cross-exchange transfer using stored wallet addresses and withdrawal fees.
        Requires API key for the source exchange (Vault → API Keys) and wallet address for the destination (Vault → Wallets).
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
                <div><span className="text-gray-500">Route:</span> <span className="text-gray-200 font-mono">{plan.from} → {plan.network} → {plan.to}</span></div>
                <div><span className="text-gray-500">Amount:</span> <span className="text-gray-200 font-mono">{plan.amount} {plan.coin}</span></div>
                <div><span className="text-gray-500">Network fee:</span> <span className="text-yellow-400 font-mono">{plan.fee_amount} {plan.coin} (≈${plan.fee_usd})</span></div>
                <div><span className="text-gray-500">Net received:</span> <span className="text-green-400 font-mono font-bold">{plan.net_amount} {plan.coin}</span></div>
                <div className="col-span-2"><span className="text-gray-500">Destination:</span> <span className="text-gray-400 font-mono text-[10px] break-all">{plan.destination}</span></div>
              </div>
              {plan.executable ? (
                <>
                  <div className="bg-red-900/20 border border-red-800/50 rounded p-2 text-xs text-red-300">
                    ⚠ {plan.note}
                  </div>
                  <button onClick={execute} disabled={executing}
                    className="text-xs px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded-lg disabled:opacity-50 font-semibold">
                    {executing ? '⟳ Executing...' : '🚀 Execute Transfer (Irreversible)'}
                  </button>
                </>
              ) : (
                <p className="text-xs text-red-400">Amount is below the minimum withdrawal for this network ({plan.min_amount} {plan.coin})</p>
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

// ── Main panel ────────────────────────────────────────────────────────────────
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

      {section === 'apikeys'    && <Card title="API Keys"          subtitle="Exchange credentials — encrypted at rest"><ApiKeysSection /></Card>}
      {section === 'wallets'    && <Card title="Wallet Addresses"  subtitle="Deposit addresses for cross-exchange transfers"><WalletsSection /></Card>}
      {section === 'fees'       && <Card title="Taker Fees"        subtitle="Used in all net profit calculations"><FeesSection /></Card>}
      {section === 'withdrawal' && <Card title="Withdrawal Fees"   subtitle="Per-exchange, per-coin, per-network transfer costs"><WithdrawalFeesSection /></Card>}
      {section === 'transfer'   && <Card title="Transfer Planner"  subtitle="Plan and execute cross-exchange transfers"><TransferPlannerSection /></Card>}
    </div>
  )
}
