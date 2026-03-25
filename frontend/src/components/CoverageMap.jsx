import React from 'react'
import { usePolling, fetchCoverage } from '../utils/api'
import { Card, StatusDot, EmptyState, Spinner } from './ui'

export default function CoverageMap({ onSelectWorker }) {
  const { data, loading } = usePolling(fetchCoverage, 8000)

  if (loading) return <Card title="Coverage Map"><Spinner /></Card>

  const coverage = data?.coverage ?? {}
  const gaps = data?.gaps ?? []

  // Group by pair across exchanges
  const byPair = {}
  Object.values(coverage).forEach(c => {
    if (!byPair[c.pair]) byPair[c.pair] = {}
    byPair[c.pair][c.exchange] = c
  })

  const exchanges = [...new Set(Object.values(coverage).map(c => c.exchange))].sort()

  return (
    <div className="space-y-4">
      {gaps.length > 0 && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4">
          <p className="text-red-400 font-medium text-sm mb-2">⚠ Coverage Gaps Detected</p>
          {gaps.map((g, i) => (
            <p key={i} className="text-xs text-red-300">{g}</p>
          ))}
        </div>
      )}

      <Card
        title="Coverage Map"
        subtitle={`${Object.keys(coverage).length} contexts covered across ${exchanges.length} exchanges`}
      >
        {exchanges.length === 0 ? (
          <EmptyState message="No coverage data yet" icon="🗺" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Pair</th>
                  {exchanges.map(e => (
                    <th key={e} className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">{e}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(byPair).sort().map(([pair, exMap]) => (
                  <tr key={pair} className="border-b border-gray-800/40">
                    <td className="py-2.5 pr-4 font-medium text-gray-200">{pair}</td>
                    {exchanges.map(ex => {
                      const ctx = exMap[ex]
                      return (
                        <td key={ex} className="py-2.5 pr-4">
                          {ctx ? (
                            <button
                              onClick={() => onSelectWorker && onSelectWorker(ctx.worker_id)}
                              className="flex items-center gap-1 hover:text-blue-400 transition-colors"
                            >
                              <StatusDot status={ctx.status} />
                              <span className="text-xs text-gray-400 font-mono">{ctx.worker_id.split('-').slice(-1)[0]}</span>
                            </button>
                          ) : (
                            <span className="text-xs text-gray-700">— none —</span>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}
