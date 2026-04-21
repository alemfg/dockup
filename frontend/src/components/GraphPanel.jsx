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
// ─── Cycle-only isolated path visualizer ──────────────────────────────────────
// Renders a single arbitrage cycle as a clean circular diagram, no noise.
function CycleGraph({ path, width = 500 }) {
  if (!path?.assets?.length) return null
  const assets  = path.assets.slice(0, -1) // remove closing repeat
  const n       = assets.length
  const cx      = width / 2
  const cy      = 110
  const r       = Math.min(80, (width * 0.35))
  const nodeR   = 26

  const pts = assets.map((_, i) => {
    const angle = (2 * Math.PI * i) / n - Math.PI / 2
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }
  })

  return (
    <svg width="100%" height={cy * 2 + 20} viewBox={`0 0 ${width} ${cy * 2 + 20}`}>
      <defs>
        <marker id="cycleArrow" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L0,6 L6,3 z" fill="#22c55e" />
        </marker>
      </defs>
      {/* Edges */}
      {assets.map((_, i) => {
        const from  = pts[i]
        const to    = pts[(i + 1) % n]
        const dx    = to.x - from.x
        const dy    = to.y - from.y
        const dist  = Math.sqrt(dx * dx + dy * dy)
        const sx    = from.x + (dx / dist) * nodeR
        const sy    = from.y + (dy / dist) * nodeR
        const ex    = to.x - (dx / dist) * (nodeR + 5)
        const ey    = to.y - (dy / dist) * (nodeR + 5)
        const edge  = path.edges?.[i]
        const midX  = (sx + ex) / 2
        const midY  = (sy + ey) / 2 - 10
        return (
          <g key={i}>
            <line x1={sx} y1={sy} x2={ex} y2={ey}
              stroke="#22c55e" strokeWidth="2"
              markerEnd="url(#cycleArrow)" strokeOpacity="0.85" />
            {/* Exchange label on edge */}
            <text x={midX} y={midY} textAnchor="middle" fontSize="8" fill="#4ade80" opacity="0.8">
              {edge?.exchange ?? ''}
            </text>
            {/* Rate label */}
            <text x={midX} y={midY + 10} textAnchor="middle" fontSize="7" fill="#6b7280">
              ×{edge?.effective_rate?.toFixed(5) ?? ''}
            </text>
          </g>
        )
      })}
      {/* Nodes */}
      {assets.map((asset, i) => {
        const p = pts[i]
        const c = assetColor(asset)
        return (
          <g key={asset} transform={`translate(${p.x},${p.y})`}>
            <circle r={nodeR} fill={c.bg} stroke={c.border} strokeWidth="2" />
            <text textAnchor="middle" dominantBaseline="middle"
              fontSize="10" fontWeight="bold" fill={c.text} className="select-none">
              {asset}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

function CurrencyGraph({ adjacency, paths, isolateCycle }) {
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

  // Identify profitable cycle nodes from top paths
  const profitableNodes = new Set()
  const profitableEdges = new Set()
  ;(paths ?? []).forEach(path => {
    if (path.net_profit_pct > 0) {
      ;(path.assets ?? []).forEach(a => profitableNodes.add(a))
      const assets = path.assets ?? []
      for (let i = 0; i < assets.length - 1; i++) {
        profitableEdges.add(`${assets[i]}→${assets[i+1]}`)
      }
    }
  })

  // When isolateCycle is on: only show nodes/edges that participate in profitable cycles
  const fullNodeSet = new Set()
  const fullEdgeList = []
  Object.entries(adjacency ?? {}).forEach(([from, toList]) => {
    fullNodeSet.add(from)
    ;(toList ?? []).forEach(edge => {
      fullNodeSet.add(edge.to)
      fullEdgeList.push([from, edge.to, edge])
    })
  })

  const nodeSet = isolateCycle
    ? new Set([...fullNodeSet].filter(n => profitableNodes.has(n)))
    : fullNodeSet
  const edgeList = isolateCycle
    ? fullEdgeList.filter(([u, v]) => profitableNodes.has(u) && profitableNodes.has(v))
    : fullEdgeList
  const nodes = [...nodeSet]

  const positions = useForceLayout(nodes, edgeList.map(([u,v]) => [u,v]), svgSize.w, svgSize.h)

  if (!nodes.length) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-600 text-sm">
        {isolateCycle ? 'No profitable cycles to isolate — waiting for graph data...' : 'Graph builds as workers stream price data...'}
      </div>
    )
  }

  const R = 28

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
  const now = Date.now()
  return (
    <div className="mt-3 border-t border-gray-800 pt-3">
      <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Leg-by-leg breakdown</p>
      <div className="space-y-2">
        {edges.map((e, i) => {
          const ageS = e.timestamp
            ? Math.round((now - new Date(e.timestamp).getTime()) / 1000)
            : null
          const isEdgeStale = ageS !== null && ageS > 25
          return (
            <div key={i} className={`rounded p-2 text-xs border ${isEdgeStale ? 'border-yellow-900/50 bg-yellow-900/10' : 'border-gray-800/60 bg-gray-900/40'}`}>
              <div className="flex items-center justify-between gap-2 flex-wrap">
                {/* Leg label */}
                <span className="text-gray-300 font-mono font-semibold w-28 shrink-0">
                  {e.from} → {e.to}
                </span>
                {/* Exchange */}
                <span className="text-gray-500 w-20 shrink-0 capitalize">{e.exchange}</span>
                {/* Rate */}
                <span className="text-gray-200 font-mono w-28 shrink-0">
                  ×{e.effective_rate?.toFixed(6)}
                </span>
                {/* Fee */}
                <span className="text-red-400 w-14 shrink-0">
                  -{(e.fee_pct ?? (e.fee ?? 0) * 100).toFixed(3)}%
                </span>
                {/* Gas */}
                {e.gas_usd > 0 && (
                  <span className="text-orange-400 w-16 shrink-0">${e.gas_usd?.toFixed(2)} gas</span>
                )}
                {/* Age */}
                <span className={`ml-auto font-mono shrink-0 ${isEdgeStale ? 'text-yellow-400' : 'text-gray-600'}`}>
                  {ageS !== null ? (isEdgeStale ? `⚠ ${ageS}s ago` : `${ageS}s ago`) : '—'}
                </span>
              </div>
              {/* Raw rate vs effective */}
              <div className="flex gap-4 mt-1 text-[10px] text-gray-600">
                <span>raw: ×{e.rate?.toFixed(6)}</span>
                <span>slippage: -{((e.slippage ?? 0) * 100).toFixed(3)}%</span>
                {e.log_weight != null && <span>log_w: {e.log_weight?.toFixed(4)}</span>}
              </div>
            </div>
          )
        })}
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
        {path.is_stale && (
          <Tip text={`Oldest edge in this path is ${path.max_edge_age_s?.toFixed(0)}s old. Stale prices may not reflect current market — treat this opportunity with caution.`} pos="right">
            <span className="bg-yellow-900/40 text-yellow-400 border border-yellow-800/60 px-2 py-0.5 rounded text-xs cursor-help">
              ⚠ stale data ({path.max_edge_age_s?.toFixed(0)}s)
            </span>
          </Tip>
        )}
      </div>

      {expanded && (
        <>
          {/* Isolated cycle diagram */}
          {path.assets?.length > 0 && (
            <div className="mt-3 border-t border-gray-800 pt-3">
              <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Cycle diagram</p>
              <CycleGraph path={path} />
            </div>
          )}
          {/* Step-by-step action guide */}
          {path.edges?.length > 0 && (
            <div className="mt-3 border-t border-gray-800 pt-3">
              <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Execution steps</p>
              <div className="space-y-1.5">
                {path.edges.map((e, i) => {
                  const isBuy  = i === 0
                  const isSell = i === path.edges.length - 1
                  const action = isBuy ? 'BUY' : isSell ? 'SELL' : 'SWAP'
                  const actionColor = isBuy ? 'text-green-400' : isSell ? 'text-red-400' : 'text-blue-400'
                  const transfer = i > 0 && e.exchange !== path.edges[i - 1]?.exchange
                  return (
                    <div key={i}>
                      {transfer && (
                        <div className="flex items-center gap-2 text-[10px] text-yellow-500/80 py-0.5 px-2">
                          <span>⟳</span>
                          <span>Transfer {path.assets[i]} from <span className="font-mono">{path.edges[i-1]?.exchange}</span> → <span className="font-mono">{e.exchange}</span></span>
                        </div>
                      )}
                      <div className="flex items-center gap-2 text-xs bg-gray-900/60 rounded px-3 py-1.5 border border-gray-800/50">
                        <span className="text-gray-500 font-mono w-4 shrink-0">{i+1}.</span>
                        <span className={`font-bold w-10 shrink-0 ${actionColor}`}>{action}</span>
                        <span className="text-gray-200 font-mono shrink-0">{e.from} → {e.to}</span>
                        <span className="text-gray-500 mx-1">on</span>
                        <span className="text-gray-300 capitalize shrink-0">{e.exchange}</span>
                        <span className="ml-auto font-mono text-gray-400">×{e.effective_rate?.toFixed(6)}</span>
                        <span className="text-red-400 text-[10px] w-14 text-right shrink-0">-{((e.fee ?? 0)*100).toFixed(3)}%</span>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
          <EdgeBreakdown edges={path.edges} />
        </>
      )}
    </div>
  )
}

function GraphSummary({ state }) {
  if (!state) return null
  const { summary } = state
  const [showAssets, setShowAssets] = React.useState(false)
  const assets = summary?.assets ?? []

  const statCards = [
    { label: 'Nodes (Assets)',  value: summary?.nodes,             color: 'text-blue-400',   tip: 'Unique asset nodes in the graph. Each is a vertex in the Bellman-Ford algorithm.' },
    { label: 'Edges (Pairs)',   value: summary?.edges,             color: 'text-white',      tip: 'Directed edges — each trading pair creates two edges (buy + sell direction).' },
    { label: 'Exchanges',       value: summary?.exchanges?.length, color: 'text-purple-400', tip: 'Exchanges contributing live price data to the graph.' },
  ]

  return (
    <div className="mb-4 space-y-3">
      {/* Stat cards row */}
      <div className="grid grid-cols-3 gap-3">
        {statCards.map(({ label, value, color, tip }) => (
          <div key={label} className="bg-gray-900 border border-gray-800 rounded-xl p-4">
            <p className="text-xs text-gray-500 uppercase tracking-wider flex items-center">
              {label}
              <TipIcon text={tip} pos="bottom" wide />
            </p>
            <p className={`font-bold mt-1 text-2xl ${color}`}>{value ?? '—'}</p>
          </div>
        ))}
      </div>

      {/* Assets tracked — collapsible */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl px-4 py-3">
        <button
          onClick={() => setShowAssets(v => !v)}
          className="w-full flex items-center justify-between text-left"
        >
          <span className="text-xs text-gray-500 uppercase tracking-wider">
            Assets tracked
            <span className="ml-2 text-gray-400 font-mono normal-case">{assets.length}</span>
          </span>
          <span className="text-gray-600 text-xs">{showAssets ? '▲ hide' : '▼ show all'}</span>
        </button>

        {/* Always show first 12 as chips */}
        <div className="flex flex-wrap gap-1 mt-2">
          {(showAssets ? assets : assets.slice(0, 12)).map(a => (
            <span key={a} className="text-[10px] font-mono px-1.5 py-0.5 bg-gray-800 text-gray-400 rounded">
              {a}
            </span>
          ))}
          {!showAssets && assets.length > 12 && (
            <button
              onClick={() => setShowAssets(true)}
              className="text-[10px] px-1.5 py-0.5 bg-gray-800 text-blue-400 rounded hover:bg-gray-700"
            >
              +{assets.length - 12} more
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main panel ───────────────────────────────────────────────────────────────
export default function GraphPanel() {
  const [showGraph,    setShowGraph]    = useState(true)
  const [showTable,    setShowTable]    = useState(false)
  const [isolateCycle, setIsolateCycle] = useState(false)

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
          subtitle={isolateCycle ? 'Showing only nodes in profitable cycles' : 'Live node-link diagram — edges colour-coded by profitability'}
          action={
            <div className="flex gap-2">
              <button
                onClick={() => setIsolateCycle(v => !v)}
                className={`text-xs px-3 py-1.5 rounded border transition-colors ${
                  isolateCycle
                    ? 'bg-green-800 border-green-600 text-green-200'
                    : 'text-gray-500 hover:text-gray-300 bg-gray-800 border-gray-700'
                }`}
                title="Show only nodes that participate in a profitable cycle"
              >
                {isolateCycle ? '⚡ Cycles only' : '⚡ Isolate cycles'}
              </button>
              <button
                onClick={() => setShowGraph(v => !v)}
                className="text-xs text-gray-500 hover:text-gray-300 bg-gray-800 px-3 py-1.5 rounded border border-gray-700"
              >
                {showGraph ? 'Hide graph' : 'Show graph'}
              </button>
            </div>
          }
        >
          {showGraph && (
            <CurrencyGraph
              adjacency={stateData.adjacency}
              paths={paths}
              isolateCycle={isolateCycle}
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
