import React, { useState } from 'react'
import { usePolling, fetchTradingMode, setTradingMode, setExchangeTrading, fetchActiveExchanges } from '../utils/api'
import { Card, Spinner } from './ui'

const MODES = [
  {
    id: 'disabled',
    label: 'Disabled',
    icon: '⬛',
    color: 'border-gray-600 bg-gray-800/60 text-gray-300',
    active: 'border-gray-400 bg-gray-700 text-white',
    desc: 'No orders sent or logged. Analysis runs normally.',
  },
  {
    id: 'simulate',
    label: 'Simulate',
    icon: '🔵',
    color: 'border-blue-800 bg-blue-900/20 text-blue-300',
    active: 'border-blue-400 bg-blue-900/50 text-blue-100',
    desc: 'Orders are computed and logged in full detail — never sent to exchange.',
  },
  {
    id: 'live',
    label: 'Live',
    icon: '🔴',
    color: 'border-red-900 bg-red-900/10 text-red-400',
    active: 'border-red-400 bg-red-900/40 text-red-100',
    desc: 'Real orders sent to enabled exchanges via CCXT. Use with caution.',
  },
]

// Exchanges loaded dynamically from active config

export default function TradingModePanel() {
  const { data, loading }             = usePolling(fetchTradingMode, 5000)
  const { data: activeData }          = usePolling(fetchActiveExchanges, 15000)
  const { data: apiKeyData }          = usePolling(() => fetch('/api/vault/apikeys').then(r=>r.json()), 15000)
  const [confirming, setConfirming]   = useState(false)
  const [pendingMode, setPendingMode] = useState(null)
  const [busy, setBusy]               = useState(false)
  const [error, setError]             = useState(null)

  const activeExchanges = activeData?.exchanges?.map(e => e.exchange) ?? []
  const keyedExchanges  = new Set((apiKeyData?.keys ?? []).map(k => k.exchange))

  if (loading) return <Card title="Trading Mode"><Spinner /></Card>

  const currentMode = data?.mode ?? 'disabled'
  const exchangeEnabled = data?.exchange_enabled ?? {}

  const handleModeClick = (modeId) => {
    if (modeId === currentMode) return
    if (modeId === 'live') {
      setPendingMode('live')
      setConfirming(true)
    } else {
      applyMode(modeId, false)
    }
  }

  const applyMode = async (modeId, confirm) => {
    setBusy(true)
    setError(null)
    try {
      await setTradingMode(modeId, confirm)
      setConfirming(false)
      setPendingMode(null)
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    } finally {
      setBusy(false)
    }
  }

  const handleExchangeToggle = async (exchange, enabled) => {
    setBusy(true)
    setError(null)
    try {
      await setExchangeTrading(exchange, enabled)
    } catch (e) {
      setError(e.response?.data?.detail ?? e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <Card
        title="Trading Mode"
        subtitle="Controls whether orders are blocked, simulated, or sent live"
      >
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
          {MODES.map(m => {
            const isActive = currentMode === m.id
            return (
              <button
                key={m.id}
                onClick={() => handleModeClick(m.id)}
                disabled={busy}
                className={`border rounded-xl p-4 text-left transition-all ${isActive ? m.active : m.color} ${busy ? 'opacity-50 cursor-not-allowed' : 'hover:opacity-90 cursor-pointer'}`}
              >
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-lg">{m.icon}</span>
                  <span className="font-semibold">{m.label}</span>
                  {isActive && <span className="ml-auto text-xs opacity-70">● active</span>}
                </div>
                <p className="text-xs opacity-70 leading-relaxed">{m.desc}</p>
              </button>
            )
          })}
        </div>

        {error && (
          <div className="bg-red-900/30 border border-red-700 rounded-lg p-3 text-sm text-red-300 mb-3">
            {error}
          </div>
        )}

        {/* Live confirmation modal */}
        {confirming && (
          <div className="bg-red-900/20 border border-red-700 rounded-xl p-4">
            <p className="text-red-300 font-semibold mb-1">⚠️ Enable Live Trading?</p>
            <p className="text-sm text-gray-400 mb-3">
              This will send <strong className="text-white">real orders</strong> to enabled exchanges.
              Make sure API keys are configured and per-exchange toggles are set correctly below.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => applyMode('live', true)}
                disabled={busy}
                className="bg-red-700 hover:bg-red-600 text-white text-sm px-4 py-2 rounded-lg transition-colors"
              >
                Yes, enable Live trading
              </button>
              <button
                onClick={() => { setConfirming(false); setPendingMode(null) }}
                className="bg-gray-700 hover:bg-gray-600 text-gray-200 text-sm px-4 py-2 rounded-lg transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </Card>

      {/* Per-exchange toggles */}
      {currentMode !== 'disabled' && (
        <Card
          title="Exchange Execution"
          subtitle={currentMode === 'live'
            ? 'Only enabled exchanges will receive real orders'
            : 'Simulated orders will be logged for these exchanges'}
        >
          <div className="space-y-2">
            {activeExchanges.map(ex => {
              const enabled = exchangeEnabled[ex] ?? false
              return (
                <div key={ex} className="flex items-center justify-between py-2 border-b border-gray-800 last:border-0">
                  <div>
                    <span className="text-sm font-medium text-gray-200 capitalize">{ex}</span>
                    {currentMode === 'live' && enabled && (
                      <span className="ml-2 text-xs text-red-400">● live orders active</span>
                    )}
                    {currentMode === 'simulate' && enabled && (
                      <span className="ml-2 text-xs text-blue-400">● simulating</span>
                    )}
                  </div>
                  <button
                    onClick={() => handleExchangeToggle(ex, !enabled)}
                    disabled={busy}
                    className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${enabled ? 'bg-green-600' : 'bg-gray-700'} ${busy ? 'opacity-50' : ''}`}
                  >
                    <span className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${enabled ? 'translate-x-4' : 'translate-x-1'}`} />
                  </button>
                </div>
              )
            })}
          </div>
          {currentMode === 'live' && (
            <p className="text-xs text-red-400 mt-3">
              ⚠️ Live mode — only enable exchanges where API keys are configured and tested.
            </p>
          )}
        </Card>
      )}
    </div>
  )
}
