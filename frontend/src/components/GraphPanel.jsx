import React, { useState, useRef, useEffect, useCallback } from 'react'
import { usePolling } from '../utils/api'
import { Card, ConfidenceBadge, EmptyState, Spinner } from './ui'
import { Tip, TipIcon } from './Tooltip'

const fetchGraphPaths = () => fetch('/api/graph/paths').then(r => r.json())
const fetchGraphState = () => fetch('/api/graph/state').then(r => r.json())
const fetchGraphConfig = () => fetch('/api/graph/config').then(r => r.json())

// ─── Colour palette ───────────────────────────────────────────────────────────
const ASSET_COLORS = {
  USDT: { bg: '#14532d', border: '#16a34a', text: '#86efac' },
  BTC:  { bg: '#7c2d12', border: '#ea580c', text: '#fdba74' },
  ETH:  { bg: '#1e3a5f', border: '#3b82f6', text: '#93c5fd' },
  BNB:  { bg: '#713f12', border: '#ca8a04', text: '#fde68a' },
  SOL:  { bg: '#3b0764', border: '#a855f7', text: '#d8b4fe' },
  XRP:  { bg: '#0c4a6e', border: '#0ea5e9', text: '#7dd3fc' },
  ADA:  { bg: '#1e1b4b', border: '#6366f1', text: '#a5b4fc' },
  DOGE: { bg: '#451a03', border: '#d97706', text: '#fcd34d' },
}
const DEFAULT_COLOR = { bg: '#1f2937', border: '#4b5563', text: '#d1d5db' }

function assetColor(asset) {
  return ASSET_COLORS[asset?.toUpperCase()] ?? DEFAULT_COLOR
}

// ─── Force-directed layout (pure JS, no D3) ──────────────────────────────────
function useForceLayout(nodes, edges, width, height) {
  const [positions, setPositions] = useState({})

  useEffect(() => {
    if (!nodes.length) return

    // Seed positions in a circle
    const pos = {}
    nodes.forEach((n, i) => {
      const angle = (2 * Math.PI * i) / nodes.length
      const r = Math.min(width, height) * 0.35
      pos[n] = {
        x: width / 2 + r * Math.cos(angle),
        y: height / 2 + r * Math.sin(angle),
        vx: 0,
        vy: 0,
      }
    })

    const k = 120      // spring rest length
    const repulsion = 8000
    const damping = 0.85
    const iterations = 200

    for (let iter = 0; iter < iterations; iter++) {
      // Repulsion between all node pairs
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = pos[nodes[i]]
          const b = pos[nodes[j]]
          const dx = a.x - b.x, dy = a.y - b.y
          const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
          const force = repulsion / (dist * dist)
          a.vx += (dx / dist) * force
          a.vy += (dy / dist) * force
          b.vx -= (dx / dist) * force
          b.vy -= (dy / dist) * force
        }
      }
      // Spring attraction along edges
      edges.forEach(([u, v]) => {
        const a = pos[u], b = pos[v]
        if (!a || !b) return
        const dx = b.x - a.x, dy = b.y - a.y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const force = (dist - k) * 0.05
        a.vx += (dx / dist) * force; a.vy += (dy / dist) * force
        b.vx -= (dx / dist) * force; b.vy -= (dy / dist) * force
      })
      // Gravity toward centre
      nodes.forEach(n => {
        const p = pos[n]
        p.vx += (width / 2 - p.x) * 0.01
        p.vy += (height / 2 - p.y) * 0.01
      })
      // Apply velocity + damping
      nodes.forEach(n => {
        const p = pos[n]
        p.x += p.vx; p.y += p.vy
        p.vx *= damping; p.vy *= damping
        // Clamp to canvas
        p.x = Math.max(50, Math.min(width - 50, p.x))
        p.y = Math.max(40, Math.min(height - 40, p.y))
      })
    }

    const result = {}
    nodes.forEach(n => { result[n] = { x: pos[n].x, y: pos[n].y } })
    setPositions(result)
  }, [nodes.join(','), width, height])

  return positions
}

