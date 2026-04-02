import React, { useState, useEffect, useRef } from 'react'
import { Card, Spinner, EmptyState } from './ui'
import { usePolling } from '../utils/api'

const fetchEvents = (category = '', level = '', limit = 300) =>
  fetch(`/api/events?limit=${limit}${category ? `&category=${category}` : ''}${level ? `&level=${level}` : ''}`)
    .then(r => r.json())

// ── Category config ──────────────────────────────────────────────────────────
const CATEGORIES = [
  { id: 'ALL',    label: '🌐 All',       color: 'text-gray-300' },
  { id: 'ARBIT',  label: '🕸 Arb',       color: 'text-green-400' },
  { id: 'CR9AM',  label: '🕘 9AM CR',    color: 'text-blue-400'  },
  { id: 'SYSTEM', label: '⚙️ System',    color: 'text-purple-400'},
  { id: 'RISK',   label: '🛡 Risk',      color: 'text-red-400'   },
  { id: 'TRADE',  label: '💹 Trade',     color: 'text-yellow-400'},
]

const LEVEL_STYLE = {
  SUCCESS: { bg: 'bg-green-900/30',  border: 'border-green-700/40',  dot: 'bg-green-400',  text: 'text-green-300'  },
  INFO:    { bg: 'bg-gray-900/40',   border: 'border-gray-700/40',   dot: 'bg-gray-500',   text: 'text-gray-400'   },
  WARNING: { bg: 'bg-yellow-900/20', border: 'border-yellow-700/40', dot: 'bg-yellow-400', text: 'text-yellow-300' },
  ERROR:   { bg: 'bg-red-900/25',    border: 'border-red-700/40',    dot: 'bg-red-500',    text: 'text-red-300'    },
}

const CAT_STYLE = {
  ARBIT:  'text-green-400  bg-green-900/30  border-green-700/40',
  CR9AM:  'text-blue-400   bg-blue-900/30   border-blue-700/40',
  SYSTEM: 'text-purple-400 bg-purple-900/30 border-purple-700/40',
  RISK:   'text-red-400    bg-red-900/30    border-red-700/40',
  TRADE:  'text-yellow-400 bg-yellow-900/30 border-yellow-700/40',
}

