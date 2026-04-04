import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Card } from './ui'

const LEVEL_COLOR = {
  DEBUG:    { text: 'text-gray-600', bg: '' },
  INFO:     { text: 'text-gray-400', bg: '' },
  WARNING:  { text: 'text-yellow-400', bg: 'bg-yellow-900/10' },
  ERROR:    { text: 'text-red-400',    bg: 'bg-red-900/15' },
  CRITICAL: { text: 'text-red-300',    bg: 'bg-red-900/25' },
}

const LEVELS = ['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG']

function LogLine({ line, searchTerm }) {
  const lc = LEVEL_COLOR[line.level] || LEVEL_COLOR.INFO

  const highlight = (text) => {
    if (!searchTerm || !text) return text
    const parts = text.split(new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'))
    return parts.map((p, i) =>
      p.toLowerCase() === searchTerm.toLowerCase()
        ? <mark key={i} className="bg-yellow-500/30 text-yellow-200 rounded px-0.5">{p}</mark>
        : p
    )
  }

  const copyLine = (e) => {
    e.stopPropagation()
    const text = `[${line.ts}] ${line.level} ${line.logger} — ${line.message}`
    navigator.clipboard?.writeText(text).catch(() => {})
  }

  return (
    <div className={`group flex gap-2 py-0.5 px-1 rounded hover:bg-gray-900/60 text-xs ${lc.bg}`}>
      <span className="text-gray-700 shrink-0 w-20 font-mono tabular-nums">
        {line.ts ? new Date(line.ts).toLocaleTimeString('en-US', { hour12: false }) : ''}
      </span>
      <span className={`shrink-0 w-14 font-semibold ${lc.text}`}>{line.level}</span>
      <span className="text-gray-600 shrink-0 w-36 truncate font-mono" title={line.logger}>{line.logger}</span>
      <span className={`flex-1 min-w-0 break-words ${lc.text === 'text-gray-400' ? 'text-gray-300' : lc.text}`}>
        {highlight(line.message)}
      </span>
      <button onClick={copyLine}
        className="shrink-0 opacity-0 group-hover:opacity-100 text-gray-600 hover:text-gray-300 transition-opacity text-[10px] px-1"
        title="Copy line">⎘</button>
    </div>
  )
}

export default function LogViewerPanel() {
  const [lines,        setLines]        = useState([])
  const [filter,       setFilter]       = useState('ALL')
  const [search,       setSearch]       = useState('')
  const [loggerFilter, setLoggerFilter] = useState('')
  const [paused,       setPaused]       = useState(false)
  const [autoScroll,   setAutoScroll]   = useState(true)
  const [status,       setStatus]       = useState('connecting')
  const bottomRef = useRef(null)
  const scrollRef = useRef(null)
  const pausedRef = useRef(false)
  pausedRef.current = paused

  const loggers = [...new Set(lines.map(l => l.logger).filter(Boolean))].sort()

  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const ws    = new WebSocket(`${proto}://${window.location.host}/api/ws/logs`)
    ws.onopen    = () => setStatus('connected')
    ws.onclose   = () => setStatus('disconnected')
    ws.onerror   = () => setStatus('error')
    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.ping) return
        if (pausedRef.current) return
        setLines(prev => {
          const next = [...prev, msg]
          return next.length > 2000 ? next.slice(-1500) : next
        })
      } catch {}
    }
    return () => ws.close()
  }, [])

  useEffect(() => {
    if (autoScroll && !paused) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, autoScroll, paused])

  const onScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }, [])

  const filtered = lines.filter(l => {
    if (filter !== 'ALL' && l.level !== filter) return false
    if (loggerFilter && l.logger !== loggerFilter) return false
    if (search && !l.message?.toLowerCase().includes(search.toLowerCase()) &&
        !l.logger?.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  const copyAll = () => {
    const text = filtered.map(l => `[${l.ts}] ${l.level} ${l.logger} — ${l.message}`).join('\n')
    navigator.clipboard?.writeText(text).catch(() => {})
  }

  const errorCount   = lines.filter(l => l.level === 'ERROR' || l.level === 'CRITICAL').length
  const warningCount = lines.filter(l => l.level === 'WARNING').length

  return (
    <Card
      title="Live Log Viewer"
      subtitle={
        <span className="flex items-center gap-3">
          <span>{lines.length} lines</span>
          {errorCount   > 0 && <span className="text-red-400 font-medium">{errorCount} error{errorCount !== 1 ? 's' : ''}</span>}
          {warningCount > 0 && <span className="text-yellow-400">{warningCount} warn{warningCount !== 1 ? 's' : ''}</span>}
        </span>
      }
      action={
        <div className="flex items-center gap-2 flex-wrap justify-end">
          <span className={`text-xs px-2 py-0.5 rounded-full border ${
            status === 'connected'
              ? 'text-green-400 border-green-800 bg-green-900/30'
              : 'text-red-400 border-red-800 bg-red-900/20'
          }`}>
            {status === 'connected' ? '● live' : `● ${status}`}
          </span>
          <div className="flex gap-1">
            {LEVELS.map(l => (
              <button key={l} onClick={() => setFilter(l)}
                className={`text-xs px-2 py-1 rounded transition-colors
                  ${filter === l ? 'bg-green-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
                {l}
              </button>
            ))}
          </div>
          <button onClick={() => setPaused(p => !p)}
            className={`text-xs px-3 py-1 rounded border transition-colors ${
              paused ? 'border-yellow-600 text-yellow-400 bg-yellow-900/20' : 'border-gray-600 text-gray-400'
            }`}>
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <button onClick={copyAll}
            className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-500 hover:text-gray-300"
            title="Copy all visible lines">⎘ Copy</button>
          <button onClick={() => setLines([])}
            className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-500 hover:text-red-400">
            ✕ Clear</button>
        </div>
      }
    >
      {/* Search + logger filter */}
      <div className="flex gap-2 mb-2">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search messages…"
          className="flex-1 bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-gray-500"
        />
        <select
          value={loggerFilter}
          onChange={e => setLoggerFilter(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded px-2 py-1 text-xs text-gray-400 focus:outline-none focus:border-gray-500 max-w-[180px]"
        >
          <option value="">All loggers</option>
          {loggers.map(l => <option key={l} value={l}>{l}</option>)}
        </select>
        {(search || loggerFilter) && (
          <button onClick={() => { setSearch(''); setLoggerFilter('') }}
            className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-500 hover:text-gray-300">✕</button>
        )}
        <span className="text-xs text-gray-600 self-center whitespace-nowrap">
          {filtered.length}{lines.length !== filtered.length ? `/${lines.length}` : ''} lines
        </span>
      </div>

      {/* Log output */}
      <div ref={scrollRef} onScroll={onScroll}
        className="bg-gray-950 rounded-lg p-2 font-mono text-xs h-[520px] overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="text-gray-700 p-2">
            {lines.length === 0
              ? 'Waiting for log output… (WebSocket connecting)'
              : 'No lines match the current filters.'}
          </p>
        ) : (
          filtered.map((line, i) => <LogLine key={i} line={line} searchTerm={search} />)
        )}
        <div ref={bottomRef} />
      </div>

      {!autoScroll && !paused && (
        <button
          onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }}
          className="mt-1 text-xs text-gray-500 hover:text-gray-300 w-full text-center py-1">
          ↓ Jump to latest
        </button>
      )}
    </Card>
  )
}
