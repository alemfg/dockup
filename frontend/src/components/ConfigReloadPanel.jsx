import React, { useState } from 'react'
import {
  usePolling, fetchCurrentConfig, reloadBrainConfig, reloadWorkersConfig,
  patchConfig, fetchSupportedExchanges, fetchActiveExchanges, updateExchange,
  testAlerts, testExchange,
} from '../utils/api'
import { Card, Spinner } from './ui'
import { TipIcon } from './Tooltip'

// ── Shared UI helpers ─────────────────────────────────────────────────────────

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

// Editable field — hover to reveal Edit button, inline input on click
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
              className="opacity-0 group-hover:opacity-100 text-xs px-1.5 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded transition-opacity">
              Edit
            </button>
          )}
        </div>
      )}
    </div>
  )
}

const ROField = (props) => <EditableField {...props} readOnly />

// Section sub-header
function SubHeader({ title }) {
  return <p className="text-xs text-gray-500 uppercase tracking-wider mt-4 mb-1 pt-3 border-t border-gray-800 first:border-0 first:mt-0 first:pt-0">{title}</p>
}

// ── Alert test button ─────────────────────────────────────────────────────────

function AlertTestButton() {
  const [state,   setState]  = useState('idle')   // idle | sending | ok | error
  const [message, setMessage] = useState('')

  const run = async () => {
    setState('sending')
    try {
      const r = await testAlerts()
      setState(r.status === 'error' || r.status === 'no_channels' ? 'error' : 'ok')
      setMessage(r.message ?? '')
    } catch (e) {
      setState('error')
      setMessage(e.message)
    }
  }

  return (
    <div className="mt-4 pt-3 border-t border-gray-800">
      <div className="flex items-center gap-3">
        <button onClick={run} disabled={state === 'sending'}
          className="text-xs px-4 py-2 bg-indigo-700 hover:bg-indigo-600 text-white rounded-lg font-medium disabled:opacity-50 transition-colors">
          {state === 'sending' ? '⟳ Sending...' : '📣 Send Test Alert'}
        </button>
        {state === 'ok'    && <span className="text-xs text-green-400">✓ {message}</span>}
        {state === 'error' && <span className="text-xs text-red-400">✗ {message}</span>}
      </div>
      <p className="text-xs text-gray-600 mt-1.5">
        Sends a test notification through all configured channels.
      </p>
    </div>
  )
}

// ── Exchange test button ───────────────────────────────────────────────────────

function ExchangeTestButton({ exchange }) {
  const [state,   setState]  = useState('idle')
  const [message, setMessage] = useState('')

  const run = async () => {
    if (!exchange) return
    setState('testing')
    try {
      const r = await testExchange(exchange)
      setState(r.ok ? 'ok' : 'error')
      setMessage(r.message ?? '')
    } catch (e) {
      setState('error')
      setMessage(e.message)
    }
  }

  if (!exchange) return null

  return (
    <div className="flex items-center gap-2 mt-1">
      <button onClick={run} disabled={state === 'testing'}
        className="text-xs px-3 py-1 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded font-medium disabled:opacity-50 transition-colors">
        {state === 'testing' ? '⟳ Testing...' : '🔌 Test connection'}
      </button>
      {state === 'ok'    && <span className="text-xs text-green-400">✓ {message}</span>}
      {state === 'error' && <span className="text-xs text-red-400">✗ {message}</span>}
    </div>
  )
}

// ── Exchange Manager ───────────────────────────────────────────────────────────

