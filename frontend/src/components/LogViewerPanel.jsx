import React, { useState, useEffect, useRef } from 'react'
import { Card } from './ui'

const LEVEL_COLOR = {
  DEBUG:    'text-gray-600',
  INFO:     'text-gray-400',
  WARNING:  'text-yellow-400',
  ERROR:    'text-red-400',
  CRITICAL: 'text-red-300',
}

export default function LogViewerPanel() {
  const [lines,   setLines]   = useState([])
  const [filter,  setFilter]  = useState('ALL')
  const [paused,  setPaused]  = useState(false)
  const [status,  setStatus]  = useState('connecting')
  const bottomRef             = useRef(null)
  const pausedRef             = useRef(false)

  pausedRef.current = paused

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
          return next.length > 1000 ? next.slice(-800) : next
        })
      } catch {}
    }

    return () => ws.close()
  }, [])

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines, paused])

  const filtered = filter === 'ALL' ? lines : lines.filter(l => l.level === filter)

  return (
    <Card
      title="Live Log Viewer"
      subtitle={`${lines.length} lines`}
      action={
        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full border ${
            status === 'connected' ? 'text-green-400 border-green-800 bg-green-900/30' : 'text-red-400 border-red-800'
          }`}>
            {status === 'connected' ? '● live' : status}
          </span>
          {['ALL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'].map(l => (
            <button key={l} onClick={() => setFilter(l)}
              className={`text-xs px-2 py-1 rounded ${filter === l ? 'bg-green-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
              {l}
            </button>
          ))}
          <button onClick={() => setPaused(p => !p)}
            className={`text-xs px-3 py-1 rounded border transition-colors ${
              paused ? 'border-yellow-600 text-yellow-400 bg-yellow-900/20' : 'border-gray-600 text-gray-400'
            }`}>
            {paused ? '▶ Resume' : '⏸ Pause'}
          </button>
          <button onClick={() => setLines([])}
            className="text-xs px-2 py-1 rounded bg-gray-800 text-gray-500 hover:text-gray-300">
            Clear
          </button>
        </div>
      }
    >
      <div className="bg-gray-950 rounded-lg p-3 font-mono text-xs h-[500px] overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="text-gray-700">Waiting for log output...</p>
        ) : (
          filtered.map((line, i) => (
            <div key={i} className="flex gap-3 py-0.5 hover:bg-gray-900/40 rounded">
              <span className="text-gray-700 shrink-0 w-20">
                {line.ts ? new Date(line.ts).toLocaleTimeString() : ''}
              </span>
              <span className={`shrink-0 w-16 ${LEVEL_COLOR[line.level] || 'text-gray-500'}`}>
                {line.level}
              </span>
              <span className="text-gray-600 shrink-0 w-40 truncate">{line.logger}</span>
              <span className={LEVEL_COLOR[line.level] || 'text-gray-400'}>{line.message}</span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </Card>
  )
}
