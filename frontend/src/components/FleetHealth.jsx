import React, { useState } from 'react'
import { useWebSocket, killWorker, restartWorker } from '../utils/api'
import { Card, StatusDot, StatusBadge, WsBadge, EmptyState, Button, Stat } from './ui'

function WorkerRow({ worker, onSelect, onKill, onRestart }) {
  const [acting, setActing] = useState(null)

  const act = async (fn, label) => {
    setActing(label)
    try { await fn(worker.worker_id) } catch {}
    setActing(null)
  }

  return (
    <tr className="border-b border-gray-800/40 hover:bg-gray-800/30 transition-colors">
      <td className="py-3 pr-3">
        <div className="flex items-center">
          <StatusDot status={worker.status} />
          <button
            onClick={() => onSelect(worker.worker_id)}
            className="text-sm text-blue-400 hover:text-blue-300 font-mono text-left"
          >
            {worker.worker_id}
          </button>
          {worker.is_replacement && (
            <span className="ml-2 text-xs bg-purple-900/40 text-purple-400 border border-purple-800 px-1.5 rounded">
              replacement
            </span>
          )}
        </div>
      </td>
      <td className="py-3 pr-3 text-gray-300">{worker.exchange}</td>
      <td className="py-3 pr-3 text-gray-500 text-xs">{(worker.pairs || []).join(', ')}</td>
      <td className="py-3 pr-3 text-gray-400 font-mono text-xs">{worker.machine}</td>
      <td className="py-3 pr-3"><StatusBadge status={worker.status} /></td>
      <td className="py-3 pr-3 text-gray-400 font-mono">
        {worker.latency_ms > 0 ? (
          <span className={worker.latency_ms > 1500 ? 'text-red-400' : worker.latency_ms > 800 ? 'text-yellow-400' : 'text-green-400'}>
            {worker.latency_ms.toFixed(0)}ms
          </span>
        ) : '—'}
      </td>
      <td className="py-3 pr-3 text-gray-500 text-xs">
        {worker.cpu_pct > 0 ? `${worker.cpu_pct.toFixed(0)}% CPU` : '—'}
      </td>
      <td className="py-3">
        <div className="flex gap-1.5">
          <Button size="sm" variant="default"   onClick={() => act(restartWorker, 'restart')} disabled={!!acting}>
            {acting === 'restart' ? '...' : '↺'}
          </Button>
          <Button size="sm" variant="danger"    onClick={() => act(killWorker, 'kill')}    disabled={!!acting}>
            {acting === 'kill' ? '...' : '✕'}
          </Button>
        </div>
      </td>
    </tr>
  )
}

export default function FleetHealth({ onSelectWorker }) {
  const { data, status } = useWebSocket('/ws/fleet')
  const workers = data?.workers ?? []
  const events  = data?.events  ?? []

  const healthy    = workers.filter(w => w.status === 'healthy').length
  const degraded   = workers.filter(w => w.status === 'degraded').length
  const blocked    = workers.filter(w => w.status === 'blocked').length
  const dead       = workers.filter(w => w.status === 'dead').length

  return (
    <div className="space-y-4">
      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card><Stat label="Total Workers" value={workers.length} color="text-white" /></Card>
        <Card><Stat label="Healthy"       value={healthy}         color="text-green-400" /></Card>
        <Card><Stat label="Degraded"      value={degraded + blocked} color={degraded + blocked > 0 ? 'text-yellow-400' : 'text-gray-600'} /></Card>
        <Card><Stat label="Dead"          value={dead}            color={dead > 0 ? 'text-red-400' : 'text-gray-600'} /></Card>
      </div>

      {/* Worker table */}
      <Card
        title="Worker Fleet"
        subtitle={`${workers.length} registered workers`}
        action={<WsBadge status={status} />}
      >
        {workers.length === 0 ? (
          <EmptyState message="No workers connected" icon="🖥" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  {['Worker ID', 'Exchange', 'Pairs', 'Machine', 'Status', 'Latency', 'Load', 'Actions'].map((h, i) => (
                    <th key={i} className="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workers.map(w => (
                  <WorkerRow
                    key={w.worker_id}
                    worker={w}
                    onSelect={onSelectWorker}
                    onKill={killWorker}
                    onRestart={restartWorker}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Recent events */}
      {events.length > 0 && (
        <Card title="Recent Events" subtitle="Last 10 fleet events">
          <div className="space-y-1.5">
            {events.slice(0, 5).map((e, i) => (
              <div key={i} className="flex items-start gap-3 text-xs">
                <span className={`shrink-0 mt-0.5 ${
                  e.level === 'WARNING' ? 'text-yellow-400' :
                  e.level === 'ERROR'   ? 'text-red-400' : 'text-gray-500'
                }`}>
                  {e.level === 'WARNING' ? '⚠' : e.level === 'ERROR' ? '✖' : '●'}
                </span>
                <span className="text-gray-400 shrink-0 font-mono">
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