// ── Single event row ─────────────────────────────────────────────────────────
function EventRow({ ev }) {
  const [open, setOpen] = useState(false)
  const ls = LEVEL_STYLE[ev.level] || LEVEL_STYLE.INFO
  const ts = new Date(ev.ts * 1000)
  const timeStr = ts.toLocaleTimeString('en-US', { hour12: false })
  const dateStr = ts.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  const catStyle = CAT_STYLE[ev.category] || 'text-gray-400 bg-gray-800 border-gray-700'

  const hasData = ev.data && Object.keys(ev.data).length > 0

  return (
    <div
      className={`border rounded-lg px-3 py-2 mb-1.5 transition-all ${ls.bg} ${ls.border} ${hasData ? 'cursor-pointer hover:brightness-110' : ''}`}
      onClick={() => hasData && setOpen(o => !o)}
    >
      <div className="flex items-start gap-2.5">
        {/* Level dot */}
        <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${ls.dot}`} />

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            {/* Category badge */}
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${catStyle}`}>
              {ev.category}
            </span>
            {/* Title */}
            <span className={`text-xs font-medium ${ls.text}`}>{ev.title}</span>
            {/* Expand hint */}
            {hasData && (
              <span className="text-[10px] text-gray-600 ml-auto">
                {open ? '▲ hide' : '▼ details'}
              </span>
            )}
          </div>

          {/* Detail line */}
          {ev.detail && (
            <p className="text-[11px] text-gray-400 mt-0.5 leading-relaxed">{ev.detail}</p>
          )}

          {/* Expanded data */}
          {open && hasData && (
            <div className="mt-2 bg-gray-950/60 rounded p-2 font-mono text-[10px] text-gray-400 overflow-x-auto">
              {Object.entries(ev.data).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <span className="text-gray-600 shrink-0 w-24">{k}:</span>
                  <span className="text-gray-300 break-all">
                    {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Timestamp */}
        <div className="text-[10px] text-gray-600 text-right shrink-0 font-mono">
          <div>{timeStr}</div>
          <div>{dateStr}</div>
        </div>
      </div>
    </div>
  )
}

// ── Stats bar ────────────────────────────────────────────────────────────────
function StatsBar({ stats }) {
  if (!stats) return null
  return (
    <div className="flex gap-3 flex-wrap text-xs mb-3">
      {CATEGORIES.filter(c => c.id !== 'ALL').map(cat => {
        const count = stats[cat.id] ?? 0
        return (
          <span key={cat.id} className={`${cat.color} font-mono`}>
            {cat.label} <span className="text-gray-500">({count})</span>
          </span>
        )
      })}
    </div>
  )
}

// ── Main panel ───────────────────────────────────────────────────────────────
export default function FinancialEventsPanel() {
  const [category, setCategory] = useState('ALL')
  const [level,    setLevel]    = useState('ALL')
  const [paused,   setPaused]   = useState(false)
  const [events,   setEvents]   = useState([])
  const [stats,    setStats]    = useState(null)
  const [lastId,   setLastId]   = useState(0)
  const pausedRef = useRef(false)
  pausedRef.current = paused

  // Poll for new events every 3 seconds
  useEffect(() => {
    let cancelled = false

    const load = async () => {
      try {
        const cat = category === 'ALL' ? '' : category
        const lvl = level    === 'ALL' ? '' : level
        const data = await fetchEvents(cat, lvl, 300)
        if (!cancelled && !pausedRef.current) {
          setEvents(data.events ?? [])
          setStats(data.stats  ?? null)
        }
      } catch {}
    }

    load()
    const id = setInterval(load, 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [category, level])

  const levels = ['ALL', 'SUCCESS', 'INFO', 'WARNING', 'ERROR']

  return (
    <div className="space-y-4">
      {/* Stats summary */}
      <Card>
        <StatsBar stats={stats} />
        <div className="flex items-center gap-2 flex-wrap">
          {/* Category tabs */}
          <div className="flex gap-1 flex-wrap">
            {CATEGORIES.map(cat => (
              <button
                key={cat.id}
                onClick={() => setCategory(cat.id)}
                className={`text-xs px-2.5 py-1 rounded transition-colors
                  ${category === cat.id
                    ? 'bg-green-700 text-white font-medium'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
              >
                {cat.label}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-gray-700 mx-1" />

          {/* Level filter */}
          <div className="flex gap-1">
            {levels.map(l => (
              <button
                key={l}
                onClick={() => setLevel(l)}
                className={`text-xs px-2 py-1 rounded transition-colors
                  ${level === l
                    ? 'bg-indigo-700 text-white'
                    : 'bg-gray-800 text-gray-500 hover:bg-gray-700'}`}
              >
                {l}
              </button>
            ))}
          </div>

          <div className="ml-auto flex gap-2">
            <button
              onClick={() => setPaused(p => !p)}
              className={`text-xs px-3 py-1 rounded border transition-colors
                ${paused
                  ? 'border-yellow-600 text-yellow-400 bg-yellow-900/20'
                  : 'border-gray-600 text-gray-400 hover:border-gray-500'}`}
            >
              {paused ? '▶ Resume' : '⏸ Pause'}
            </button>
            <button
              onClick={() => setEvents([])}
              className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-500 hover:text-gray-300"
            >
              Clear
            </button>
          </div>
        </div>
      </Card>

      {/* Event feed */}
      <Card
        title="Event Feed"
        subtitle={`${events.length} events${paused ? ' · paused' : ''}`}
      >
        <div className="max-h-[700px] overflow-y-auto pr-1">
          {events.length === 0 ? (
            <EmptyState
              icon="📡"
              message="No events yet. Events are emitted when arbitrage cycles are detected, 9AM sessions fire, workers connect, or risk limits trigger."
            />
          ) : (
            events.map(ev => <EventRow key={ev.id} ev={ev} />)
          )}
        </div>
      </Card>
    </div>
  )
}
