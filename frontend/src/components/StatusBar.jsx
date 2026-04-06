import React, { useState } from 'react'
import { usePolling, fetchSystemStatus, reloadBrainConfig } from '../utils/api'

const MODE_STYLE = {
  disabled: 'bg-gray-800 text-gray-400 border-gray-700',
  simulate: 'bg-blue-900/50 text-blue-300 border-blue-700',
  live:     'bg-red-900/60 text-red-300 border-red-700 animate-pulse',
}
const MODE_LABEL = {
  disabled: '⬛ DISABLED',
  simulate: '🔵 SIMULATE',
  live:     '🔴 LIVE',
}

export default function StatusBar() {
  const { data } = usePolling(fetchSystemStatus, 5000)
  const [reloading, setReloading] = useState(false)
  const [reloadMsg, setReloadMsg] = useState(null)

  const uptime = data?.uptime_s
  const uptimeStr = !uptime ? '—'
    : uptime < 60    ? `${uptime.toFixed(0)}s`
    : uptime < 3600  ? `${(uptime / 60).toFixed(0)}m`
    : `${(uptime / 3600).toFixed(1)}h`

  const mode = data?.trading_mode ?? 'disabled'

  const handleReload = async () => {
    setReloading(true)
    setReloadMsg(null)
    try {
      const r = await reloadBrainConfig()
      setReloadMsg('✅ reloaded')
    } catch (e) {
      setReloadMsg('⚠️ failed')
    } finally {
      setReloading(false)
      setTimeout(() => setReloadMsg(null), 3000)
    }
  }

  const mkt = data?.market ?? {}

  return (
    <div className="bg-gray-900 border-b border-gray-800 px-4 py-1.5 flex items-center justify-between text-xs gap-4 flex-wrap">

      {/* Left — brain status + mode */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full ${data?.status === 'running' ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
          <span className={data?.status === 'running' ? 'text-green-400 font-medium' : 'text-red-400'}>
            {data?.status === 'running' ? 'Brain' : 'Connecting…'}
          </span>
        </div>

        {/* Brain reload button — lives right next to brain status */}
        <button
          onClick={handleReload}
          disabled={reloading}
          title="Reload brain config from disk"
          className="text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-40 border border-gray-700 rounded px-1.5 py-0.5"
        >
          {reloading ? '⟳…' : '⟳ reload'}
        </button>
        {reloadMsg && <span className="text-gray-400">{reloadMsg}</span>}

        <span className={`border px-2 py-0.5 rounded-full font-medium ${MODE_STYLE[mode]}`}>
          {MODE_LABEL[mode]}
        </span>
      </div>

      {/* Centre — market snapshot */}
      <div className="flex items-center gap-4 text-gray-500 flex-wrap">
        <span title="Connected workers">
          <span className="text-gray-400">{data?.workers ?? 0}</span> workers
        </span>
        <span title="Active exchange×pair price contexts">
          <span className="text-gray-400">{mkt.price_contexts ?? 0}</span> contexts
        </span>
        {(mkt.stale_pairs ?? 0) > 0 && (
          <span className="text-red-400" title="Pairs not updated in >30s">
            ⚠️ {mkt.stale_pairs} stale
          </span>
        )}
        <span title="Total balance across exchanges">
          <span className="text-green-400">${(mkt.total_usd ?? 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</span>
        </span>
        {(data?.open_orders ?? 0) > 0 && (
          <span title="Open orders">
            <span className="text-yellow-400">{data.open_orders}</span> open orders
          </span>
        )}
      </div>

      {/* Right — version + uptime */}
      <div className="flex items-center gap-3 text-gray-600">
        <span>v{data?.version ?? '—'}</span>
        <span>↑ {uptimeStr}</span>
      </div>
    </div>
  )
}
