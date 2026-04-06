import React, { useState, useCallback } from 'react'
import {
  usePolling, fetchCurrentConfig, reloadBrainConfig, reloadWorkersConfig,
  patchConfig, fetchSupportedExchanges, fetchActiveExchanges, updateExchange,
  testAlerts, testExchange,
} from '../utils/api'
import { Card, Spinner } from './ui'
import { TipIcon } from './Tooltip'

// ── Shared helpers ─────────────────────────────────────────────────────────────

function ReloadButton({ label, description, onReload, color = 'green', tooltip }) {
  const [loading, setLoading] = useState(false)
  const [result,  setResult]  = useState(null)
  const [error,   setError]   = useState(null)
  const handle = async () => {
    setLoading(true); setResult(null); setError(null)
    try   { setResult(await onReload()) }
    catch (e) { setError(e.response?.data?.detail ?? e.message) }
    finally   { setLoading(false) }
  }
  const btnCls = color === 'blue' ? 'bg-blue-700 hover:bg-blue-600' : 'bg-green-700 hover:bg-green-600'
  return (
    <div className="border border-gray-800 rounded-xl p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center">
            <p className="text-sm font-semibold text-gray-200">{label}</p>
            {tooltip && <TipIcon text={tooltip} pos="right" wide />}
          </div>
          <p className="text-xs text-gray-500 mt-0.5">{description}</p>
        </div>
        <button onClick={handle} disabled={loading}
          className={`shrink-0 text-xs px-4 py-2 rounded-lg text-white font-medium transition-colors ${btnCls} disabled:opacity-50`}>
          {loading ? '⟳ Reloading...' : '↺ Reload'}
        </button>
      </div>
      {result && <div className="mt-3 bg-green-900/20 border border-green-800 rounded-lg p-3 text-xs text-green-300">✅ {result.message}</div>}
      {error  && <div className="mt-3 bg-red-900/20 border border-red-800 rounded-lg p-3 text-xs text-red-300">⚠️ {error}</div>}
    </div>
  )
}

function EditableField({ label, section, fieldKey, value, type = 'number', tooltip, unit = '', readOnly = false }) {
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft]   = useState('')
  const [saving,  setSaving]  = useState(false)
  const [saved,   setSaved]   = useState(false)
  const start = () => { setDraft(String(value ?? '')); setEditing(true); setSaved(false) }
  const save  = async () => {
    setSaving(true)
    try {
      const parsed = type === 'int' ? parseInt(draft, 10) : type === 'number' ? parseFloat(draft) : draft
      await patchConfig(section, fieldKey, parsed)
      setSaved(true); setEditing(false)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }
  const display = Array.isArray(value) ? value.join(', ') : String(value ?? '—')
  return (
    <div className="flex justify-between items-center py-2 border-b border-gray-800 last:border-0 group">
      <span className="text-xs text-gray-500 w-48 shrink-0 flex items-center">
        {label}{tooltip && <TipIcon text={tooltip} pos="right" wide />}
      </span>
      {(!readOnly && editing) ? (
        <div className="flex items-center gap-1 flex-1 justify-end">
          <input type={type === 'text' ? 'text' : 'number'} value={draft}
            onChange={e => setDraft(e.target.value)} autoFocus
            onKeyDown={e => { if (e.key === 'Enter') save(); if (e.key === 'Escape') setEditing(false) }}
            className="bg-gray-800 border border-gray-600 rounded px-2 py-0.5 text-xs text-gray-100 w-32 font-mono focus:outline-none focus:border-blue-500" />
          {unit && <span className="text-xs text-gray-600">{unit}</span>}
          <button onClick={save} disabled={saving}
            className="text-xs px-2 py-0.5 bg-green-700 hover:bg-green-600 text-white rounded">{saving ? '...' : '✓'}</button>
          <button onClick={() => setEditing(false)} className="text-xs px-2 py-0.5 bg-gray-700 text-gray-300 rounded">✕</button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          {saved && <span className="text-green-400 text-xs">✓</span>}
          <span className="text-xs text-gray-300 font-mono break-all">
            {display}{unit && <span className="text-gray-600 ml-0.5">{unit}</span>}
          </span>
          {!readOnly && (
            <button onClick={start}
              className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-opacity">Edit</button>
          )}
        </div>
      )}
    </div>
  )
}
const ROField = (props) => <EditableField {...props} readOnly />
function SubHeader({ title }) {
  return <p className="text-xs text-gray-500 uppercase tracking-wider mt-4 mb-1 pt-3 border-t border-gray-800">{title}</p>
}

// ── Exchange Manager ───────────────────────────────────────────────────────────

