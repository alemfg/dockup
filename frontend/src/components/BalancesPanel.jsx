import React from 'react'
import { usePolling, fetchBalances } from '../utils/api'
import { Card, EmptyState, Spinner, Stat } from './ui'

const EXCHANGE_COLORS = {
  binance: 'bg-yellow-500', kraken: 'bg-blue-500',
  coinbase: 'bg-blue-400',  bybit: 'bg-orange-500',
}

export default function BalancesPanel() {
  const { data, loading } = usePolling(fetchBalances, 10000)
  if (loading) return <Card title="Balances"><Spinner /></Card>

  const totalUsd   = data?.total_usd ?? 0
  const byExchange = data?.exchanges ?? {}

  return (
    <Card
      title="Fund Balances"
      subtitle="Across all connected exchanges"
      action={<span className="text-lg font-bold text-green-400">${totalUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>}
    >
      {Object.keys(byExchange).length === 0 ? (
        <EmptyState message="No balance data yet — workers not reporting balances" icon="💰" />
      ) : (
        Object.entries(byExchange).map(([exchange, balances]) => {
          const exTotal = balances.reduce((s, b) => s + (b.usd_value || 0), 0)
          const pct = totalUsd > 0 ? (exTotal / totalUsd * 100) : 0
          const color = EXCHANGE_COLORS[exchange] || 'bg-gray-500'
          return (
            <div key={exchange} className="mb-4">
              <div className="flex justify-between items-center mb-1.5">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${color}`} />
                  <span className="text-sm font-medium text-gray-200 capitalize">{exchange}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-gray-500">{pct.toFixed(1)}%</span>
                  <span className="text-sm font-semibold text-gray-200">${exTotal.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                </div>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 mb-1.5">
                <div className={`h-1.5 rounded-full ${color} transition-all`} style={{ width: `${Math.min(pct, 100)}%` }} />
              </div>
              <div className="flex gap-3 flex-wrap">
                {balances.map(b => (
                  <span key={b.asset} className="text-xs text-gray-500">
                    {b.asset}: <span className="text-gray-300">{b.free?.toFixed(4)}</span>
                  </span>
                ))}
              </div>
            </div>
          )
        })
      )}
    </Card>
  )
}
