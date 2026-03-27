import React, { useState } from 'react'
import { usePolling, fetchSecurityInfo, revokeWorker } from '../utils/api'
import { Card, EmptyState, Spinner, Button } from './ui'

export default function SecurityPanel() {
  const { data, loading, error } = usePolling(fetchSecurityInfo, 15000)
  const [revoking, setRevoking] = useState(null)

  const handleRevoke = async (workerId) => {
    if (!window.confirm(`Revoke worker ${workerId}? This will kill the worker immediately.`)) return
    setRevoking(workerId)
    try { await revokeWorker(workerId) } catch {}
    setRevoking(null)
  }

  if (loading) return <Card title="Security"><Spinner /></Card>

  const workers     = data?.workers ?? []
  const rejections  = data?.recent_rejections ?? []
  const count24h    = data?.rejections_24h ?? 0

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {[
          ['Registered Workers', workers.length, 'text-white'],
          ['Active',   workers.filter(w => !w.revoked).length, 'text-green-400'],
          ['Rejections (24h)', count24h, count24h > 0 ? 'text-red-400' : 'text-gray-600'],
        ].map(([label, value, color]) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
            <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Registered workers */}
      <Card title="Registered Workers" subtitle="Workers with brain credentials">
        {workers.length === 0 ? (
          <EmptyState message="No workers registered" icon="🔐" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  {['Worker ID', 'Exchange', 'Pairs', 'Can Execute', 'Expires', 'Status', ''].map((h, i) => (
                    <th key={i} className="text-left text-xs text-gray-500 uppercase pb-2 pr-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {workers.map((w, i) => (
                  <tr key={i} className="border-b border-gray-800/40">
                    <td className="py-2.5 pr-3 font-mono text-xs text-blue-400">{w.worker_id}</td>
                    <td className="py-2.5 pr-3 text-gray-300">{w.exchange}</td>
                    <td className="py-2.5 pr-3 text-gray-500 text-xs">
                      {(w.allowed_pairs || []).length > 0 ? w.allowed_pairs.join(', ') : 'all'}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className={`text-xs ${w.can_execute_orders ? 'text-green-400' : 'text-gray-600'}`}>
                        {w.can_execute_orders ? '✅ yes' : '○ no'}
                      </span>
                    </td>
                    <td className="py-2.5 pr-3 text-xs text-gray-500">
                      {w.expires_at ? new Date(w.expires_at).toLocaleDateString() : 'never'}
                    </td>
                    <td className="py-2.5 pr-3">
                      <span className={`text-xs ${w.revoked ? 'text-red-400' : 'text-green-400'}`}>
                        {w.revoked ? 'revoked' : 'active'}
                      </span>
                    </td>
                    <td className="py-2.5">
                      {!w.revoked && (
                        <Button
                          size="sm" variant="danger"
                          onClick={() => handleRevoke(w.worker_id)}
                          disabled={revoking === w.worker_id}
                        >
                          {revoking === w.worker_id ? '...' : 'Revoke'}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Rejection log */}
      {rejections.length > 0 && (
        <Card title="Recent Rejections" subtitle="Last 20 blocked connection attempts">
          <div className="space-y-1.5">
            {rejections.map((r, i) => (
              <div key={i} className="flex items-center gap-3 text-xs p-2 bg-red-900/10 rounded">
                <span className="text-red-400 shrink-0">✖</span>
                <span className="text-gray-500 font-mono shrink-0">{new Date(r.timestamp).toLocaleTimeString()}</span>
                <span className="text-gray-400 font-mono shrink-0">{r.ip}</span>
                <span className="text-gray-300">{r.worker_id || 'unknown'}</span>
                <span className="text-red-400 ml-auto">{r.reason}</span>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  )
}
