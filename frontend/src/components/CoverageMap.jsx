import React from 'react'
import { usePolling, fetchCoverage } from '../utils/api'
import { Card, StatusDot, EmptyState, Spinner } from './ui'
import { Tip, TipIcon } from './Tooltip'

const STATUS_TIPS = {
  healthy:    'Worker is streaming live data at normal latency with no errors.',
  degraded:   'Worker is connected but experiencing high latency, partial errors, or rate limiting.',
  blocked:    'Worker has been IP-blocked by the exchange. A replacement should be spawned from Fleet Health.',
  overloaded: 'Worker CPU or memory is above threshold — consider splitting its pairs across two workers.',
  dead:       'No heartbeat received within the TTL window. Worker is presumed offline.',
  starting:   'Worker is connecting and registering. Should become healthy within a few seconds.',
}

export default function CoverageMap({ onSelectWorker }) {
  const { data, loading } = usePolling(fetchCoverage, 8000)

  if (loading) return <Card title="Coverage Map"><Spinner /></Card>

  const coverage = data?.coverage ?? {}
  const gaps     = data?.gaps     ?? []

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
          <p className="text-red-400 font-medium text-sm mb-2 flex items-center">
            ⚠ Coverage Gaps Detected
            <TipIcon text="A gap means no worker is currently streaming data for this pair on this exchange. This creates a blind spot — arbitrage opportunities on that pair won't be detected." pos="right" wide />
          </p>
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
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">
                    <Tip text="Trading pair being monitored. Each row shows which exchanges have active workers streaming this pair." pos="bottom">
                      <span className="cursor-help border-b border-dashed border-gray-700">Pair</span>
                    </Tip>
                  </th>
                  {exchanges.map(e => (
                    <th key={e} className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">
                      <Tip text={`Workers streaming data from ${e}. Click the worker ID to inspect it in Fleet Health.`} pos="bottom">
                        <span className="cursor-help border-b border-dashed border-gray-700">{e}</span>
                      </Tip>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(byPair).sort().map(([pair, exMap]) => (
                  <tr key={pair} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                    <td className="py-2.5 pr-4 font-medium text-gray-200">{pair}</td>
                    {exchanges.map(ex => {
                      const ctx = exMap[ex]
                      return (
                        <td key={ex} className="py-2.5 pr-4">
                          {ctx ? (
                            <Tip text={
                              `Worker: ${ctx.worker_id}\nStatus: ${ctx.status}\n${STATUS_TIPS[ctx.status] ?? ''}\nClick to inspect in Fleet Health.`
                            } pos="right" wide>
                              <button
                                onClick={() => onSelectWorker && onSelectWorker(ctx.worker_id)}
                                className="flex items-center gap-1 hover:text-blue-400 transition-colors"
                              >
                                <StatusDot status={ctx.status} />
                                <span className="text-xs text-gray-400 font-mono">
                                  {ctx.worker_id.split('-').slice(-1)[0]}
                                </span>
                              </button>
                            </Tip>
                          ) : (
                            <Tip text={`No worker is streaming ${pair} on ${ex}. You can spawn one from Fleet Health → spawn worker.`} pos="right" wide>
                              <span className="text-xs text-red-900 cursor-help">— none —</span>
                            </Tip>
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
