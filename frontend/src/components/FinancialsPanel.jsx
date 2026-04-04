import React, { useState } from 'react'
import { usePolling, fetchFinancialSummary, fetchTrades, fetchDailyPnl, closePosition } from '../utils/api'
import { Card, EmptyState, Spinner } from './ui'
import { Tip, TipIcon } from './Tooltip'

function StatCard({ label, value, sub, color = 'text-white', tip }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-xs text-gray-500 uppercase tracking-wider flex items-center">
        {label}
        {tip && <TipIcon text={tip} pos="bottom" wide />}
      </p>
      <p className={`text-2xl font-bold mt-1 ${color}`}>{value}</p>
      {sub && <p className="text-xs text-gray-600 mt-0.5">{sub}</p>}
    </div>
  )
}

function PnlChart({ data }) {
  if (!data || data.length === 0) return (
    <EmptyState message="No closed trades yet — P&L chart will appear here" icon="📈" />
  )
  const pnls    = data.map(d => d.pnl_usd)
  const max     = Math.max(...pnls.map(Math.abs), 1)
  let cumulative = 0
  const points  = data.map(d => { cumulative += d.pnl_usd; return cumulative })
  const maxCum  = Math.max(...points.map(Math.abs), 1)
  const W = 600, H = 120

  return (
    <div>
      <p className="text-xs text-gray-500 mb-2">Cumulative P&L (USD)</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-24">
        <line x1="0" y1={H/2} x2={W} y2={H/2} stroke="#374151" strokeWidth="1" />
        <polyline
          fill="none"
          stroke={points[points.length-1] >= 0 ? '#34d399' : '#f87171'}
          strokeWidth="2"
          points={points.map((v, i) => {
            const x = (i / Math.max(points.length - 1, 1)) * W
            const y = H/2 - (v / maxCum) * (H/2 - 8)
            return `${x},${y}`
          }).join(' ')}
        />
        {points.map((v, i) => {
          const x = (i / Math.max(points.length - 1, 1)) * W
          const y = H/2 - (v / maxCum) * (H/2 - 8)
          return <circle key={i} cx={x} cy={y} r="2" fill={v >= 0 ? '#34d399' : '#f87171'} />
        })}
      </svg>
      <div className="flex justify-between text-xs text-gray-600 mt-1">
        <span>{data[0]?.date}</span>
        <span>{data[data.length-1]?.date}</span>
      </div>
    </div>
  )
}

function TradeRow({ trade, onClose }) {
  const pnl    = trade.pnl_usd ?? 0
  const isOpen = trade.status === 'open' || trade.status === 'tp1_hit'
  return (
    <tr className="border-b border-gray-800/40 hover:bg-gray-800/20 text-xs">
      <td className="py-2 pr-3 font-medium text-gray-200">{trade.pair}</td>
      <td className="py-2 pr-3 capitalize text-gray-400">{trade.exchange}</td>
      <td className="py-2 pr-3">
        <span className={trade.side === 'buy' ? 'text-green-400' : 'text-red-400'}>
          {trade.side?.toUpperCase()}
        </span>
      </td>
      <td className="py-2 pr-3 font-mono text-gray-300">{trade.entry_price?.toFixed(4)}</td>
      <td className="py-2 pr-3 font-mono text-gray-300">
        {isOpen
          ? <span className="text-yellow-400">{trade.current_price?.toFixed(4)}</span>
          : trade.close_reason}
      </td>
      <td className="py-2 pr-3">
        <Tip text={`Realised P&L for this trade. ${pnl >= 0 ? 'Profitable.' : 'Loss.'} Includes entry/exit fees. Source: ${trade.source ?? 'unknown'}`} pos="left">
          <span className={`cursor-help ${pnl >= 0 ? 'text-green-400 font-semibold' : 'text-red-400 font-semibold'}`}>
            {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}
          </span>
        </Tip>
      </td>
      <td className="py-2 pr-3 text-gray-500">{trade.source}</td>
      <td className="py-2">
        {isOpen && (
          <button
            onClick={() => onClose(trade.id)}
            className="text-xs px-2 py-0.5 rounded bg-red-900/40 text-red-300 border border-red-800 hover:bg-red-900/60"
          >
            Close
          </button>
        )}
      </td>
    </tr>
  )
}