function ExchangeTestBtn({ exchange }) {
  const [state, setState] = useState('idle')
  const [msg,   setMsg]   = useState('')
  const run = async () => {
    setState('testing')
    try {
      const r = await testExchange(exchange)
      setState(r.ok ? 'ok' : 'error'); setMsg(r.message ?? '')
    } catch (e) { setState('error'); setMsg(e.message) }
  }
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <button onClick={run} disabled={state === 'testing'}
        className="text-[10px] px-2 py-0.5 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded disabled:opacity-50">
        {state === 'testing' ? '⟳ Testing...' : '🔌 Test'}
      </button>
      {state === 'ok'    && <span className="text-[10px] text-green-400 truncate max-w-xs">✓ {msg}</span>}
      {state === 'error' && <span className="text-[10px] text-red-400 truncate max-w-xs">✗ {msg}</span>}
    </div>
  )
}

function AddExchangeModal({ allExchanges, active, onAdd, onClose }) {
  const activeIds = new Set(active.map(e => e.exchange))
  const [search,   setSearch]   = useState('')
  const [selected, setSelected] = useState(new Set())
  const [pairs,    setPairs]    = useState('BTC/USDT,ETH/USDT')
  const [saving,   setSaving]   = useState(false)
  const [error,    setError]    = useState(null)

  const PRESETS = [
    { label: 'Top 10 USDT', value: 'BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT,XRP/USDT,DOGE/USDT,AVAX/USDT,LINK/USDT,ADA/USDT,DOT/USDT' },
    { label: 'USDT + cross', value: 'BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,BTC/ETH,ETH/BNB,SOL/BTC' },
    { label: 'ALL USDT',    value: 'ALL' },
  ]

  const filtered = allExchanges.filter(e =>
    !activeIds.has(e.id) &&
    (e.id.includes(search.toLowerCase()) || e.name?.toLowerCase().includes(search.toLowerCase()))
  )

  const toggle = (id) => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll = () => setSelected(s => s.size === filtered.length ? new Set() : new Set(filtered.map(e => e.id)))

  const save = async () => {
    if (!selected.size) return
    setSaving(true); setError(null)
    try {
      await Promise.all([...selected].map(ex => updateExchange(ex, pairs, true)))
      onAdd(); onClose()
    } catch (e) { setError(e.response?.data?.detail ?? e.message) }
    finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 bg-black/75 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-5 w-full max-w-lg space-y-4 max-h-[90vh] flex flex-col">
        <div className="flex justify-between items-center shrink-0">
          <h3 className="text-sm font-bold text-white">Add Exchanges</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg">✕</button>
        </div>

        {/* Search */}
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search exchanges..."
          className="shrink-0 bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-blue-500 w-full" />

        {/* Exchange table */}
        <div className="flex-1 overflow-y-auto border border-gray-800 rounded-lg min-h-0">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-900 border-b border-gray-800">
              <tr>
                <th className="w-8 py-2 px-2">
                  <input type="checkbox" checked={selected.size === filtered.length && filtered.length > 0}
                    onChange={toggleAll} className="cursor-pointer" />
                </th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase">Exchange</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase hidden sm:table-cell">ID</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase">Test</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr><td colSpan={4} className="text-center py-6 text-gray-600">
                  {search ? 'No results' : 'All supported exchanges are already active'}
                </td></tr>
              )}
              {filtered.map(ex => (
                <tr key={ex.id} className={`border-b border-gray-800/40 cursor-pointer hover:bg-gray-800/30 ${selected.has(ex.id) ? 'bg-green-900/10' : ''}`}
                  onClick={() => toggle(ex.id)}>
                  <td className="py-1.5 px-2">
                    <input type="checkbox" checked={selected.has(ex.id)} onChange={() => toggle(ex.id)}
                      onClick={e => e.stopPropagation()} className="cursor-pointer" />
                  </td>
                  <td className="py-1.5 px-2 font-medium text-gray-200">{ex.name || ex.id}</td>
                  <td className="py-1.5 px-2 text-gray-500 font-mono hidden sm:table-cell">{ex.id}</td>
                  <td className="py-1.5 px-2" onClick={e => e.stopPropagation()}>
                    <ExchangeTestBtn exchange={ex.id} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pairs */}
        <div className="shrink-0 space-y-1.5">
          <label className="text-xs text-gray-500">Pairs for selected exchanges</label>
          <div className="flex flex-wrap gap-1">
            {PRESETS.map(p => (
              <button key={p.label} onClick={() => setPairs(p.value)}
                className="text-[10px] px-2 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded border border-gray-700">{p.label}</button>
            ))}
          </div>
          <input value={pairs} onChange={e => setPairs(e.target.value)}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500"
            placeholder="BTC/USDT,ETH/USDT or ALL" />
        </div>

        {error && <div className="shrink-0 text-xs text-red-400 bg-red-900/20 border border-red-800 rounded p-2">{error}</div>}

        <div className="flex gap-2 shrink-0">
          <button onClick={onClose} className="flex-1 text-xs py-2 bg-gray-800 text-gray-400 rounded-lg">Cancel</button>
          <button onClick={save} disabled={!selected.size || saving}
            className="flex-1 text-xs py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-40">
            {saving ? 'Adding...' : `Add ${selected.size} exchange${selected.size !== 1 ? 's' : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}

function ExchangeManager() {
  const { data: activeData,    loading, refresh } = usePolling(fetchActiveExchanges,    10000)
  const { data: supportedData, loading: sLoading } = usePolling(fetchSupportedExchanges, 120000)
  const [showAdd,   setShowAdd]   = useState(false)
  const [editEx,    setEditEx]    = useState(null)
  const [saving,    setSaving]    = useState(false)
  const [selected,  setSelected]  = useState(new Set())
  const [massState, setMassState] = useState('idle')

  const active    = activeData?.exchanges    ?? []
  const allEx     = supportedData?.exchanges ?? []

  const toggleSelect = (id) => setSelected(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll    = () => setSelected(s => s.size === active.length ? new Set() : new Set(active.map(e => e.exchange)))

  const handleRemove = async (ids) => {
    if (!confirm(`Remove ${ids.length} exchange(s)?`)) return
    await Promise.all(ids.map(id => updateExchange(id, '', false)))
    setSelected(new Set()); refresh()
  }

  const handleEditSave = async () => {
    if (!editEx) return
    setSaving(true)
    await updateExchange(editEx.exchange, editEx.pairs_raw, true)
    setSaving(false); setEditEx(null); refresh()
  }

  const massTest = async () => {
    setMassState('testing')
    const ids = [...selected]
    await Promise.all(ids.map(id => testExchange(id).catch(() => {})))
    setMassState('done')
    setTimeout(() => setMassState('idle'), 3000)
  }

  const dot = (ex) => ex.healthy > 0 ? 'bg-green-500' : ex.worker_count > 0 ? 'bg-yellow-500' : 'bg-gray-600'

  return (
    <div className="space-y-3">
      {/* Toolbar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span>{active.length} exchange{active.length !== 1 ? 's' : ''}</span>
          {selected.size > 0 && (
            <>
              <span className="text-gray-700">·</span>
              <span className="text-blue-400">{selected.size} selected</span>
              <button onClick={() => handleRemove([...selected])}
                className="px-2 py-0.5 bg-red-900/40 text-red-400 border border-red-800 rounded hover:bg-red-900/60">✕ Remove</button>
              <button onClick={massTest} disabled={massState === 'testing'}
                className="px-2 py-0.5 bg-gray-800 text-gray-400 border border-gray-700 rounded hover:bg-gray-700 disabled:opacity-50">
                {massState === 'testing' ? '⟳ Testing...' : massState === 'done' ? '✓ Done' : '🔌 Test all'}
              </button>
            </>
          )}
        </div>
        <button onClick={() => setShowAdd(true)}
          className="text-xs px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded-lg font-medium">
          + Add Exchange
        </button>
      </div>

      {/* Table */}
      {loading && active.length === 0 ? <Spinner /> : active.length === 0 ? (
        <div className="text-center py-8 text-gray-600 text-sm">No exchanges configured. Click + to add one.</div>
      ) : (
        <div className="border border-gray-800 rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-gray-900 border-b border-gray-800">
              <tr>
                <th className="w-8 py-2 px-3">
                  <input type="checkbox" checked={selected.size === active.length && active.length > 0}
                    onChange={toggleAll} className="cursor-pointer" />
                </th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase font-medium">Exchange</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase font-medium hidden sm:table-cell">Pairs</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase font-medium">Workers</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase font-medium">Status</th>
                <th className="text-left py-2 px-2 text-gray-500 uppercase font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {active.map(ex => (
                <tr key={ex.exchange} className={`border-b border-gray-800/40 hover:bg-gray-800/20 ${selected.has(ex.exchange) ? 'bg-blue-900/10' : ''}`}>
                  <td className="py-2 px-3">
                    <input type="checkbox" checked={selected.has(ex.exchange)}
                      onChange={() => toggleSelect(ex.exchange)} className="cursor-pointer" />
                  </td>
                  <td className="py-2 px-2">
                    <div className="flex items-center gap-2">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dot(ex)}`} />
                      <span className="font-semibold text-gray-200 capitalize">{ex.exchange}</span>
                      {ex.authenticated && <span className="text-[9px] px-1 py-px bg-yellow-900/40 border border-yellow-700/50 text-yellow-400 rounded">🔑</span>}
                    </div>
                  </td>
                  <td className="py-2 px-2 text-gray-500 hidden sm:table-cell">
                    <span className="font-mono truncate max-w-[180px] block" title={ex.pairs_raw}>
                      {ex.pairs_raw === 'ALL' ? 'ALL USDT'
                        : (ex.pairs_raw || '').split(',').slice(0,3).join(', ')
                          + ((ex.pairs_raw || '').split(',').length > 3 ? ` +${(ex.pairs_raw || '').split(',').length-3}` : '')}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-gray-400">{ex.worker_count}</td>
                  <td className="py-2 px-2">
                    <span className={`font-semibold ${ex.healthy > 0 ? 'text-green-400' : ex.worker_count > 0 ? 'text-yellow-400' : 'text-gray-600'}`}>
                      {ex.healthy > 0 ? 'Live' : ex.worker_count > 0 ? 'Starting' : 'Offline'}
                    </span>
                  </td>
                  <td className="py-2 px-2">
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => setEditEx(ex)}
                        className="text-[10px] px-1.5 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded">✏ Pairs</button>
                      <ExchangeTestBtn exchange={ex.exchange} />
                      <button onClick={() => handleRemove([ex.exchange])}
                        className="text-[10px] px-1.5 py-0.5 bg-red-900/30 hover:bg-red-900/50 text-red-400 rounded">✕</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Edit pairs modal */}
      {editEx && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-sm font-bold text-white capitalize">Edit {editEx.exchange} pairs</h3>
              <button onClick={() => setEditEx(null)} className="text-gray-500 text-lg">✕</button>
            </div>
            <textarea value={editEx.pairs_raw} rows={5}
              onChange={e => setEditEx({ ...editEx, pairs_raw: e.target.value })}
              className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 resize-none" />
            <div className="flex gap-2">
              <button onClick={() => setEditEx(null)} className="flex-1 text-xs py-2 bg-gray-800 text-gray-400 rounded-lg">Cancel</button>
              <button onClick={handleEditSave} disabled={saving}
                className="flex-1 text-xs py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-50">
                {saving ? 'Saving...' : 'Save Pairs'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showAdd && !sLoading && (
        <AddExchangeModal allExchanges={allEx} active={active} onAdd={refresh} onClose={() => setShowAdd(false)} />
      )}
      {showAdd && sLoading && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50">
          <div className="bg-gray-900 border border-gray-700 rounded-xl p-6 flex items-center gap-3">
            <Spinner /><span className="text-sm text-gray-300">Loading exchange list...</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Alerts section ─────────────────────────────────────────────────────────────

function ChannelTestBtn({ channel, label }) {
  const [state, setState] = useState('idle')
  const [msg,   setMsg]   = useState('')
  const run = async () => {
    setState('sending')
    try {
      const r = await fetch(`/api/alerts/test/${channel}`, { method: 'POST' }).then(x => x.json())
      setState(r.ok ? 'ok' : 'error'); setMsg(r.message ?? '')
    } catch (e) { setState('error'); setMsg(e.message) }
  }
  return (
    <div className="flex items-center gap-2 py-2 border-b border-gray-800 last:border-0">
      <span className="text-xs text-gray-400 w-24 shrink-0">{label}</span>
      <button onClick={run} disabled={state === 'sending'}
        className="text-xs px-3 py-1 bg-indigo-800 hover:bg-indigo-700 text-white rounded disabled:opacity-50">
        {state === 'sending' ? '⟳ Sending...' : '📣 Test'}
      </button>
      {state === 'ok'    && <span className="text-xs text-green-400 flex-1 truncate">✓ {msg}</span>}
      {state === 'error' && <span className="text-xs text-red-400 flex-1 truncate">✗ {msg}</span>}
    </div>
  )
}

// ── Sections ───────────────────────────────────────────────────────────────────

// ── Alerts Panel ──────────────────────────────────────────────────────────────

function EnvInstruction({ lines }) {
  return (
    <div className="mt-2 bg-gray-950 border border-gray-800 rounded p-2">
      <p className="text-[10px] text-gray-600 mb-1">Add to config/.env.local:</p>
      {lines.map(l => <p key={l} className="text-[10px] font-mono text-gray-400">{l}</p>)}
    </div>
  )
}

function ChannelCard({ icon, title, enabled, configured, children, channel }) {
  const [testState, setTestState] = useState('idle')
  const [testMsg,   setTestMsg]   = useState('')
  const [open, setOpen] = useState(false)

  const runTest = async (e) => {
    e.stopPropagation()
    setTestState('sending')
    try {
      const r = await fetch(`/api/alerts/test/${channel}`, { method: 'POST' }).then(x => x.json())
      setTestState(r.ok ? 'ok' : 'error')
      setTestMsg(r.message ?? '')
    } catch(e) { setTestState('error'); setTestMsg(e.message) }
  }

  return (
    <div className={`border rounded-xl overflow-hidden transition-colors ${enabled ? 'border-green-900/50' : 'border-gray-800'}`}>
      {/* Header row */}
      <div className="flex items-center gap-3 px-4 py-3 cursor-pointer hover:bg-gray-800/30"
        onClick={() => setOpen(o => !o)}>
        <span className={`w-2 h-2 rounded-full shrink-0 ${configured ? 'bg-green-500' : 'bg-gray-700'}`} />
        <span className="text-sm font-medium text-gray-200">{icon} {title}</span>
        <span className={`text-[10px] px-1.5 py-0.5 rounded ${configured ? 'bg-green-900/40 text-green-400 border border-green-800/50' : 'bg-gray-800 text-gray-600 border border-gray-700'}`}>
          {configured ? 'configured' : 'not configured'}
        </span>
        <div className="flex items-center gap-2 ml-auto" onClick={e => e.stopPropagation()}>
          <button onClick={runTest} disabled={testState === 'sending'}
            className="text-xs px-3 py-1 bg-indigo-800 hover:bg-indigo-700 text-white rounded disabled:opacity-50">
            {testState === 'sending' ? '⟳' : '📣 Test'}
          </button>
          {testState === 'ok'    && <span className="text-xs text-green-400 max-w-[120px] truncate">✓ {testMsg}</span>}
          {testState === 'error' && <span className="text-xs text-red-400 max-w-[120px] truncate">✗ {testMsg}</span>}
          <span className="text-gray-600 text-xs">{open ? '▲' : '▼'}</span>
        </div>
      </div>

      {/* Expanded config */}
      {open && (
        <div className="border-t border-gray-800 px-4 py-3 bg-gray-950/40">
          {children}
        </div>
      )}
    </div>
  )
}

function AlertsPanel({ al }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-gray-600 pb-1">
        Click any channel to expand its configuration. Credentials are stored in
        <code className="bg-gray-800 px-1 mx-1 rounded">.env.local</code> — never sent to the browser.
      </p>

      {/* ntfy */}
      <ChannelCard icon="📱" title="ntfy" channel="ntfy"
        enabled={al.ntfy_enabled} configured={al.ntfy_enabled && !!al.ntfy_topic}>
        <ROField label="Topic"   value={al.ntfy_topic || '—'} tooltip="NTFY_TOPIC" />
        <ROField label="Server"  value={al.ntfy_url}          tooltip="NTFY_URL (default: https://ntfy.sh)" />
        {!al.ntfy_topic && <EnvInstruction lines={['NTFY_TOPIC=arbx-alerts', 'NTFY_URL=https://ntfy.sh  # optional, for self-hosted']} />}
      </ChannelCard>

      {/* Slack */}
      <ChannelCard icon="💬" title="Slack" channel="slack"
        enabled={al.slack_enabled} configured={al.slack_configured}>
        <ROField label="Webhook" value={al.slack_configured ? '●●●● (set)' : '— not set'} tooltip="SLACK_WEBHOOK_URL" />
        {!al.slack_configured && <EnvInstruction lines={['SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...']} />}
      </ChannelCard>

      {/* Discord */}
      <ChannelCard icon="🎮" title="Discord" channel="discord"
        enabled={al.discord_enabled} configured={al.discord_configured}>
        <ROField label="Webhook" value={al.discord_configured ? '●●●● (set)' : '— not set'} tooltip="DISCORD_WEBHOOK_URL" />
        {!al.discord_configured && <EnvInstruction lines={['DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/ID/TOKEN']} />}
      </ChannelCard>

      {/* Telegram */}
      <ChannelCard icon="✈️" title="Telegram" channel="telegram"
        enabled={al.telegram_enabled} configured={al.telegram_configured}>
        <ROField label="Bot token" value={al.telegram_configured ? '●●●● (set)' : '— not set'} tooltip="TELEGRAM_BOT_TOKEN" />
        <ROField label="Chat ID"   value={al.telegram_chat_id || '— not set'}                  tooltip="TELEGRAM_CHAT_ID" />
        {!al.telegram_configured && (
          <EnvInstruction lines={[
            'TELEGRAM_BOT_TOKEN=123456:ABCdef...',
            'TELEGRAM_CHAT_ID=-100123456789   # group/channel ID',
          ]} />
        )}
      </ChannelCard>

      {/* Email */}
      <ChannelCard icon="📧" title="Email (SMTP)" channel="email"
        enabled={al.email_enabled} configured={al.email_configured}>
        <ROField label="SMTP host"  value={al.email_smtp_host  || '— not set'} tooltip="EMAIL_SMTP_HOST" />
        <ROField label="SMTP port"  value={al.email_smtp_port}                  tooltip="EMAIL_SMTP_PORT (default 587)" />
        <ROField label="TLS mode"   value={al.email_tls_mode   || 'starttls'}   tooltip="EMAIL_TLS_MODE: starttls (587) | ssl (465) | none (25)" />
        <ROField label="From"       value={al.email_from       || '— not set'} tooltip="EMAIL_FROM" />
        <ROField label="To"         value={al.email_to         || '— not set'} tooltip="EMAIL_TO" />
        <ROField label="Password"   value={al.email_configured ? '●●●● (set)' : '— not set'} tooltip="EMAIL_PASSWORD" />
        {!al.email_configured && (
          <EnvInstruction lines={[
            'EMAIL_SMTP_HOST=smtp.gmail.com',
            'EMAIL_SMTP_PORT=587',
            'EMAIL_TLS_MODE=starttls   # starttls | ssl | none',
            'EMAIL_FROM=you@gmail.com',
            'EMAIL_TO=alerts@yourmail.com',
            'EMAIL_PASSWORD=your-app-password',
          ]} />
        )}
        <p className="text-[10px] text-gray-600 mt-2">
          Gmail: use an App Password (not your login password). Enable 2FA first.
          <br/>Port 587 + starttls (most providers) · Port 465 + ssl · Port 25 + none (internal)
        </p>
      </ChannelCard>

      {/* Generic Webhook */}
      <ChannelCard icon="🔗" title="Webhook" channel="webhook"
        enabled={al.webhook_enabled} configured={al.webhook_configured}>
        <ROField label="URL" value={al.webhook_configured ? '●●●● (set)' : '— not set'} tooltip="WEBHOOK_URL — receives JSON POST with event data" />
        {!al.webhook_configured && <EnvInstruction lines={['WEBHOOK_URL=https://your-server.com/arbx-hook']} />}
      </ChannelCard>

      <p className="text-[10px] text-gray-600 pt-1">
        After adding credentials to .env.local, run <code className="bg-gray-800 px-1 rounded">make docker-down && make docker-rebuild</code> then test each channel.
      </p>
    </div>
  )
}


const SECTIONS = [
  { id: 'reload',    label: '↺ Reload' },
  { id: 'exchanges', label: '🌐 Exchanges' },
  { id: 'ports',     label: '🔌 Ports' },
  { id: 'workers',   label: '⚙ Workers' },
  { id: 'risk',      label: '🛡 Risk' },
  { id: 'decision',  label: '⚡ Decision' },
  { id: 'graph',     label: '🕸 Graph' },
  { id: 'analysis',  label: '🔬 Analysis' },
  { id: 'alerts',    label: '🔔 Alerts' },
  { id: 'cr9am',     label: '📐 9AM CR' },
  { id: 'brain',     label: '🧠 Brain' },
]

export default function ConfigReloadPanel() {
  const { data: cfg, loading } = usePolling(fetchCurrentConfig, 10000)
  const [section, setSection]  = useState('exchanges')

  if (loading) return <Card title="Config & Reload"><Spinner /></Card>

  const g  = cfg?.graph    ?? {}
  const w  = cfg?.workers  ?? {}
  const s  = cfg?.spawner  ?? {}
  const p  = cfg?.ports    ?? {}
  const a  = cfg?.analysis ?? {}
  const al = cfg?.alerts   ?? {}
  const cr = cfg?.cr_9am   ?? {}

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

      {section === 'reload' && (
        <Card title="Hot Reload" subtitle="Apply changes without restarting containers">
          <div className="space-y-3">
            <ReloadButton label="Reload Brain Config"
              description="Re-reads config.yaml + .env. Updates risk, decision, graph weights instantly."
              onReload={reloadBrainConfig} color="green"
              tooltip="Applies all .env changes immediately. Ports and Redis host require full restart." />
            <ReloadButton label="Reload Workers Config"
              description="Broadcasts a reload command to all connected workers via Redis."
              onReload={reloadWorkersConfig} color="blue"
              tooltip="Workers re-read PAIRS, TICK_INTERVAL_MS without restarting." />
          </div>
          <p className="text-xs text-gray-600 mt-4 pt-3 border-t border-gray-800">
            Always requires restart: BRAIN_API_PORT, BRAIN_METRICS_PORT, REDIS_HOST, POSTGRES_HOST.
          </p>
        </Card>
      )}

      {section === 'exchanges' && (
        <Card title="Exchange Manager" subtitle="Select rows for bulk actions — click ✏ to edit pairs">
          <ExchangeManager />
        </Card>
      )}

      {section === 'ports' && (
        <Card title="Ports" subtitle="Read-only — set in .env.local, require full restart">
          <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-lg p-3 text-xs text-yellow-400 mb-4">
            ⚠ Port changes require <code className="bg-gray-800 px-1 rounded">make docker-down && make docker-rebuild</code>
          </div>
          <ROField label="Brain API"    value={p.brain_api}     tooltip="FastAPI REST + WebSocket (BRAIN_API_PORT)" />
          <ROField label="Metrics"      value={p.brain_metrics}  tooltip="Prometheus scrape endpoint (BRAIN_METRICS_PORT)" />
          <ROField label="Frontend"     value={p.frontend}       tooltip="nginx / React dashboard (FRONTEND_PORT)" />
          <ROField label="Redis"        value={p.redis}          tooltip="Redis Streams (REDIS_PORT)" />
          <ROField label="PostgreSQL"   value={p.postgres}       tooltip="PostgreSQL database (POSTGRES_PORT)" />
        </Card>
      )}

      {section === 'workers' && (
        <Card title="Workers" subtitle="Pool and timing settings">
          <SubHeader title="Pool" />
          <ROField label="Max workers"        value={w.max_workers}          tooltip="MAX_WORKERS" />
          <ROField label="Pairs per worker"   value={w.pairs_worker_size}    tooltip="PAIRS_WORKER_SIZE" />
          <ROField label="Quote filter"       value={w.pairs_all_quote_filter} tooltip="PAIRS_ALL_QUOTE_FILTER" />
          <ROField label="Worker image"       value={w.worker_image}          tooltip="WORKER_IMAGE" />
          <SubHeader title="Timing" />
          <ROField label="Tick interval"      value={w.tick_interval_ms}     tooltip="TICK_INTERVAL_MS" unit="ms" />
          <ROField label="Heartbeat interval" value={w.heartbeat_interval_s}  tooltip="HEARTBEAT_INTERVAL_S" unit="s" />
          <ROField label="Balance interval"   value={w.balance_interval_s}   tooltip="BALANCE_INTERVAL_S" unit="s" />
          <SubHeader title="Auto-spawner" />
          <ROField label="Watch interval"     value={s.watch_interval_s}     tooltip="EXCHANGES_WATCH_INTERVAL" unit="s" />
          <ROField label="Spawn delay"        value={s.spawn_delay_s}        tooltip="EXCHANGES_SPAWN_DELAY" unit="s" />
          <ROField label="Startup wait"       value={s.startup_wait_s}       tooltip="EXCHANGES_STARTUP_WAIT" unit="s" />
        </Card>
      )}

      {section === 'risk' && (
        <Card title="Risk Manager" subtitle="Hover a field → click Edit to change live">
          <EditableField label="Max daily loss"     section="risk" fieldKey="max_daily_loss_usd"     value={cfg?.risk?.max_daily_loss_usd}     type="number" unit="USD" tooltip="MAX_DAILY_LOSS_USD — halts trading when hit" />
          <EditableField label="Max drawdown"       section="risk" fieldKey="max_drawdown_pct"       value={cfg?.risk?.max_drawdown_pct}       type="number" unit="%"   tooltip="MAX_DRAWDOWN_PCT — % drop from peak before halt" />
          <EditableField label="Max consec. losses" section="risk" fieldKey="max_consecutive_losses" value={cfg?.risk?.max_consecutive_losses} type="int"               tooltip="MAX_CONSECUTIVE_LOSSES" />
          <EditableField label="Max pair exposure"  section="risk" fieldKey="max_pair_exposure_usd"  value={cfg?.risk?.max_pair_exposure_usd}  type="number" unit="USD" tooltip="MAX_PAIR_EXPOSURE_USD" />
        </Card>
      )}

      {section === 'decision' && (
        <Card title="Decision Engine" subtitle="Hover a field → click Edit to change live">
          <EditableField label="CR min score"        section="decision" fieldKey="cr_min_score"          value={cfg?.decision?.cr_min_score}          type="number"           tooltip="CR_MIN_SCORE" />
          <EditableField label="CR min R:R"          section="decision" fieldKey="cr_min_rr"             value={cfg?.decision?.cr_min_rr}             type="number"           tooltip="CR_MIN_RR" />
          <EditableField label="Max capital / trade" section="decision" fieldKey="max_capital_per_trade" value={cfg?.decision?.max_capital_per_trade} type="number" unit="USD" tooltip="MAX_CAPITAL_PER_TRADE" />
          <EditableField label="Cooldown"            section="decision" fieldKey="cooldown_seconds"      value={cfg?.decision?.cooldown_seconds}      type="int"    unit="s"   tooltip="COOLDOWN_SECONDS" />
          <EditableField label="Max concurrent"      section="decision" fieldKey="max_concurrent_orders" value={cfg?.decision?.max_concurrent_orders} type="int"              tooltip="MAX_CONCURRENT_ORDERS" />
        </Card>
      )}

      {section === 'graph' && (
        <Card title="Graph Arbitrage" subtitle="Hover a field → click Edit to change live">
          <SubHeader title="Engine" />
          <ROField   label="Algorithm"     value={g.algorithm}         tooltip="GRAPH_ALGORITHM" />
          <ROField   label="FW interval"   value={g.fw_interval_s}     tooltip="GRAPH_FW_INTERVAL_S" unit="s" />
          <EditableField label="Min profit"  section="graph" fieldKey="min_profit_pct"   value={g.min_profit_pct}   type="number" unit="%" tooltip="GRAPH_MIN_SPREAD_PCT" />
          <EditableField label="Max hops"    section="graph" fieldKey="max_hops"          value={g.max_hops}          type="int"           tooltip="GRAPH_MAX_HOPS" />
          <EditableField label="Min hops"    section="graph" fieldKey="min_hops"          value={g.min_hops}          type="int"           tooltip="GRAPH_MIN_HOPS" />
          <EditableField label="Stale edge"  section="graph" fieldKey="stale_threshold_s" value={g.stale_edge_s}      type="int"  unit="s" tooltip="GRAPH_STALE_EDGE_S" />
          <SubHeader title="Assets" />
          <ROField   label="Start asset"   value={g.start_asset}       tooltip="GRAPH_START_ASSET" />
          <ROField   label="Hub assets"    value={g.hub_assets}        tooltip="GRAPH_HUB_ASSETS" />
          <EditableField label="Capital"   section="graph" fieldKey="capital_usd"      value={g.capital_usd}      type="number" unit="USD" tooltip="GRAPH_CAPITAL_USD" />
          <EditableField label="Max gas"   section="graph" fieldKey="dex_max_gas_usd"  value={g.dex_max_gas_usd}  type="number" unit="USD" tooltip="UNISWAP_MAX_GAS_USD" />
          <SubHeader title="Taker fees (%)" />
          {['binance','kraken','bybit','mexc','kucoin','gateio','bitmart','htx','okx','bitget','phemex','uniswap','coinbase','curve'].map(ex => (
            <EditableField key={ex} label={ex} section="graph" fieldKey={`fee_${ex}_pct`}
              value={g[`fee_${ex}_pct`]} type="number" unit="%" tooltip={`FEE_${ex.toUpperCase()}_PCT`} />
          ))}
        </Card>
      )}

      {section === 'analysis' && (
        <Card title="Analysis" subtitle="Plugin whitelist and data quality">
          <ROField label="Analysis pairs"      value={a.analysis_pairs || '(all pairs)'} tooltip="ANALYSIS_PAIRS" />
          <ROField label="Outlier threshold"   value={`${a.price_outlier_threshold}×`}   tooltip="PRICE_OUTLIER_THRESHOLD" />
          <p className="text-xs text-gray-600 mt-3 pt-3 border-t border-gray-800">Edit in .env.local → make docker-rebuild.</p>
        </Card>
      )}

      {section === 'alerts' && (
        <div className="space-y-3">
          <AlertsPanel al={al} />
        </div>
      )}

      {section === 'cr9am' && (
        <Card title="9AM CR Model" subtitle="CRT methodology">
          <ROField   label="Timezone"          value={cr.timezone}         tooltip="Session timezone for 1AM/5AM/9AM detection" />
          <ROField   label="Active window"     value={`${cr.active_from}:00–${cr.active_to}:00`} tooltip="Hours when CR plugin is active" />
          <EditableField label="Min score"     section="cr_9am" fieldKey="min_setup_score" value={cr.min_setup_score} type="number" tooltip="Minimum quality score to emit a CR signal" />
          <ROField   label="Reversal range"    value={cr.reversal_range}   tooltip="CR_REVERSAL_RANGE" />
          <ROField   label="Continuation"      value={cr.continuation_range} tooltip="CR_CONTINUATION_RANGE" />
          <ROField   label="Require BOS"       value={String(cr.require_bos)} tooltip="CR_REQUIRE_BOS" />
          <ROField   label="Require FVG"       value={String(cr.require_fvg)} tooltip="CR_REQUIRE_FVG" />
          <ROField   label="Pairs"             value={cr.pairs}            tooltip="Pairs monitored by the CR plugin" />
        </Card>
      )}

      {section === 'brain' && (
        <Card title="Brain" subtitle="Read-only — restart required to change">
          <ROField label="Version"         value={cfg?.version}         tooltip="VERSION file" />
          <ROField label="Trading mode"    value={cfg?.trading_mode}    tooltip="disabled / simulate / live" />
          <ROField label="Dry run"         value={String(cfg?.dry_run)} tooltip="DRY_RUN" />
          <ROField label="Log level"       value={cfg?.log_level}       tooltip="LOG_LEVEL" />
          <ROField label="Heartbeat TTL"   value={`${cfg?.heartbeat_ttl}s`}     tooltip="HEARTBEAT_TTL" />
          <ROField label="Stale threshold" value={`${cfg?.stale_threshold_s}s`} tooltip="stale_data_threshold_s" />
        </Card>
      )}
    </div>
  )
}
