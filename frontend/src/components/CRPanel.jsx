import React, { useState } from 'react'
import { usePolling, fetchCRSignals, fetchCRDailyState, setCRForceActive } from '../utils/api'
import { Card, ConfidenceBadge, EmptyState, Spinner } from './ui'

const DIRECTION_COLORS = {
  long:  { text: 'text-green-400', bg: 'bg-green-900/20', border: 'border-green-800/50', icon: '▲' },
  short: { text: 'text-red-400',   bg: 'bg-red-900/20',   border: 'border-red-800/50',   icon: '▼' },
}

function RangeVisual({ htf, ltf, entry, direction }) {
  if (!htf || !ltf) return null
  const totalRange = htf.high - htf.low
  const pct  = (v) => ((v - htf.low) / totalRange * 100).toFixed(1)
  const dc = DIRECTION_COLORS[direction] || DIRECTION_COLORS.long

  return (
    <div className="mt-3 mb-1">
      <div className="text-xs text-gray-500 mb-1">Price Range Visualization</div>
      <div className="relative h-8 bg-gray-800 rounded overflow-hidden">
        {/* HTF range = full bar */}
        <div className="absolute inset-0 bg-gray-700/40" />
        {/* LTF range */}
        <div
          className="absolute h-full bg-blue-900/40 border-x border-blue-700"
          style={{
            left:  `${pct(ltf.low)}%`,
            width: `${pct(ltf.high) - pct(ltf.low)}%`,
          }}
        />
        {/* Entry zone */}
        {entry && (
          <div
            className={`absolute h-full ${dc.bg} border-x ${dc.border}`}
            style={{
              left:  `${pct(entry.zone_bottom)}%`,
              width: `${pct(entry.zone_top) - pct(entry.zone_bottom)}%`,
            }}
          />
        )}
        {/* Labels */}
        <div className="absolute inset-0 flex items-center justify-between px-1 text-xs">
          <span className="text-gray-500">{htf.low?.toFixed(0)}</span>
          <span className="text-blue-400 font-medium">
            LTF {ltf.low?.toFixed(0)}–{ltf.high?.toFixed(0)}
          </span>
          <span className="text-gray-500">{htf.high?.toFixed(0)}</span>
        </div>
      </div>
    </div>
  )
}

