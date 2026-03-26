import React, { useState } from 'react'
import { usePolling, fetchFleetEvents } from '../utils/api'
import { Card, EmptyState, Spinner } from './ui'

const LEVEL_STYLES = {
  WARNING:  { dot: 'bg-yellow-400', text: 'text-yellow-400', label: '⚠' },
  ERROR:    { dot: 'bg-red-500',    text: 'text-red-400',    label: '✖' },
  CRITICAL: { dot: 'bg-red-600',    text: 'text-red-300',    label: '🔴' },
  INFO:     { dot: 'bg-gray-500',   text: 'text-gray-400',   label: '●' },
}

export default function EventLog() {
  const [filter, setFilter] = useState('ALL')
  const { data, loading } = usePolling(() => fetchFleetEvents(200), 5000)

  if (loading) return <Card title="Event Log"><Spinner /></Card>

  const events = data?.events ?? []
  const filtered = filter === 'ALL' ? events : events.filter(e => e.level === filter)

  const counts = {
    WARNING:  events.filter(e => e.level === 'WARNING').length,
    ERROR:    events.filter(e => e.level === 'ERROR').length,
    CRITICAL: events.filter(e => e.level === 'CRITICAL').length,
    INFO:     events.filter(e => e.level === 'INFO').length,
  }

  return (
    <Card
      title="Event Log"
      subtitle={`${events.length} events`}
      action={
        <div className="flex gap-1">
          {['ALL', 'CRITICAL', 'WARNING', 'ERROR', 'INFO'].map(level => (
            <button
              key={level}
              onClick={() => setFilter(level)}
              className={`text-xs px-2 py-1 rounded transition-colors
                ${filter === level ? 'bg-green-700 text-white' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}
            >
              {level}
              {level !== 'ALL' && counts[level] > 0 && (
                <span className="ml-1 text-xs opacity-70">({counts[level]})</span>
              )}
            </button>
          ))}
        </div>
      }
    >
      {filtered.length === 0 ? (
        <EmptyState message="No events yet" icon="📋" />
      ) : (
        <div className="space-y-1 max-h-[600px] overflow-y-auto">
          {filtered.map((e, i) => {
            const style = LEVEL_STYLES[e.level] || LEVEL_STYLES.INFO
            return (
              <div key={i} className="flex items-start gap-3 py-2 border-b border-gray-800/40 text-xs">
                <span className={`shrink-0 mt-0.5 ${style.text}`}>{style.label}</span>
                <span className="text-gray-500 font-mono shrink-0 w-20">
                  {new Date(e.timestamp).toLocaleTimeString()}
                </span>
                <span className={`shrink-0 w-16 font-medium ${style.text}`}>{e.level}</span>
                <span className="text-gray-300">{e.message}</span>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