// ─── SVG graph component ──────────────────────────────────────────────────────
function CurrencyGraph({ adjacency, paths }) {
  const svgRef = useRef(null)
  const [svgSize, setSvgSize] = useState({ w: 700, h: 420 })
  const [hovered, setHovered] = useState(null)
  const [tooltip, setTooltip] = useState(null)

  useEffect(() => {
    const obs = new ResizeObserver(entries => {
      const e = entries[0]
      setSvgSize({ w: e.contentRect.width, h: Math.max(380, e.contentRect.width * 0.56) })
    })
    if (svgRef.current) obs.observe(svgRef.current)
    return () => obs.disconnect()
  }, [])

  // Build node + edge lists from adjacency
  const nodeSet = new Set()
  const edgeList = []
  Object.entries(adjacency ?? {}).forEach(([from, toList]) => {
    nodeSet.add(from)
    ;(toList ?? []).forEach(edge => {
      nodeSet.add(edge.to)
      edgeList.push([from, edge.to, edge])
    })
  })
  const nodes = [...nodeSet]

  // Identify profitable cycle nodes from top paths
  const profitableNodes = new Set()
  const profitableEdges = new Set()  // "FROM→TO"
  ;(paths ?? []).forEach(path => {
    if (path.net_profit_pct > 0) {
      ;(path.assets ?? []).forEach(a => profitableNodes.add(a))
      const assets = path.assets ?? []
      for (let i = 0; i < assets.length - 1; i++) {
        profitableEdges.add(`${assets[i]}→${assets[i+1]}`)
      }
    }
  })

  const positions = useForceLayout(nodes, edgeList.map(([u,v]) => [u,v]), svgSize.w, svgSize.h)

  if (!nodes.length) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-600 text-sm">
        Graph builds as workers stream price data...
      </div>
    )
  }

  const R = 28  // node radius

  function edgeColor(u, v, edge) {
    const key = `${u}→${v}`
    if (profitableEdges.has(key)) return '#22c55e'
    if (edge?.stale) return '#6b7280'
    const rate = edge?.effective_rate ?? 1
    if (rate > 1.001) return '#22c55e'
    if (rate > 0.999) return '#eab308'
    return '#ef4444'
  }

  function edgeWidth(u, v) {
    return profitableEdges.has(`${u}→${v}`) ? 2.5 : 1
  }

  const handleEdgeHover = (e, u, v, edge) => {
    const rect = svgRef.current?.getBoundingClientRect()
    setTooltip({
      x: e.clientX - (rect?.left ?? 0),
      y: e.clientY - (rect?.top ?? 0),
      text: `${u} → ${v}\nExchange: ${edge.exchange}\nRate: ×${edge.effective_rate?.toFixed(6)}\nFee: -${edge.fee_pct?.toFixed(3)}%${edge.stale ? '\n⚠ Stale data' : ''}`,
    })
  }

  return (
    <div className="relative" ref={svgRef}>
      <svg width="100%" height={svgSize.h} style={{ display: 'block' }}>
        <defs>
          <marker id="arrowGreen"  markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="#22c55e" />
          </marker>
          <marker id="arrowYellow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="#eab308" />
          </marker>
          <marker id="arrowRed"    markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="#ef4444" />
          </marker>
          <marker id="arrowGray"   markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L0,6 L6,3 z" fill="#6b7280" />
          </marker>
        </defs>

        {/* Edges */}
        {edgeList.map(([u, v, edge], i) => {
          const a = positions[u], b = positions[v]
          if (!a || !b) return null
          const color = edgeColor(u, v, edge)
          const markerId =
            color === '#22c55e' ? 'arrowGreen' :
            color === '#eab308' ? 'arrowYellow' :
            color === '#6b7280' ? 'arrowGray' : 'arrowRed'
          const dx = b.x - a.x, dy = b.y - a.y
          const dist = Math.sqrt(dx*dx + dy*dy)
          const ex = b.x - (dx/dist) * (R + 6)
          const ey = b.y - (dy/dist) * (R + 6)
          const sx = a.x + (dx/dist) * R
          const sy = a.y + (dy/dist) * R
          const isProfit = profitableEdges.has(`${u}→${v}`)
          return (
            <g key={i}>
              <line
                x1={sx} y1={sy} x2={ex} y2={ey}
                stroke={color}
                strokeWidth={edgeWidth(u, v)}
                strokeOpacity={isProfit ? 0.9 : 0.35}
                markerEnd={`url(#${markerId})`}
                className="transition-all"
              />
              {/* Invisible wide hit area for hover */}
              <line
                x1={sx} y1={sy} x2={ex} y2={ey}
                stroke="transparent"
                strokeWidth={12}
                className="cursor-pointer"
                onMouseEnter={e => handleEdgeHover(e, u, v, edge)}
                onMouseLeave={() => setTooltip(null)}
              />
              {/* Rate label on hover */}
              {hovered === `${u}-${v}` && (
                <text
                  x={(sx+ex)/2} y={(sy+ey)/2 - 6}
                  textAnchor="middle"
                  fontSize="9"
                  fill={color}
                >
                  ×{edge.effective_rate?.toFixed(5)}
                </text>
              )}
            </g>
          )
        })}

        {/* Nodes */}
        {nodes.map(n => {
          const p = positions[n]
          if (!p) return null
          const c = assetColor(n)
          const isProfit = profitableNodes.has(n)
          return (
            <g key={n} transform={`translate(${p.x},${p.y})`}
              onMouseEnter={() => setHovered(n)}
              onMouseLeave={() => setHovered(null)}
            >
              <circle r={R} fill={c.bg} stroke={c.border}
                strokeWidth={isProfit ? 2.5 : 1.5}
                opacity={hovered && hovered !== n ? 0.5 : 1}
                className="transition-all"
              />
              {isProfit && (
                <circle r={R + 5} fill="none" stroke={c.border}
                  strokeWidth={1} strokeDasharray="3 2" opacity={0.5} />
              )}
              <text textAnchor="middle" dominantBaseline="middle"
                fontSize="11" fontWeight="bold" fill={c.text} className="select-none pointer-events-none">
                {n}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Float tooltip on edge hover */}
      {tooltip && (
        <div
          className="absolute pointer-events-none bg-gray-800 border border-gray-600 rounded-lg px-3 py-2 text-xs text-gray-200 whitespace-pre shadow-xl z-40"
          style={{ left: tooltip.x + 10, top: tooltip.y - 10 }}
        >
          {tooltip.text}
        </div>
      )}

      {/* Legend */}
      <div className="flex gap-4 flex-wrap text-xs text-gray-500 mt-2 px-1">
        {[
          { color: '#22c55e', label: 'Profitable / in a cycle' },
          { color: '#eab308', label: 'Marginal (near break-even)' },
          { color: '#ef4444', label: 'Unprofitable' },
          { color: '#6b7280', label: 'Stale data' },
        ].map(({ color, label }) => (
          <span key={label} className="flex items-center gap-1.5">
            <span className="w-3 h-0.5 inline-block rounded" style={{ background: color }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── Path flow chip ───────────────────────────────────────────────────────────
function PathFlow({ assets, exchanges }) {
  return (
    <div className="flex items-center gap-1 flex-wrap my-2">
      {assets.map((asset, i) => {
        const c = assetColor(asset)
        return (
          <React.Fragment key={i}>
            <div className="px-2.5 py-1 rounded-full text-xs font-bold border"
              style={{ background: c.bg, borderColor: c.border, color: c.text }}>
              {asset}
            </div>
            {i < assets.length - 1 && (
              <div className="flex flex-col items-center">
                <span className="text-xs text-gray-600 mb-0.5">{exchanges?.[i]}</span>
                <span className="text-gray-500 text-sm">→</span>
              </div>
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

function EdgeBreakdown({ edges }) {
  if (!edges?.length) return null
  return (
    <div className="mt-3 border-t border-gray-800 pt-3">
      <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Leg-by-leg breakdown</p>
      <div className="space-y-1">
        {edges.map((e, i) => (
          <div key={i} className="flex items-center justify-between text-xs">
            <span className="text-gray-400 font-mono w-32">{e.from} → {e.to}</span>
            <span className="text-gray-500 w-20">{e.exchange}</span>
            <span className="text-gray-300 font-mono w-24">×{e.effective_rate?.toFixed(6)}</span>
            <span className="text-red-400 w-16">-{(e.fee_pct ?? 0).toFixed(3)}%</span>
            {e.gas_usd > 0 && <span className="text-orange-400 w-16">${e.gas_usd?.toFixed(2)} gas</span>}
          </div>
        ))}
      </div>
    </div>
  )
}

function PathCard({ path, rank }) {
  const [expanded, setExpanded] = useState(false)
  const isProfit = path.net_profit_pct > 0

  const profitColor =
    path.net_profit_pct > 0.5  ? 'text-green-400' :
    path.net_profit_pct > 0    ? 'text-yellow-400' : 'text-red-400'

  const borderClass =
    rank === 0 && isProfit ? 'border-green-700/60 bg-green-900/10' :
    isProfit               ? 'border-yellow-700/40 bg-yellow-900/5' :
                             'border-gray-800 bg-gray-900/50'

  return (
    <div className={`border rounded-lg p-4 mb-3 ${borderClass}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {rank === 0 && isProfit && (
            <span className="text-xs bg-green-800 text-green-300 px-2 py-0.5 rounded-full border border-green-700">BEST</span>
          )}
          <span className="text-xs text-gray-500 font-mono">#{rank + 1}</span>
          <Tip text={`${path.hops}-hop cycle: price is converted ${path.hops} times before returning to the start asset. More hops = more fees but potentially better profit.`} pos="right">
            <span className="text-xs text-gray-500 cursor-help border-b border-dashed border-gray-700">{path.hops} hops</span>
          </Tip>
          <span className="text-xs text-gray-600">
            {path.exchanges?.filter((v, i, a) => a.indexOf(v) === i).join(' + ')}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <div className="text-right">
            <Tip text={
              `Net profit after all fees and gas: ${path.net_profit_pct?.toFixed(4)}%\n` +
              `Gross: ${path.gross_profit_pct?.toFixed(4)}%\n` +
              `Fees: -${path.total_fee_pct?.toFixed(4)}%\n` +
              `Gas: -$${(path.total_gas_usd ?? 0).toFixed(2)}`
            } pos="left" wide>
              <p className={`text-lg font-bold font-mono cursor-help ${profitColor}`}>
                {isProfit ? '+' : ''}{path.net_profit_pct?.toFixed(4)}%
              </p>
              <p className="text-xs text-gray-500">${path.net_profit_usd?.toFixed(2)} net</p>
            </Tip>
          </div>
          <button onClick={() => setExpanded(!expanded)} className="text-gray-600 hover:text-gray-300 text-xs">
            {expanded ? '▲' : '▼'}
          </button>
        </div>
      </div>

      <PathFlow assets={path.assets} exchanges={path.exchanges} />

      <div className="flex gap-2 flex-wrap text-xs mt-1">
        <Tip text="Gross profit before fees — the raw product of all conversion rates minus 1.0, expressed as a percentage.">
          <span className="bg-gray-800 text-gray-400 px-2 py-0.5 rounded cursor-help">
            gross {path.gross_profit_pct?.toFixed(4)}%
          </span>
        </Tip>
        <Tip text="Total exchange fees across all legs. Typical CEX fee: 0.1% per trade. DEX: 0.3%. Higher for volatile pairs.">
          <span className="bg-red-900/30 text-red-400 px-2 py-0.5 rounded cursor-help">
            fees -{path.total_fee_pct?.toFixed(4)}%
          </span>
        </Tip>
        {path.total_gas_usd > 0 && (
          <Tip text="Gas cost for on-chain swaps (DEX legs). Deducted from net profit.">
            <span className="bg-orange-900/30 text-orange-400 px-2 py-0.5 rounded cursor-help">
              gas -${path.total_gas_usd?.toFixed(2)}
            </span>
          </Tip>
        )}
        <span className="bg-gray-800 text-gray-500 px-2 py-0.5 rounded font-mono text-xs">{path.path}</span>
      </div>

      {expanded && <EdgeBreakdown edges={path.edges} />}
    </div>
  )
}

function GraphSummary({ state }) {
  if (!state) return null
  const { summary } = state
  const summaryItems = [
    { label: 'Nodes (Assets)',  value: summary?.nodes,                      color: 'text-blue-400',   tip: 'Number of unique currency/asset nodes in the graph. Each is a vertex in the Bellman-Ford graph.' },
    { label: 'Edges (Pairs)',   value: summary?.edges,                      color: 'text-white',      tip: 'Number of directed edges. Each trading pair creates two edges (buy direction + sell direction).' },
    { label: 'Exchanges',       value: summary?.exchanges?.length,          color: 'text-purple-400', tip: 'Exchanges contributing price data to the graph.' },
    { label: 'Assets tracked',  value: summary?.assets?.join(', ') || '—', color: 'text-xs text-gray-400', tip: 'All currency/asset symbols currently in the graph.' },
  ]
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
      {summaryItems.map(({ label, value, color, tip }) => (
        <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
          <p className="text-xs text-gray-500 uppercase tracking-wider flex items-center">
            {label}
            <TipIcon text={tip} pos="bottom" wide />
          </p>
          <p className={`font-bold mt-1 ${color} ${typeof value === 'string' && value.length > 10 ? 'text-xs mt-1.5' : 'text-2xl'}`}>
            {value ?? '—'}
          </p>
        </div>
      ))}
    </div>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────
export default function GraphPanel() {
  const [showGraph, setShowGraph] = useState(true)
  const [showTable, setShowTable] = useState(false)

  const { data: pathData, loading: pathLoading } = usePolling(fetchGraphPaths,  5000)
  const { data: stateData }                       = usePolling(fetchGraphState,  10000)
  const { data: cfgData }                         = usePolling(fetchGraphConfig, 15000)

  const paths  = pathData?.paths     ?? []
  const algo   = cfgData?.algorithm  ?? pathData?.algorithm ?? 'bellman_ford'
  const fwStat = pathData?.fw_status ?? null

  if (pathLoading) return <Card title="Graph Arbitrage"><Spinner /></Card>

  return (
    <div className="space-y-4">
      <GraphSummary state={stateData} />

      {/* Live config strip */}
      {cfgData && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl px-5 py-3 flex flex-wrap gap-x-6 gap-y-2 text-xs">
          <Tip text="Active graph algorithm. bellman_ford runs every ~5s from each node. floyd_warshall runs on a schedule and finds all pairs simultaneously. Change with GRAPH_ALGORITHM in .env then hit Reload Brain Config." pos="bottom" wide>
            <span className="text-gray-500 cursor-help">
              Algorithm: <span className={`font-mono font-bold ${algo === 'floyd_warshall' ? 'text-blue-400' : 'text-green-400'}`}>{algo}</span>
            </span>
          </Tip>
          {fwStat && (
            <Tip text={`Floyd-Warshall runs every ${fwStat.interval_s}s as a scheduled deep scan. It finds every profitable cycle simultaneously in O(V³). Last ran ${fwStat.last_run_ago}s ago.`} pos="bottom" wide>
              <span className="text-gray-500 cursor-help">
                FW in: <span className="text-gray-300 font-mono">{Math.max(0, fwStat.interval_s - (fwStat.last_run_ago ?? 0)).toFixed(0)}s</span>
              </span>
            </Tip>
          )}
          <Tip text="Minimum net profit % after all fees and gas required to surface a cycle. Set GRAPH_MIN_SPREAD_PCT in .env." pos="bottom">
            <span className="text-gray-500 cursor-help">
              Min profit: <span className="text-gray-300 font-mono">{cfgData.min_profit_pct}%</span>
            </span>
          </Tip>
          <Tip text="Cycle hop range. 3 = triangular (A→B→C→A). 5 = complex multi-exchange path. Set GRAPH_MIN_HOPS / GRAPH_MAX_HOPS." pos="bottom">
            <span className="text-gray-500 cursor-help">
              Hops: <span className="text-gray-300 font-mono">{cfgData.min_hops}–{cfgData.max_hops}</span>
            </span>
          </Tip>
          <Tip text="Edges older than this are pruned before each scan. Set GRAPH_STALE_EDGE_S." pos="bottom">
            <span className="text-gray-500 cursor-help">
              Stale: <span className="text-gray-300 font-mono">{cfgData.stale_edge_s}s</span>
            </span>
          </Tip>
          <Tip text="Hub assets used as preferred bridge nodes. Cycles through these are prioritised. Set GRAPH_HUB_ASSETS." pos="bottom" wide>
            <span className="text-gray-500 cursor-help">
              Hubs: <span className="text-gray-300 font-mono">{(cfgData.hub_assets ?? []).join(', ')}</span>
            </span>
          </Tip>
          {cfgData.fees_pct && (
            <Tip text="Per-exchange taker fee used in edge weight calculations. These are what actually determines whether a path is profitable. Set FEE_{EXCHANGE}_PCT in .env and reload." pos="bottom" wide>
              <span className="text-gray-500 cursor-help">
                Fees: <span className="text-gray-300 font-mono">
                  {Object.entries(cfgData.fees_pct)
                    .filter(([, v]) => v > 0)
                    .map(([ex, fee]) => `${ex}=${fee}%`)
                    .join(' · ')}
                </span>
              </span>
            </Tip>
          )}
        </div>
      )}

      {/* Live graph visualization */}
      {stateData?.adjacency && (
        <Card
          title="Currency Graph"
          subtitle="Live node-link diagram — edges colour-coded by profitability"
          action={
            <button
              onClick={() => setShowGraph(v => !v)}
              className="text-xs text-gray-500 hover:text-gray-300 bg-gray-800 px-3 py-1.5 rounded border border-gray-700"
            >
              {showGraph ? 'Hide graph' : 'Show graph'}
            </button>
          }
        >
          {showGraph && (
            <CurrencyGraph
              adjacency={stateData.adjacency}
              paths={paths}
            />
          )}
        </Card>
      )}

      {/* Profitable paths */}
      <Card
        title="Multi-Hop Arbitrage Paths"
        subtitle={`${paths.length} profitable cycles detected · algorithm: ${algo}`}
        action={
          <div className="flex gap-2 items-center">
            <TipIcon
              text="Paths are detected by Bellman-Ford on -log(rate) edge weights. A negative-weight cycle = profitable arbitrage. Ranked by net profit after all fees and gas."
              pos="left" wide
            />
            <button
              onClick={() => setShowTable(v => !v)}
              className="text-xs text-gray-500 hover:text-gray-300 bg-gray-800 px-3 py-1.5 rounded border border-gray-700"
            >
              {showTable ? 'Hide raw edges' : 'Show raw edges'}
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

      {/* Raw adjacency table */}
      {showTable && stateData?.adjacency && (
        <Card title="Currency Graph — Raw Edges" subtitle="All live edges with effective rates">
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-gray-800">
                  {['From', 'To', 'Exchange', 'Effective Rate', 'Fee', 'Status'].map(h => (
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

      {/* Explainer */}
      <Card title="How Graph Arbitrage Works">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs text-gray-400">
          <div>
            <p className="text-gray-200 font-medium mb-1">1 — Build the Graph</p>
            <p>Every price tick adds directed edges to the currency graph. Fees, slippage, and gas are baked into each edge weight. The graph shows all live exchange rates as a connected network.</p>
          </div>
          <div>
            <p className="text-gray-200 font-medium mb-1">2 — Run Bellman-Ford</p>
            <p>Edge weights are transformed as -log(rate). A negative-weight cycle means the product of conversion rates &gt; 1.0 — a profitable path. Bellman-Ford detects these in O(V×E) time.</p>
          </div>
          <div>
            <p className="text-gray-200 font-medium mb-1">3 — Validate & Rank</p>
            <p>Each path is checked for liquidity, data freshness, and transfer feasibility. Surviving paths are ranked by net profit after all costs. <span className="text-green-400">Green edges</span> = part of a profitable cycle.</p>
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