function SignalCard({ signal }) {
  const [expanded, setExpanded] = useState(false)
  const dc = DIRECTION_COLORS[signal.direction] || DIRECTION_COLORS.long

  return (
    <div className={`border ${dc.border} ${dc.bg} rounded-lg p-4 mb-3`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className={`text-2xl font-bold ${dc.text}`}>{dc.icon}</span>
          <div>
            <p className="font-semibold text-gray-100">{signal.pair}</p>
            <p className="text-xs text-gray-500">{signal.exchange} · {signal.direction.toUpperCase()}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <ConfidenceBadge value={signal.quality?.confidence} />
          <span className="text-xs text-gray-500">score: {signal.quality?.score?.toFixed(2)}</span>
          <button onClick={() => setExpanded(!expanded)} className="text-gray-500 hover:text-gray-300 text-xs ml-2">
            {expanded ? '▲ less' : '▼ more'}
          </button>
        </div>
      </div>

      {/* Ranges */}
      <div className="grid grid-cols-2 gap-4 text-xs mb-3">
        <div className="bg-gray-800/50 rounded p-2">
          <p className="text-gray-500 mb-1">8AM 1H Range (HTF)</p>
          <p className="text-gray-200 font-mono">H: {signal.htf_range?.high?.toFixed(4)}</p>
          <p className="text-gray-200 font-mono">L: {signal.htf_range?.low?.toFixed(4)}</p>
        </div>
        <div className="bg-blue-900/20 border border-blue-900/40 rounded p-2">
          <p className="text-blue-400 mb-1">9:15 15M Range (LTF)</p>
          <p className="text-gray-200 font-mono">H: {signal.ltf_range?.high?.toFixed(4)}</p>
          <p className="text-gray-200 font-mono">L: {signal.ltf_range?.low?.toFixed(4)}</p>
        </div>
      </div>

      {/* Sweep */}
      <div className="text-xs mb-3 p-2 bg-gray-800/40 rounded">
        <span className="text-gray-500">Sweep: </span>
        <span className={`font-medium ${dc.text}`}>
          {signal.sweep?.direction?.replace('_', ' ').toUpperCase()} @ {signal.sweep?.sweep_price?.toFixed(4)}
        </span>
        <span className="text-gray-600 ml-2">
          {signal.sweep?.sweep_time ? new Date(signal.sweep.sweep_time).toLocaleTimeString() : ''}
        </span>
      </div>

      {/* Targets */}
      <div className="grid grid-cols-3 gap-2 text-xs mb-2">
        <div className="text-center">
          <p className="text-gray-500">Entry</p>
          <p className={`font-mono font-bold ${dc.text}`}>{signal.entry?.price?.toFixed(4)}</p>
        </div>
        <div className="text-center">
          <p className="text-yellow-500">TP1 (LTF)</p>
          <p className="font-mono text-yellow-400">{signal.targets?.tp1?.toFixed(4)}</p>
          <p className="text-gray-600">R:R {signal.targets?.rr_tp1}</p>
        </div>
        <div className="text-center">
          <p className="text-green-500">TP2 (HTF)</p>
          <p className="font-mono text-green-400">{signal.targets?.tp2?.toFixed(4)}</p>
          <p className="text-gray-600">R:R {signal.targets?.rr_tp2}</p>
        </div>
      </div>
      <div className="text-center text-xs">
        <span className="text-red-500">SL: </span>
        <span className="font-mono text-red-400">{signal.targets?.stop_loss?.toFixed(4)}</span>
      </div>

      <RangeVisual
        htf={signal.htf_range} ltf={signal.ltf_range}
        entry={signal.entry} direction={signal.direction}
      />

      {/* Expanded: structure details + notes */}
      {expanded && (
        <div className="mt-3 border-t border-gray-800 pt-3 space-y-2 text-xs">
          <div className="flex gap-4">
            <span className={`${signal.entry?.ob ? 'text-green-400' : 'text-gray-600'}`}>
              {signal.entry?.ob ? '✅' : '○'} Order Block
            </span>
            <span className={`${signal.entry?.fvg ? 'text-green-400' : 'text-gray-600'}`}>
              {signal.entry?.fvg ? '✅' : '○'} FVG
            </span>
            <span className={`${signal.entry?.ifvg_ob_alignment ? 'text-green-400' : 'text-gray-600'}`}>
              {signal.entry?.ifvg_ob_alignment ? '✅' : '○'} IFVG+OB Alignment
            </span>
            <span className={`${signal.quality?.bos_confirmed ? 'text-green-400' : 'text-yellow-400'}`}>
              {signal.quality?.bos_confirmed ? '✅' : '⏳'} BOS
            </span>
          </div>
          {signal.quality?.notes?.length > 0 && (
            <ul className="text-gray-400 space-y-0.5">
              {signal.quality.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}

function CRDailyState() {
  const { data } = usePolling(fetchCRDailyState, 10000)
  const states   = data?.state ?? []
  if (states.length === 0) return null

  return (
    <Card title="CRT Daily State" subtitle="Session ranges and model classification per pair">
      <div className="space-y-3">
        {states.map((s, i) => (
          <div key={i} className="border border-gray-800 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-gray-200">{s.pair}</span>
              <div className="flex items-center gap-2">
                {s.model_type && (
                  <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${
                    s.model_type === 'reversal'
                      ? 'bg-orange-900/30 text-orange-300 border-orange-800'
                      : s.model_type === 'continuation'
                      ? 'bg-blue-900/30 text-blue-300 border-blue-800'
                      : 'bg-gray-800 text-gray-500 border-gray-700'
                  }`}>
                    {s.model_type?.toUpperCase() ?? 'DETECTING'}
                  </span>
                )}
                {s.has_signal && (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-900/40 text-green-300 border border-green-800">
                    ✅ Signal
                  </span>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="bg-gray-800/50 rounded p-2">
                <p className="text-gray-500 mb-1">1AM Range</p>
                {s.range_1am ? (
                  <p className="font-mono text-gray-300">
                    H: {s.range_1am.high?.toFixed(5)} <br/>
                    L: {s.range_1am.low?.toFixed(5)}
                  </p>
                ) : <p className="text-gray-600">Not built yet</p>}
              </div>
              <div className="bg-gray-800/50 rounded p-2">
                <p className="text-gray-500 mb-1">5AM Range</p>
                {s.range_5am ? (
                  <p className="font-mono text-gray-300">
                    H: {s.range_5am.high?.toFixed(5)} <br/>
                    L: {s.range_5am.low?.toFixed(5)}
                  </p>
                ) : <p className="text-gray-600">Not built yet</p>}
              </div>
            </div>
            {s.sweep && (
              <div className="mt-2 text-xs bg-yellow-900/20 border border-yellow-800/50 rounded p-2">
                <span className="text-yellow-400">⚡ Sweep: </span>
                <span className="text-gray-300">{s.sweep.direction} @ {s.sweep.sweep_price?.toFixed(5)}</span>
              </div>
            )}
          </div>
        ))}
      </div>
    </Card>
  )
}

export default function CRPanel() {
  const { data, loading } = usePolling(fetchCRSignals, 10000)
  const [forceLoading, setForceLoading] = useState(false)

  if (loading) return <Card title="9AM CR Model"><Spinner /></Card>

  const signals    = data?.signals ?? []
  const forceActive = data?.force_active ?? false
  const now        = new Date()
  const nyHour     = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' })).getHours()
  const isActive   = forceActive || (nyHour >= 9 && nyHour < 10)
  const isPreWindow = !forceActive && nyHour === 8

  const toggleForce = async () => {
    setForceLoading(true)
    try { await setCRForceActive(!forceActive) }
    catch (e) { console.error(e) }
    finally { setForceLoading(false) }
  }

  return (
    <div className="space-y-4">
      {/* Window status */}
      <Card>
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-4">
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Model Window</p>
              <p className={`text-lg font-bold ${isActive ? 'text-green-400' : isPreWindow ? 'text-yellow-400' : 'text-gray-500'}`}>
                {forceActive
                  ? '⚡ FORCED ACTIVE'
                  : isActive ? '● ACTIVE'
                  : isPreWindow ? '○ PRE-WINDOW (8AM building)'
                  : '○ INACTIVE'}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">NY Time</p>
              <p className="text-lg font-mono text-gray-200">
                {now.toLocaleTimeString('en-US', { timeZone: 'America/New_York', hour12: false })}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {forceActive && (
              <span className="text-xs text-yellow-400 bg-yellow-900/30 border border-yellow-700 px-2 py-1 rounded-lg">
                ⚠️ Outside market hours — no real candle data
              </span>
            )}
            <button
              onClick={toggleForce}
              disabled={forceLoading}
              className={`text-xs px-4 py-2 rounded-lg font-medium transition-colors border ${
                forceActive
                  ? 'bg-yellow-900/40 border-yellow-700 text-yellow-300 hover:bg-yellow-900/60'
                  : 'bg-gray-800 border-gray-600 text-gray-300 hover:bg-gray-700'
              } ${forceLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
            >
              {forceLoading ? '...' : forceActive ? '⏹ Stop Forced Analysis' : '▶ Force Analyse Now'}
            </button>
          </div>
        </div>
        <div className="text-right text-xs text-gray-500 mt-2">
          <p>8AM: Build HTF 1H range</p>
          <p>9:15: Build LTF 15M range</p>
          <p>9:00–10:00: Monitor sweeps</p>
        </div>
      </Card>

      {/* Active signals */}
      <Card
        title="9AM CR Setups"
        subtitle={`${signals.length} active setup${signals.length !== 1 ? 's' : ''} today`}
      >
        {signals.length === 0 ? (
          <EmptyState
            message={isPreWindow ? 'Waiting for 9AM window...' : 'No setups yet — watching for range sweeps'}
            icon="🕘"
          />
        ) : (
          signals.map((s, i) => <SignalCard key={i} signal={s} />)
        )}
      </Card>

      {/* Daily State (v4) */}
      <CRDailyState />

      {/* Model guide */}
      <Card title="Model Reference">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs text-gray-400">
          <div>
            <p className="text-gray-200 font-medium mb-1">Step 1 — 8AM 1H</p>
            <p>Wait for 8AM candle to close. Mark High and Low as HTF boundary.</p>
          </div>
          <div>
            <p className="text-gray-200 font-medium mb-1">Step 2 — 9:15 15M</p>
            <p>Wait for 9:00 candle to close. Mark High and Low as LTF range inside HTF.</p>
          </div>
          <div>
            <p className="text-gray-200 font-medium mb-1">Step 3 — 1M Sweep</p>
            <p>Wait for price to sweep one side of LTF range, then look for BOS + OB + FVG.</p>
          </div>
        </div>
        <div className="mt-3 text-xs text-gray-500 border-t border-gray-800 pt-3">
          <span className="text-yellow-400 font-medium">TP1</span>: opposite end of 9:15 LTF range ·
          <span className="text-green-400 font-medium ml-2">TP2</span>: opposite end of 8AM HTF range ·
          <span className="text-red-400 font-medium ml-2">SL</span>: beyond sweep extreme
        </div>
      </Card>
    </div>
  )
}