function AddExchangeModal({ supported, active, onAdd, onClose }) {
  const activeIds = active.map(e => e.exchange)
  const available = supported.filter(e => !activeIds.includes(e))
  const [selected, setSelected] = useState('')
  const [pairs,    setPairs]    = useState('BTC/USDT,ETH/USDT')
  const [saving,   setSaving]   = useState(false)
  const [error,    setError]    = useState(null)
  const PRESETS = [
    { label: 'Top 10 USDT', value: 'BTC/USDT,ETH/USDT,BNB/USDT,SOL/USDT,XRP/USDT,DOGE/USDT,AVAX/USDT,LINK/USDT,ADA/USDT,DOT/USDT' },
    { label: 'USDT + cross', value: 'BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,BTC/ETH,ETH/BNB,SOL/BTC' },
    { label: 'ALL USDT', value: 'ALL' },
  ]
  const save = async () => {
    if (!selected) return
    setSaving(true); setError(null)
    try { await updateExchange(selected, pairs, true); onAdd(); onClose() }
    catch (e) { setError(e.response?.data?.detail ?? e.message) }
    finally { setSaving(false) }
  }
  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md space-y-4">
        <div className="flex justify-between items-center">
          <h3 className="text-sm font-bold text-white">Add Exchange</h3>
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 text-lg">✕</button>
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Exchange</label>
          <div className="grid grid-cols-3 gap-1.5 max-h-48 overflow-y-auto pr-1">
            {available.map(ex => (
              <button key={ex} onClick={() => setSelected(ex)}
                className={`text-xs px-2 py-1.5 rounded capitalize border transition-colors
                  ${selected === ex ? 'bg-green-700 border-green-600 text-white' : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600'}`}>
                {ex}
              </button>
            ))}
            {available.length === 0 && <p className="col-span-3 text-xs text-gray-600 text-center py-3">All supported exchanges already active.</p>}
          </div>
          <ExchangeTestButton exchange={selected} />
        </div>
        <div>
          <label className="text-xs text-gray-500 mb-1 block">Pairs</label>
          <div className="flex flex-wrap gap-1 mb-2">
            {PRESETS.map(p => (
              <button key={p.label} onClick={() => setPairs(p.value)}
                className="text-[10px] px-2 py-0.5 bg-gray-800 hover:bg-gray-700 text-gray-400 rounded border border-gray-700">{p.label}</button>
            ))}
          </div>
          <textarea value={pairs} onChange={e => setPairs(e.target.value)} rows={3}
            className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 resize-none"
            placeholder="BTC/USDT,ETH/USDT or ALL" />
          <p className="text-[10px] text-gray-600 mt-1">Comma-separated pairs, or ALL to stream all USDT pairs.</p>
        </div>
        {error && <div className="text-xs text-red-400 bg-red-900/20 border border-red-800 rounded p-2">{error}</div>}
        <div className="flex gap-2 pt-1">
          <button onClick={onClose} className="flex-1 text-xs py-2 bg-gray-800 text-gray-400 rounded-lg">Cancel</button>
          <button onClick={save} disabled={!selected || saving}
            className="flex-1 text-xs py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg disabled:opacity-40">
            {saving ? 'Adding...' : `Add ${selected || 'Exchange'}`}
          </button>
        </div>
      </div>
    </div>
  )
}

