import React from 'react'
import { usePolling, fetchWorker, fetchPrices } from '../utils/api'
import { Card, StatusDot, StatusBadge, Stat, Spinner, Button } from './ui'

export default function WorkerInspector({ workerId, onBack }) {
  const { data: worker, loading } = usePolling(() => fetchWorker(workerId), 4000)
  const { data: pricesData }      = usePolling(fetchPrices, 3000)

  if (loading) return <Card title="Worker Inspector"><Spinner /></Card>
  if (!worker) return <Card title="Worker Inspector"><p className="text-gray-500 text-sm">Worker not found.</p></Card>

  const allPrices = pricesData?.prices ?? []
  const workerPrices = allPrices.filter(p => p.worker_id === workerId || p.exchange === worker.exchange)

  return (
    <div className="space-y-4">
      {/* Back button + header */}
      <div className="flex items-center gap-3">
        <Button variant="default" onClick={onBack}>← Back to Fleet</Button>
        <div>
          <h2 className="text-sm font-bold text-white font-mono">{worker.worker_id}</h2>
          <p className="text-xs text-gray-500">{worker.exchange} · {worker.machine}</p>
        </div>
        <StatusBadge status={worker.status} />
        {worker.is_replacement && (
          <span className="text-xs bg-purple-900/40 text-purple-400 border border-purple-800 px-2 py-0.5 rounded">
            replacement for {worker.replaced_worker}
          </span>
        )}
      </div>

      {/* Performance stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <Card><Stat label="Latency"    value={`${worker.latency_ms?.toFixed(0) ?? '—'}ms`}
          color={worker.latency_ms > 1500 ? 'text-red-400' : 'text-green-400'} /></Card>
        <Card><Stat label="Ticks/min"  value={worker.ticks_per_min ?? 0} color="text-blue-400" /></Card>
        <Card><Stat label="CPU"        value={`${worker.cpu_pct?.toFixed(0) ?? 0}%`}
          color={worker.cpu_pct > 80 ? 'text-red-400' : 'text-gray-300'} /></Card>
        <Card><Stat label="Errors"     value={worker.error_count ?? 0}
          color={worker.error_count > 0 ? 'text-red-400' : 'text-gray-500'} /></Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Worker details */}
        <Card title="Worker Details">
          <dl className="space-y-2 text-sm">
            {[
              ['Exchange',   worker.exchange],
              ['Machine',    worker.machine],
              ['Status',     worker.status],
              ['Condition',  worker.condition || 'none'],
              ['Pairs',      (worker.pairs || []).join(', ')],
              ['Role',       worker.can_execute_orders ? 'collector + executor' : 'collector only'],
              ['Last heartbeat', worker.last_heartbeat ? new Date(worker.last_heartbeat).toLocaleTimeString() : '—'],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between">
                <dt className="text-gray-500">{label}</dt>
                <dd className="text-gray-200 font-mono text-xs">{value}</dd>
              </div>
            ))}
          </dl>
          {worker.last_error && (
            <div className="mt-3 p-2 bg-red-900/20 border border-red-900/50 rounded text-xs text-red-400">
              Last error: {worker.last_error}
            </div>
          )}
        </Card>

        {/* Live price feed from this worker's exchange */}
        <Card title="Live Price Feed" subtitle={`${worker.exchange} prices`}>
          {workerPrices.length === 0 ? (
            <p className="text-gray-600 text-sm">No prices yet</p>
          ) : (
            <div className="space-y-1.5">
              {workerPrices.slice(0, 8).map((p, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-gray-300 font-medium">{p.pair}</span>
                  <span className="text-green-400 font-mono">{p.price?.toLocaleString(undefined, { maximumFractionDigits: 6 })}</span>
                  <span className="text-gray-600 text-xs font-mono">
                    {p.timestamp ? new Date(p.timestamp).toLocaleTimeString() : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
