import React, { useState } from 'react'
import {
  useWebSocket,
  killWorker, restartWorker, pauseWorker, resumeWorker, reloadWorker,
  reloadAllWorkers, killAllWorkers,
} from '../utils/api'
import { Card, StatusDot, StatusBadge, WsBadge, EmptyState, Stat } from './ui'

const STATUS_ORDER = { healthy: 0, degraded: 1, paused: 2, blocked: 3, overloaded: 4, dead: 5, starting: 6 }

function WorkerActionBtn({ label, title, onClick, variant = 'default', disabled }) {
  const [loading, setLoading] = useState(false)
  const handle = async () => {
    setLoading(true)
    try { await onClick() } catch {}
    setLoading(false)
  }
  const base = 'text-xs px-1.5 py-0.5 rounded border transition-colors disabled:opacity-40 font-mono'
  const styles = {
    default: 'border-gray-700 text-gray-400 hover:text-gray-200 hover:border-gray-500',
    danger:  'border-red-900 text-red-400 hover:bg-red-900/30',
    warn:    'border-yellow-900 text-yellow-400 hover:bg-yellow-900/30',
    blue:    'border-blue-900 text-blue-400 hover:bg-blue-900/30',
    green:   'border-green-900 text-green-400 hover:bg-green-900/30',
  }
  return (
    <button
      title={title}
      onClick={handle}
      disabled={disabled || loading}
      className={`${base} ${styles[variant] || styles.default}`}
    >
      {loading ? '…' : label}
    </button>
  )
}

function WorkerRow({ worker, onSelect }) {
  const isPaused = worker.status === 'paused'
  const isDead   = worker.status === 'dead'

  return (
    <tr className={`border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors ${isDead ? 'opacity-50' : ''}`}>
      <td className="py-2.5 pr-3">
        <div className="flex items-center gap-1.5">
          <StatusDot status={worker.status} />
          <button
            onClick={() => onSelect(worker.worker_id)}
            className="text-sm text-blue-400 hover:text-blue-300 font-mono text-left"
          >
            {worker.worker_id}
          </button>
          {worker.is_replacement && (
            <span className="text-xs bg-purple-900/40 text-purple-400 border border-purple-800 px-1 rounded">
              replacement
            </span>
          )}
          {isPaused && (
            <span className="text-xs bg-yellow-900/40 text-yellow-400 border border-yellow-800 px-1 rounded">
              ⏸ paused
            </span>
          )}
        </div>
      </td>
      <td className="py-2.5 pr-3 text-gray-300 text-sm">{worker.exchange}</td>
      <td className="py-2.5 pr-3 text-gray-500 text-xs max-w-[180px] truncate">
        {(worker.pairs || []).join(', ')}
      </td>
      <td className="py-2.5 pr-3"><StatusBadge status={worker.status} /></td>
      <td className="py-2.5 pr-3 font-mono text-xs">
        {worker.latency_ms > 0 ? (
          <span className={
            worker.latency_ms > 1500 ? 'text-red-400' :
            worker.latency_ms > 800  ? 'text-yellow-400' : 'text-green-400'
          }>
            {worker.latency_ms.toFixed(0)}ms
          </span>
        ) : '—'}
      </td>
      <td className="py-2.5">
        {/* Per-worker action buttons */}
        <div className="flex gap-1 flex-wrap">
          {isPaused ? (
            <WorkerActionBtn label="▶" title="Resume worker" variant="green"
              onClick={() => resumeWorker(worker.worker_id)} />
          ) : (
            <WorkerActionBtn label="⏸" title="Pause worker (suspend ticks)" variant="warn"
              onClick={() => pauseWorker(worker.worker_id)} />
          )}
          <WorkerActionBtn label="↺" title="Restart worker" variant="default"
            onClick={() => restartWorker(worker.worker_id)} />
          <WorkerActionBtn label="⟳" title="Reload config" variant="blue"
            onClick={() => reloadWorker(worker.worker_id)} />
          <WorkerActionBtn label="✕" title="Kill worker" variant="danger"
            onClick={() => killWorker(worker.worker_id)} />
        </div>
      </td>
    </tr>
  )
}

function BulkActions() {
  const [result, setResult] = useState(null)
  const act = async (fn, label) => {
    try { const r = await fn(); setResult(`✅ ${label}: ${r.message}`) }
    catch (e) { setResult(`⚠️ ${e.message}`) }
    setTimeout(() => setResult(null), 4000)
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-xs text-gray-500">All workers:</span>
      <WorkerActionBtn label="⟳ Reload all" title="Reload config on all workers" variant="blue"
        onClick={() => act(reloadAllWorkers, 'Reload all')} />
      <WorkerActionBtn label="✕ Stop all" title="Kill all workers" variant="danger"
        onClick={() => act(killAllWorkers, 'Kill all')} />
      {result && <span className="text-xs text-gray-400 ml-1">{result}</span>}
    </div>
  )
}

export default function FleetHealth({ onSelectWorker }) {
  const { data, status } = useWebSocket('/ws/fleet')
  const workers = (data?.workers ?? []).slice().sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
  )
  const events = data?.events ?? []

  const healthy  = workers.filter(w => w.status === 'healthy').length
  const degraded = workers.filter(w => ['degraded', 'overloaded'].includes(w.status)).length
  const paused   = workers.filter(w => w.status === 'paused').length
  const blocked  = workers.filter(w => w.status === 'blocked').length
  const dead     = workers.filter(w => w.status === 'dead').length

  return (
    <div className="space-y-4">
      {/* Summary stats — now includes Paused and Blocked */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
        <Card><Stat label="Total"    value={workers.length}        color="text-white" /></Card>
        <Card><Stat label="Healthy"  value={healthy}               color="text-green-400" /></Card>
        <Card><Stat label="Degraded" value={degraded}              color={degraded > 0 ? 'text-yellow-400' : 'text-gray-600'} /></Card>
        <Card><Stat label="Paused"   value={paused}                color={paused > 0 ? 'text-yellow-300' : 'text-gray-600'} /></Card>
        <Card><Stat label="Blocked"  value={blocked}               color={blocked > 0 ? 'text-orange-400' : 'text-gray-600'} /></Card>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Card><Stat label="Dead" value={dead} color={dead > 0 ? 'text-red-400' : 'text-gray-600'} /></Card>
      </div>

      {/* Worker table */}
      <Card
        title="Worker Fleet"
        subtitle={`${workers.length} registered workers`}
        action={
          <div className="flex items-center gap-3">
            <BulkActions />
            <WsBadge status={status} />
          </div>
        }
      >
        {workers.length === 0 ? (
          <EmptyState message="No workers connected" icon="🖥" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  {['Worker ID', 'Exchange', 'Pairs', 'Status', 'Latency', 'Actions'].map((h, i) => (
                    <th key={i} className="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workers.map(w => (
                  <WorkerRow key={w.worker_id} worker={w} onSelect={onSelectWorker} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Recent events */}
      {events.length > 0 && (
        <Card title="Recent Fleet Events">
          <div className="space-y-1.5">
            {events.slice(0, 8).map((e, i) => (
              <div key={i} className="flex items-start gap-3 text-xs">
                <span className={`shrink-0 mt-0.5 ${
                  e.level === 'WARNING' ? 'text-yellow-400' :
                  e.level === 'ERROR'   ? 'text-red-400' : 'text-gray-500'
                }`}>
                  {e.level === 'WARNING' ? '⚠' : e.level === 'ERROR' ? '✖' : '●'}
                </span>
                <span className="text-gray-400 shrink-0 font-mono w-16">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <span className="text-gray-300">{e.message}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