export default function FinancialsPanel() {
  const { data: summary, loading: sLoad } = usePolling(fetchFinancialSummary, 5000)
  const { data: tradesData, loading: tLoad } = usePolling(fetchTrades, 10000)
  const { data: pnlData }                  = usePolling(fetchDailyPnl, 30000)
  const [tab, setTab]                      = useState('summary')

  const handleClose = async (posId) => {
    try { await closePosition(posId) } catch (e) { console.error(e) }
  }

  if (sLoad) return <Card title="Financials"><Spinner /></Card>

  const ord   = summary?.orders   ?? {}
  const pos   = summary?.positions ?? {}
  const risk  = summary?.risk     ?? {}
  const trades    = tradesData?.trades ?? []
  const dailyPnl  = pnlData?.positions ?? pnlData?.orders ?? []

  return (
    <div className="space-y-4">
      {risk.halted && (
        <div className="bg-red-900/40 border border-red-600 rounded-xl p-4 flex items-center justify-between">
          <div>
            <p className="text-red-300 font-semibold">⛔ Risk Manager Halted</p>
            <p className="text-sm text-red-400 mt-0.5">{risk.halt_reason}</p>
          </div>
          <button
            onClick={() => fetch('/api/risk/resume', { method: 'POST' })}
            className="text-xs px-4 py-2 bg-red-700 hover:bg-red-600 text-white rounded-lg"
          >
            Resume
          </button>
        </div>
      )}

      {/* Top-level summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="Total P&L"
          value={`$${(ord.total_pnl_usd ?? 0).toFixed(2)}`}
          color={(ord.total_pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}
          tip="Sum of all realised profits and losses across all closed trades (simulated and live). Does not include open unrealised P&L."
        />
        <StatCard
          label="Win Rate"
          value={`${ord.win_rate ?? 0}%`}
          sub={`${ord.wins ?? 0}W / ${ord.losses ?? 0}L`}
          color="text-blue-400"
          tip="Percentage of closed trades that ended in profit. Win rate alone doesn't measure strategy quality — a 40% win rate with a 3:1 R:R is profitable."
        />
        <StatCard
          label="Total Trades"
          value={ord.closed ?? 0}
          sub={`${ord.simulated ?? 0} simulated · ${ord.live ?? 0} live`}
          tip="Count of all closed trades. Simulated trades use real market prices but don't execute on the exchange. Live trades are real fills."
        />
        <StatCard
          label="Daily Loss"
          value={`$${risk.daily_loss_usd ?? 0}`}
          sub={`limit $${risk.max_daily_loss_usd ?? 0}`}
          color={(risk.daily_loss_pct ?? 0) > 80 ? 'text-red-400' : 'text-gray-300'}
          tip="Total realised losses today (resets at midnight UTC). When this reaches the Max Daily Loss limit in Risk & Rules, all new orders are halted automatically."
        />
      </div>

      {/* Risk Status gauges */}
      <Card title="Risk Status">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[
            {
              label: 'Daily Loss',
              pct: risk.daily_loss_pct ?? 0,
              color: 'bg-red-500',
              tip: 'How much of the daily loss limit has been consumed. Bar turns full red when the circuit breaker triggers.',
            },
            {
              label: 'Drawdown',
              pct: ((risk.drawdown_pct ?? 0) / (risk.max_drawdown_pct || 10)) * 100,
              color: 'bg-orange-500',
              tip: 'Current portfolio drawdown as a percentage of the max drawdown limit. Drawdown = (peak_balance - current_balance) / peak_balance × 100.',
            },
            {
              label: 'Consec. Losses',
              pct: ((risk.consecutive_losses ?? 0) / (risk.max_consecutive || 5)) * 100,
              color: 'bg-yellow-500',
              tip: 'How many consecutive losing trades have occurred out of the allowed maximum. Resets to 0 when a trade closes in profit.',
            },
          ].map(g => (
            <div key={g.label}>
              <div className="flex justify-between text-xs text-gray-400 mb-1">
                <span className="flex items-center">
                  {g.label}
                  <TipIcon text={g.tip} pos="top" wide />
                </span>
                <span>{Math.round(g.pct)}%</span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-2">
                <div
                  className={`h-2 rounded-full ${g.color} transition-all`}
                  style={{ width: `${Math.min(g.pct, 100)}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-800 pb-2">
        {['summary', 'trades', 'chart'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`text-xs px-3 py-1.5 rounded transition-colors capitalize
              ${tab === t ? 'bg-green-700 text-white' : 'text-gray-400 hover:bg-gray-800'}`}>
            {t === 'summary' ? '📊 Summary' : t === 'trades' ? '📋 Trade History' : '📈 P&L Chart'}
          </button>
        ))}
      </div>

      {tab === 'chart' && (
        <Card title="Cumulative P&L">
          {tLoad ? <Spinner /> : <PnlChart data={dailyPnl} />}
        </Card>
      )}

      {tab === 'summary' && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Trade Stats */}
          <Card title="Trade Stats">
            <div className="space-y-2 text-sm">
              {[
                {
                  l: 'Best Trade',
                  v: `$${ord.best_trade ?? 0}`,
                  tip: 'The single most profitable closed trade (gross P&L before fees).',
                },
                {
                  l: 'Worst Trade',
                  v: `$${ord.worst_trade ?? 0}`,
                  tip: 'The single largest loss on a closed trade (gross P&L before fees). Review this for risk sizing.',
                },
                {
                  l: 'Avg P&L',
                  v: `$${ord.avg_pnl_usd ?? 0}`,
                  tip: 'Average profit or loss per closed trade. Positive expectancy means the strategy is profitable in the long run.',
                },
                {
                  l: 'Total Fees',
                  v: `$${ord.total_fees_usd ?? 0}`,
                  tip: 'Cumulative exchange fees paid across all closed trades. This is already deducted from the P&L figures above.',
                },
              ].map(({ l, v, tip }) => (
                <div key={l} className="flex justify-between border-b border-gray-800 pb-1">
                  <span className="text-gray-500 flex items-center">
                    {l}
                    <TipIcon text={tip} pos="right" wide />
                  </span>
                  <span className="text-gray-200 font-medium">{v}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Open Positions */}
          <Card title="Open Positions">
            {(summary?.positions?.total_trades === 0) ? (
              <EmptyState message="No open positions" icon="📭" />
            ) : (
              <div className="space-y-2 text-xs">
                {trades
                  .filter(t => t.status === 'open' || t.status === 'tp1_hit')
                  .map((t, i) => (
                    <div key={i} className="flex justify-between border-b border-gray-800 pb-1">
                      <span className="text-gray-300">
                        {t.pair} <span className="text-gray-600">{t.exchange}</span>
                        {t.status === 'tp1_hit' && (
                          <Tip text="TP1 has been reached — the position is partially closed or stop moved to breakeven. Waiting for TP2." pos="right">
                            <span className="ml-1 text-blue-400 cursor-help">TP1✓</span>
                          </Tip>
                        )}
                      </span>
                      <span className={(t.pnl_usd ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'}>
                        {(t.pnl_usd ?? 0) >= 0 ? '+' : ''}{(t.pnl_usd ?? 0).toFixed(2)}
                      </span>
                    </div>
                  ))}
              </div>
            )}
          </Card>
        </div>
      )}

      {tab === 'trades' && (
        <Card title="Trade History" subtitle={`${trades.length} trades`}>
          {tLoad ? <Spinner /> : trades.length === 0 ? (
            <EmptyState message="No trades yet" icon="📋" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800">
                    {['Pair', 'Exchange', 'Side', 'Entry', 'Exit / Status', 'P&L', 'Source', ''].map(h => (
                      <th key={h} className="text-left text-xs text-gray-500 uppercase pb-2 pr-3">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {trades.map((t, i) => <TradeRow key={i} trade={t} onClose={handleClose} />)}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
