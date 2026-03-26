import React from 'react'
import { usePolling, fetchContexts, fetchSignals } from '../utils/api'
import { Card, ConfidenceBadge, EmptyState, Spinner } from './ui'

function PluginDots({ signal }) {
  const plugins = signal?.plugins ?? []
  return (
    <div className="flex gap-1">
      {plugins.map((p, i) => (
        <span
          key={i}
          title={`${p.plugin}: ${p.signal_score?.toFixed(2)}`}
          className={`w-2 h-2 rounded-full ${p.signal_score > 0.6 ? 'bg-green-500' : p.signal_score > 0.4 ? 'bg-yellow-500' : 'bg-red-500'}`}
        />
      ))}
    </div>
  )
}

export default function AnalysisContexts() {
  const { data: ctxData, loading: ctxLoading } = usePolling(fetchContexts, 8000)
  const { data: sigData }                       = usePolling(fetchSignals,  8000)

  if (ctxLoading) return <Card title="Analysis Contexts"><Spinner /></Card>

  const contexts = ctxData?.contexts ?? []
  const signals  = sigData?.signals  ?? []
  const sigMap   = Object.fromEntries(signals.map(s => [`${s.exchange}:${s.pair}`, s]))

  return (
    <Card
      title="Analysis Contexts"
      subtitle={`${contexts.length} active contexts — per (exchange × pair)`}
    >
      {contexts.length === 0 ? (
        <EmptyState message="No contexts yet — waiting for worker data" icon="🧠" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                {['Context', 'Ticks', 'Score', 'Trend', 'Volatility', 'Plugins', 'Conf.'].map((h, i) => (
                  <th key={i} className="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {contexts.map((ctx, i) => {
                const sig = sigMap[ctx.key]
                return (
                  <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                    <td className="py-2.5 pr-4">
                      <span className="text-xs font-mono text-blue-400">{ctx.exchange}</span>
                      <span className="text-gray-500 mx-1">:</span>
                      <span className="text-gray-200 font-medium">{ctx.pair}</span>
                    </td>
                    <td className="py-2.5 pr-4 text-gray-500 text-xs font-mono">{ctx.tick_count?.toLocaleString()}</td>
                    <td className="py-2.5 pr-4 font-mono">
                      {sig ? (
                        <span className={sig.signal_score > 0.65 ? 'text-green-400' : sig.signal_score > 0.45 ? 'text-yellow-400' : 'text-red-400'}>
                          {sig.signal_score?.toFixed(3)}
                        </span>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="py-2.5 pr-4 text-xs">
                      <span className={sig?.trend === 'BULLISH' ? 'text-green-400' : sig?.trend === 'BEARISH' ? 'text-red-400' : 'text-gray-500'}>
                        {sig?.trend ?? '—'}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 text-xs text-gray-500">{sig?.volatility ?? '—'}</td>
                    <td className="py-2.5 pr-4">
                      {sig ? <PluginDots signal={sig} /> : <span className="text-gray-600 text-xs">{ctx.plugins_active} loaded</span>}
                    </td>
                    <td className="py-2.5 pr-4">
                      {sig ? <ConfidenceBadge value={sig.confidence} /> : <span className="text-gray-600 text-xs">—</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