function ExchangeCard({ exchange, onRemove, onEdit }) {
  const dot = exchange.healthy > 0 ? 'bg-green-500' : exchange.worker_count > 0 ? 'bg-yellow-500' : 'bg-gray-600'
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full shrink-0 ${dot}`} />
          <span className="text-sm font-semibold text-white capitalize">{exchange.exchange}</span>
          {exchange.authenticated && <span className="text-[10px] px-1.5 py-0.5 bg-yellow-900/40 border border-yellow-700/50 text-yellow-400 rounded">🔑 API</span>}
        </div>
        <button onClick={() => onRemove(exchange.exchange)} className="text-gray-700 hover:text-red-400 text-xs transition-colors">✕</button>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div><div className="text-[10px] text-gray-600">Workers</div><div className="text-sm font-bold text-gray-300">{exchange.worker_count}</div></div>
        <div><div className="text-[10px] text-gray-600">Pairs</div><div className="text-sm font-bold text-gray-300">{exchange.pair_count || '?'}</div></div>
        <div>
          <div className="text-[10px] text-gray-600">Status</div>
          <div className={`text-xs font-semibold ${exchange.healthy > 0 ? 'text-green-400' : 'text-gray-500'}`}>
            {exchange.healthy > 0 ? 'Live' : exchange.worker_count > 0 ? 'Connecting' : 'Offline'}
          </div>
        </div>
      </div>
      {exchange.pairs_raw && (
        <div className="text-[10px] text-gray-600 font-mono truncate" title={exchange.pairs_raw}>
          {exchange.pairs_raw === 'ALL' ? 'ALL USDT pairs'
            : exchange.pairs_raw.split(',').slice(0, 4).join(', ')
              + (exchange.pairs_raw.split(',').length > 4 ? ` +${exchange.pairs_raw.split(',').length - 4}` : '')}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button onClick={() => onEdit(exchange)} className="text-[10px] text-gray-600 hover:text-gray-400 transition-colors">✏ Edit pairs</button>
        <span className="text-gray-800">·</span>
        <ExchangeTestButton exchange={exchange.exchange} />
      </div>
    </div>
  )
}

function ExchangeManager() {
  const { data: activeData, loading, refresh } = usePolling(fetchActiveExchanges, 10000)
  const { data: supportedData }                = usePolling(fetchSupportedExchanges, 60000)
  const [showAdd, setShowAdd] = useState(false)
  const [editEx,  setEditEx]  = useState(null)
  const [saving,  setSaving]  = useState(false)

  const active    = activeData?.exchanges    ?? []
  const supported = supportedData?.exchanges ?? []

  const handleRemove = async (ex) => {
    if (!confirm(`Remove ${ex}? Workers stop on next reconcile.`)) return
    await updateExchange(ex, '', false); refresh()
  }
  const handleEditSave = async () => {
    if (!editEx) return
    setSaving(true)
    await updateExchange(editEx.exchange, editEx.pairs_raw, true)
    setSaving(false); setEditEx(null); refresh()
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-500">{active.length} active exchange{active.length !== 1 ? 's' : ''}</p>
        <button onClick={() => setShowAdd(true)}
          className="text-xs px-3 py-1.5 bg-green-700 hover:bg-green-600 text-white rounded-lg font-medium">
          + Add Exchange
        </button>
      </div>
      {loading && active.length === 0 ? <Spinner /> : active.length === 0 ? (
        <div className="text-center py-8 text-gray-600 text-sm">No exchanges configured. Click + to add one.</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {active.map(ex => <ExchangeCard key={ex.exchange} exchange={ex} onRemove={handleRemove} onEdit={setEditEx} />)}
        </div>
      )}

      {/* Edit pairs modal */}
      {editEx && (
        <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-md space-y-4">
            <div className="flex justify-between items-center">
              <h3 className="text-sm font-bold text-white capitalize">Edit {editEx.exchange} pairs</h3>
              <button onClick={() => setEditEx(null)} className="text-gray-500 hover:text-gray-300 text-lg">✕</button>
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Pairs (comma-separated or ALL)</label>
              <textarea value={editEx.pairs_raw} onChange={e => setEditEx({ ...editEx, pairs_raw: e.target.value })} rows={5}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200 font-mono focus:outline-none focus:border-blue-500 resize-none" />
            </div>
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
      {showAdd && <AddExchangeModal supported={supported} active={active} onAdd={refresh} onClose={() => setShowAdd(false)} />}
    </div>
  )
}

// ── Section definitions ────────────────────────────────────────────────────────

const SECTIONS = [
  { id: 'reload',    label: '↺ Hot Reload' },
  { id: 'exchanges', label: '🌐 Exchanges' },
  { id: 'ports',     label: '🔌 Ports' },
  { id: 'workers',   label: '⚙ Workers' },
  { id: 'risk',      label: '🛡 Risk' },
  { id: 'decision',  label: '⚡ Decision' },
  { id: 'graph',     label: '🕸 Graph Arb' },
  { id: 'analysis',  label: '🔬 Analysis' },
  { id: 'alerts',    label: '🔔 Alerts' },
  { id: 'cr9am',     label: '📐 9AM CR' },
  { id: 'brain',     label: '🧠 Brain' },
]

// ── Main panel ─────────────────────────────────────────────────────────────────

export default function ConfigReloadPanel() {
  const { data: cfg, loading } = usePolling(fetchCurrentConfig, 10000)
  const [section, setSection]  = useState('exchanges')

  if (loading) return <Card title="Config & Reload"><Spinner /></Card>

  const g = cfg?.graph     ?? {}
  const w = cfg?.workers   ?? {}
  const s = cfg?.spawner   ?? {}
  const p = cfg?.ports     ?? {}
  const a = cfg?.analysis  ?? {}
  const al = cfg?.alerts   ?? {}
  const cr = cfg?.cr_9am   ?? {}

  return (
    <div className="space-y-3">
      {/* Section tabs — wrapping */}
      <div className="flex gap-1 flex-wrap">
        {SECTIONS.map(({ id, label }) => (
          <button key={id} onClick={() => setSection(id)}
            className={`text-xs px-3 py-1.5 rounded transition-colors
              ${section === id ? 'bg-indigo-700 text-white font-medium' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {label}
          </button>
        ))}
      </div>

      {/* ── Hot Reload ──────────────────────────────────────────────────── */}
      {section === 'reload' && (
        <Card title="Hot Reload" subtitle="Apply changes without restarting containers">
          <div className="space-y-3">
            <ReloadButton label="Reload Brain Config"
              description="Re-reads config.yaml + .env. Updates risk, decision, graph, analysis weights instantly."
              onReload={reloadBrainConfig} color="green"
              tooltip="Applies all config.yaml AND .env changes. Ports and Redis host require full restart." />
            <ReloadButton label="Reload Workers Config"
              description="Broadcasts a reload command to all connected workers via Redis Streams."
              onReload={reloadWorkersConfig} color="blue"
              tooltip="Sends soft reload to every live worker. Workers re-read PAIRS, TICK_INTERVAL_MS without restarting." />
          </div>
          <p className="text-xs text-gray-600 mt-4 pt-3 border-t border-gray-800">
            Always requires restart: BRAIN_API_PORT, BRAIN_METRICS_PORT, REDIS_HOST, POSTGRES_HOST.
          </p>
        </Card>
      )}

      {/* ── Exchanges ───────────────────────────────────────────────────── */}
      {section === 'exchanges' && (
        <Card title="Exchange Manager" subtitle="Active exchanges — click + to add, ✕ to remove, ✏ to edit pairs">
          <ExchangeManager />
        </Card>
      )}

      {/* ── Ports ───────────────────────────────────────────────────────── */}
      {section === 'ports' && (
        <Card title="Ports" subtitle="Read-only — set in .env.local, require full restart to change">
          <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-lg p-3 text-xs text-yellow-400 mb-4">
            ⚠ Port changes require <code className="bg-gray-800 px-1 rounded">make docker-down && make docker-rebuild</code> to take effect.
          </div>
          <ROField label="Brain API port"     value={p.brain_api}     tooltip="FastAPI REST + WebSocket (BRAIN_API_PORT)" />
          <ROField label="Metrics port"       value={p.brain_metrics}  tooltip="Prometheus scrape endpoint (BRAIN_METRICS_PORT)" />
          <ROField label="Frontend port"      value={p.frontend}       tooltip="nginx serving React dashboard (FRONTEND_PORT)" />
          <ROField label="Redis port"         value={p.redis}          tooltip="Redis Streams (REDIS_PORT)" />
          <ROField label="PostgreSQL port"    value={p.postgres}       tooltip="PostgreSQL database (POSTGRES_PORT)" />
          <p className="text-xs text-gray-600 mt-3 pt-3 border-t border-gray-800">
            To change ports, add them to <code className="bg-gray-800 px-1 rounded">config/.env.local</code> then rebuild.
          </p>
        </Card>
      )}

      {/* ── Workers ─────────────────────────────────────────────────────── */}
      {section === 'workers' && cfg && (
        <Card title="Workers" subtitle="Worker pool and auto-spawn settings">
          <SubHeader title="Pool" />
          <ROField label="Max workers"         value={w.max_workers}         tooltip="Maximum worker containers worker_manager will spawn (MAX_WORKERS)" />
          <ROField label="Pairs per worker"    value={w.pairs_worker_size}   tooltip="Max pairs per worker. Larger exchanges are split across multiple workers (PAIRS_WORKER_SIZE)" />
          <ROField label="Quote filter"        value={w.pairs_all_quote_filter} tooltip="When PAIRS=ALL: only include pairs with these quote currencies (PAIRS_ALL_QUOTE_FILTER)" />
          <ROField label="Worker image"        value={w.worker_image}         tooltip="Docker image for spawned workers (WORKER_IMAGE)" />
          <SubHeader title="Tick & Heartbeat" />
          <ROField label="Tick interval"       value={w.tick_interval_ms}    tooltip="Milliseconds between price fetches per pair (TICK_INTERVAL_MS)" unit="ms" />
          <ROField label="Heartbeat interval"  value={w.heartbeat_interval_s} tooltip="Seconds between worker heartbeats (HEARTBEAT_INTERVAL_S)" unit="s" />
          <ROField label="Balance interval"    value={w.balance_interval_s}  tooltip="Seconds between balance fetches — requires API key (BALANCE_INTERVAL_S)" unit="s" />
          <SubHeader title="Auto-spawner timing" />
          <ROField label="Watch interval"      value={s.watch_interval_s}    tooltip="Seconds between fleet health checks and re-spawn attempts (EXCHANGES_WATCH_INTERVAL)" unit="s" />
          <ROField label="Spawn delay"         value={s.spawn_delay_s}       tooltip="Seconds between individual SPAWN messages to avoid flooding (EXCHANGES_SPAWN_DELAY)" unit="s" />
          <ROField label="Startup wait"        value={s.startup_wait_s}      tooltip="Seconds brain waits for worker_manager before sending first SPAWNs (EXCHANGES_STARTUP_WAIT)" unit="s" />
          <p className="text-xs text-gray-600 mt-3 pt-3 border-t border-gray-800">
            These settings require adding to <code className="bg-gray-800 px-1 rounded">.env.local</code> + worker container restart to change.
          </p>
        </Card>
      )}

      {/* ── Risk ────────────────────────────────────────────────────────── */}
      {section === 'risk' && cfg && (
        <Card title="Risk Manager" subtitle="Circuit breakers — hover a field and click Edit to change live">
          <EditableField label="Max daily loss"      section="risk" fieldKey="max_daily_loss_usd"     value={cfg.risk?.max_daily_loss_usd}     type="number" unit="USD" tooltip="Total realised losses today before all trading halts. Resets at midnight UTC." />
          <EditableField label="Max drawdown"        section="risk" fieldKey="max_drawdown_pct"       value={cfg.risk?.max_drawdown_pct}       type="number" unit="%"   tooltip="Portfolio drawdown from peak before halt. 10 = halt when down 10% from high." />
          <EditableField label="Max consec. losses"  section="risk" fieldKey="max_consecutive_losses" value={cfg.risk?.max_consecutive_losses} type="int"               tooltip="Halt after this many losing trades in a row. Resets when a trade closes green." />
          <EditableField label="Max pair exposure"   section="risk" fieldKey="max_pair_exposure_usd"  value={cfg.risk?.max_pair_exposure_usd}  type="number" unit="USD"  tooltip="Maximum USD exposure per pair across all open positions. (max_pair_exposure_usd)" />
        </Card>
      )}

      {/* ── Decision ────────────────────────────────────────────────────── */}
      {section === 'decision' && cfg && (
        <Card title="Decision Engine" subtitle="Order generation rules — hover a field and click Edit to change live">
          <EditableField label="CR min score"        section="decision" fieldKey="cr_min_score"          value={cfg.decision?.cr_min_score}          type="number"           tooltip="Minimum signal quality score (0–1) before a 9AM CR order is created." />
          <EditableField label="CR min R:R"          section="decision" fieldKey="cr_min_rr"             value={cfg.decision?.cr_min_rr}             type="number"           tooltip="Minimum Risk:Reward ratio. 1.5 = TP must be 1.5× the stop distance." />
          <EditableField label="Max capital / trade" section="decision" fieldKey="max_capital_per_trade" value={cfg.decision?.max_capital_per_trade} type="number" unit="USD" tooltip="Hard cap on USD value per trade." />
          <EditableField label="Cooldown"            section="decision" fieldKey="cooldown_seconds"      value={cfg.decision?.cooldown_seconds}      type="int"    unit="s"   tooltip="Minimum seconds between two orders on the same pair." />
          <EditableField label="Max concurrent"      section="decision" fieldKey="max_concurrent_orders" value={cfg.decision?.max_concurrent_orders} type="int"              tooltip="Maximum simultaneous open positions." />
        </Card>
      )}

      {/* ── Graph Arb ───────────────────────────────────────────────────── */}
      {section === 'graph' && (
        <Card title="Graph Arbitrage" subtitle="Bellman-Ford / Floyd-Warshall — editable fields apply immediately">
          <SubHeader title="Engine" />
          <ROField   label="Algorithm"         value={g.algorithm}         tooltip="Primary: bellman_ford every ~5s. floyd_warshall cross-check every FW interval." />
          <ROField   label="FW interval"       value={g.fw_interval_s}     tooltip="Seconds between Floyd-Warshall cross-checks (GRAPH_FW_INTERVAL_S)" unit="s" />
          <EditableField label="Min profit"    section="graph" fieldKey="min_profit_pct"    value={g.min_profit_pct}    type="number" unit="%" tooltip="Net profit floor after fees. Paths below this are not reported." />
          <EditableField label="Max hops"      section="graph" fieldKey="max_hops"           value={g.max_hops}           type="int"           tooltip="Maximum edges in a cycle. 3=triangular, 5=exotic." />
          <EditableField label="Min hops"      section="graph" fieldKey="min_hops"           value={g.min_hops}           type="int"           tooltip="Minimum edges — 3 avoids trivial A→B→A cycles." />
          <EditableField label="Stale edge"    section="graph" fieldKey="stale_threshold_s"  value={g.stale_edge_s}       type="int"  unit="s" tooltip="Exclude edges with prices older than this from path-finding." />
          <SubHeader title="Assets" />
          <ROField   label="Start asset"       value={g.start_asset}       tooltip="Asset cycles must start and end with (GRAPH_START_ASSET)" />
          <ROField   label="Hub assets"        value={g.hub_assets}        tooltip="Central nodes in the graph — pairs must connect through these (GRAPH_HUB_ASSETS)" />
          <EditableField label="Capital USD"   section="graph" fieldKey="capital_usd"        value={g.capital_usd}        type="number" unit="USD" tooltip="Simulated capital for profit calculation (GRAPH_CAPITAL_USD)" />
          <SubHeader title="DEX" />
          <EditableField label="Max gas USD"   section="graph" fieldKey="dex_max_gas_usd"    value={g.dex_max_gas_usd}    type="number" unit="USD" tooltip="Skip DEX paths if estimated gas exceeds this (UNISWAP_MAX_GAS_USD)" />
          <SubHeader title="Taker fees (%)" />
          {['binance','kraken','bybit','mexc','kucoin','gateio','bitmart','htx','okx','bitget','phemex','uniswap','sushiswap','curve'].map(ex => (
            <EditableField key={ex} label={ex}
              section="graph" fieldKey={`fee_${ex}_pct`}
              value={g[`fee_${ex}_pct`]}
              type="number" unit="%" tooltip={`Taker fee % for ${ex}. Check your VIP tier — lower fees improve net profit calculations. (FEE_${ex.toUpperCase()}_PCT)`} />
          ))}
        </Card>
      )}

      {/* ── Analysis ────────────────────────────────────────────────────── */}
      {section === 'analysis' && (
        <Card title="Analysis" subtitle="Plugin whitelist and data quality settings">
          <SubHeader title="Plugin Whitelist" />
          <ROField label="Analysis pairs"         value={a.analysis_pairs || '(all pairs)'}    tooltip="Pairs that run RSI/MACD/Bollinger/CR9AM plugins. Empty = all pairs (CPU intensive). (ANALYSIS_PAIRS)" />
          <SubHeader title="Price Data Quality" />
          <ROField label="Outlier threshold"      value={`${a.price_outlier_threshold}×`}       tooltip="Prices deviating more than this multiple from the median are rejected as unit mismatches. (PRICE_OUTLIER_THRESHOLD)" />
          <p className="text-xs text-gray-600 mt-3 pt-3 border-t border-gray-800">
            These require editing <code className="bg-gray-800 px-1 rounded">.env.local</code> and restarting the brain.
          </p>
        </Card>
      )}

      {/* ── Alerts ──────────────────────────────────────────────────────── */}
      {section === 'alerts' && (
        <Card title="Alerts" subtitle="Notification channels — URLs stored in .env.local (never shown here)">
          <ROField label="ntfy enabled"      value={String(al.ntfy_enabled)}    tooltip="Send alerts to ntfy.sh push service (NTFY_URL + NTFY_TOPIC in .env.local)" />
          <ROField label="ntfy topic"        value={al.ntfy_topic || '—'}       tooltip="ntfy topic name (NTFY_TOPIC)" />
          <ROField label="Slack enabled"     value={String(al.slack_enabled)}   tooltip="Send alerts to Slack webhook (SLACK_WEBHOOK_URL in .env.local)" />
          <ROField label="Webhook enabled"   value={String(al.webhook_enabled)} tooltip="Send alerts to generic webhook (WEBHOOK_URL in .env.local)" />
          <p className="text-xs text-gray-600 mt-3 pt-3 border-t border-gray-800">
            Add webhook URLs to <code className="bg-gray-800 px-1 rounded">.env.local</code> — they are not displayed here for security.
          </p>
          <AlertTestButton />
        </Card>
      )}

      {/* ── 9AM CR ──────────────────────────────────────────────────────── */}
      {section === 'cr9am' && (
        <Card title="9AM CR Model" subtitle="CRT methodology — editable fields apply immediately">
          <ROField   label="Timezone"          value={cr.timezone}              tooltip="Session boundary timezone for 1AM, 5AM, 9AM detection." />
          <ROField   label="Active window"     value={`${cr.active_from}:00–${cr.active_to}:00`} tooltip="Hours when CR plugin analyses candles and generates signals." />
          <EditableField label="Min score"     section="cr_9am" fieldKey="min_setup_score" value={cr.min_setup_score} type="number" tooltip="Minimum quality score to emit a CR signal." />
          <ROField   label="TP1 %"             value={`${((cr.tp1_pct_of_range ?? 0.5)*100).toFixed(0)}%`} tooltip="First take-profit as % of session range candle size." />
          <ROField   label="Reversal range"    value={cr.reversal_range}        tooltip="Session candle used for NY Reversal setups (CR_REVERSAL_RANGE)" />
          <ROField   label="Continuation"      value={cr.continuation_range}    tooltip="Session candle used for NY Continuation setups (CR_CONTINUATION_RANGE)" />
          <ROField   label="Require BOS"       value={String(cr.require_bos)}   tooltip="Require Break of Structure confirmation (CR_REQUIRE_BOS)" />
          <ROField   label="Require FVG"       value={String(cr.require_fvg)}   tooltip="Require Fair Value Gap in the setup (CR_REQUIRE_FVG)" />
          <ROField   label="Pairs"             value={cr.pairs}                 tooltip="Pairs monitored by the CR plugin." />
        </Card>
      )}

      {/* ── Brain ───────────────────────────────────────────────────────── */}
      {section === 'brain' && cfg && (
        <Card title="Brain" subtitle="Read-only — restart required to change">
          <ROField label="Version"          value={cfg.version}          tooltip="ARBX version from VERSION file." />
          <ROField label="Trading mode"     value={cfg.trading_mode}     tooltip="disabled / simulate / live. Change in Trading Mode tab." />
          <ROField label="Dry run"          value={String(cfg.dry_run)}  tooltip="Secondary safety switch. true = no real orders even in live mode." />
          <ROField label="Log level"        value={cfg.log_level}        tooltip="DEBUG / INFO / WARNING — set LOG_LEVEL in .env.local" />
          <ROField label="Heartbeat TTL"    value={`${cfg.heartbeat_ttl}s`}     tooltip="Seconds before a worker is marked dead (HEARTBEAT_TTL)" />
          <ROField label="Stale threshold"  value={`${cfg.stale_threshold_s}s`} tooltip="Seconds before a price is flagged stale in coverage map." />
        </Card>
      )}
    </div>
  )
}
