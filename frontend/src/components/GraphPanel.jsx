import React, { useState } from 'react'
import { usePolling } from '../utils/api'
import { Card, ConfidenceBadge, EmptyState, Spinner } from './ui'

const fetchGraphPaths = () => fetch('/api/graph/paths').then(r => r.json())
const fetchGraphState = () => fetch('/api/graph/state').then(r => r.json())

// ─── Visual path renderer ────────────────────────────────────────────────────

function PathFlow({ assets, exchanges }) {
  return (
    <div className="flex items-center gap-1 flex-wrap my-2">
      {assets.map((asset, i) => (
        <React.Fragment key={i}>
          {/* Asset bubble */}
          <div className={`
            px-2.5 py-1 rounded-full text-xs font-bold border
            ${asset === 'USDT' ? 'bg-green-900/50 border-green-700 text-green-300' :
              asset === 'BTC'  ? 'bg-orange-900/50 border-orange-700 text-orange-300' :
              asset === 'ETH'  ? 'bg-blue-900/50 border-blue-700 text-blue-300' :
              asset === 'BNB'  ? 'bg-yellow-900/50 border-yellow-700 text-yellow-300' :
              asset === 'SOL'  ? 'bg-purple-900/50 border-purple-700 text-purple-300' :
              'bg-gray-800 border-gray-700 text-gray-300'}
          `}>
            {asset}
          </div>

          {/* Arrow + exchange label */}
          {i < assets.length - 1 && (
            <div className="flex flex-col items-center">
              <span className="text-xs text-gray-600 mb-0.5">{exchanges?.[i]}</span>
              <span className="text-gray-500 text-sm">→</span>
            </div>
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ─── Edge breakdown table ─────────────────────────────────────────────────────

function EdgeBreakdown({ edges }) {
  if (!edges?.length) return null
  return (
    <div className="mt-3 border-t border-gray-800 pt-3">
      <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Leg-by-leg breakdown</p>
      <div className="space-y-1">
        {edges.map((e, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-gray-400 font-mono w-32">
              {e.from} → {e.to}
            </span>
            <span className="text-gray-500 w-20">{e.exchange}</span>
            <span className="text-gray-300 font-mono w-24">
              ×{e.effective_rate?.toFixed(6)}
            </span>
            <span className="text-red-400 w-16">
              -{(e.fee_pct ?? 0).toFixed(3)}%
            </span>
            {e.gas_usd > 0 && (
              <span className="text-orange-400 w-16">
                ${e.gas_usd?.toFixed(2)} gas
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Single path card ─────────────────────────────────────────────────────────

function PathCard({ path, rank }) {
  const [expanded, setExpanded] = useState(false)
  const isProfit = path.net_profit_pct > 0

  return (
    <div className={`border rounded-lg p-4 mb-3 ${
      rank === 0
        ? 'border-green-700/60 bg-green-900/10'
        : 'border-gray-800 bg-gray-900/50'
    }`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {rank === 0 && (
            <span className="text-xs bg-green-800 text-green-300 px-2 py-0.5 rounded-full border border-green-700">
              BEST
            </span>
          )}
          <span className="text-xs text-gray-500 font-mono">#{rank + 1}</span>
          <span className="text-xs text-gray-500">{path.hops} hops</span>
          <span className="text-xs text-gray-600">
            {path.exchanges?.filter((v, i, a) => a.indexOf(v) === i).join(' + ')}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className={`text-lg font-bold font-mono ${isProfit ? 'text-green-400' : 'text-red-400'}`}>
              {isProfit ? '+' : ''}{path.net_profit_pct?.toFixed(4)}%
            </p>
            <p className="text-xs text-gray-500">
              ${path.net_profit_usd?.toFixed(2)} net
            </p>
          </div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-gray-600 hover:text-gray-300 text-xs"
          >
            {expanded ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {/* Path flow visual */}
      <PathFlow assets={path.assets} exchanges={path.exchanges} />

      {/* Profit breakdown pills */}
      <div className="flex gap-2 flex-wrap text-xs mt-1">
        <span className="bg-gray-800 text-gray-400 px-2 py-0.5 rounded">
          gross {path.gross_profit_pct?.toFixed(4)}%
        </span>
        <span className="bg-red-900/30 text-red-400 px-2 py-0.5 rounded">
          fees -{path.total_fee_pct?.toFixed(4)}%
        </span>
        {path.total_gas_usd > 0 && (
          <span className="bg-orange-900/30 text-orange-400 px-2 py-0.5 rounded">
            gas -${path.total_gas_usd?.toFixed(2)}
          </span>
        )}
        <span className="bg-gray-800 text-gray-500 px-2 py-0.5 rounded font-mono">
          {path.path}
        </span>
      </div>

      {/* Expanded leg detail */}
      {expanded && <EdgeBreakdown edges={path.edges} />}
    </div>
  )
}

// ─── Graph state summary ──────────────────────────────────────────────────────

function GraphSummary({ state }) {
  if (!state) return null
  const { summary } = state
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
      {[
        ['Nodes (Assets)',   summary?.nodes,                        'text-blue-400'],
        ['Edges (Pairs)',    summary?.edges,                        'text-white'],
        ['Exchanges',        summary?.exchanges?.length,            'text-purple-400'],
        ['Assets tracked',   summary?.assets?.join(', ') || '—',   'text-xs text-gray-400'],
      ].map(([label, value, color]) => (
        <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider">{label}</p>
          <p className={`font-bold mt-1 ${color} ${typeof value === 'string' && value.length > 10 ? 'text-xs mt-1.5' : 'text-2xl'}`}>
            {value ?? '—'}
          </p>
        </div>
      ))}
    </div>
  )
}

// ─── Main panel ──────────────────────────────────────────────────────────────

export default function GraphPanel() {
  const [showState, setShowState] = useState(false)

  const { data: pathData, loading: pathLoading } = usePolling(fetchGraphPaths, 5000)
  const { data: stateData }                       = usePolling(fetchGraphState, 10000)

  const paths    = pathData?.paths     ?? []
  const algo     = pathData?.algorithm ?? 'bellman_ford'

  if (pathLoading) return <Card title="Graph Arbitrage"><Spinner /></Card>

  return (
    <div className="space-y-4">

      {/* Graph state stats */}
      <GraphSummary state={stateData} />

      {/* Paths */}
      <Card
        title="Multi-Hop Arbitrage Paths"
        subtitle={`${paths.length} profitable cycles detected · algorithm: ${algo}`}
        action={
          <div className="flex gap-2 items-center">
            <button
              onClick={() => setShowState(!showState)}
              className="text-xs text-gray-500 hover:text-gray-300 bg-gray-800 px-3 py-1.5 rounded border border-gray-700"
            >
              {showState ? 'Hide graph' : 'Show graph'}
            </button>
          </div>
        }
      >
        {paths.length === 0 ? (
          <EmptyState
            message="No profitable paths yet — graph builds as workers stream prices"
            icon="🕸"
          />
        ) : (
          paths.map((path, i) => <PathCard key={path.id || i} path={path} rank={i} />)
        )}
      </Card>

      {/* Raw adjacency graph (toggle) */}
      {showState && stateData?.adjacency && (
        <Card title="Currency Graph — Adjacency" subtitle="All live edges with effective rates">
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-800">
                  {['From', 'To', 'Exchange', 'Effective Rate', 'Fee', 'Stale'].map(h => (
                    <th key={h} className="text-left text-gray-500 uppercase pb-2 pr-4">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(stateData.adjacency).flatMap(([from, toList]) =>
                  toList.map((edge, i) => (
                    <tr key={`${from}-${edge.to}-${i}`} className="border-b border-gray-800/30">
                      <td className="py-1.5 pr-4 font-bold text-gray-300">{from}</td>
                      <td className="py-1.5 pr-4 text-gray-400">{edge.to}</td>
                      <td className="py-1.5 pr-4 text-gray-500">{edge.exchange}</td>
                      <td className="py-1.5 pr-4 font-mono text-gray-300">{edge.effective_rate?.toFixed(6)}</td>
                      <td className="py-1.5 pr-4 text-red-400">{edge.fee_pct?.toFixed(3)}%</td>
                      <td className="py-1.5">
                        <span className={edge.stale ? 'text-red-400' : 'text-green-400'}>
                          {edge.stale ? '⚠ stale' : '● live'}
                        </span>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* How it works */}
      <Card title="How Graph Arbitrage Works">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs text-gray-400">
          <div>
            <p className="text-gray-200 font-medium mb-1">1 — Build the Graph</p>
            <p>
              Every price tick from every worker adds two directed edges to the
              currency graph — one for buying, one for selling. All fees,
              slippage, and gas are baked into the edge weight.
            </p>
          </div>
          <div>
            <p className="text-gray-200 font-medium mb-1">2 — Run Bellman-Ford</p>
            <p>
              Edge weights are transformed with -log(rate). A negative-weight
              cycle means the product of rates &gt; 1.0 — a profitable path.
              Bellman-Ford detects these cycles in O(V×E) time.
            </p>
          </div>
          <div>
            <p className="text-gray-200 font-medium mb-1">3 — Validate & Rank</p>
            <p>
              Each path is checked for liquidity, freshness, and transfer
              feasibility. Surviving paths are ranked by net profit after
              all costs and displayed here in real-time.
            </p>
          </div>
        </div>
        <div className="mt-3 text-xs text-gray-600 border-t border-gray-800 pt-3 font-mono">
          Example: USDT → BTC → BNB → SOL → USDT
          &nbsp;·&nbsp; 0.99901 × 0.99874 × 1.00250 × 0.99900 = 1.00923 (+0.923%)
        </div>
      </Card>
    </div>
  )
}
