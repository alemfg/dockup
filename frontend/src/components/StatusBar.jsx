import React from 'react'
import { usePolling, fetchSystemStatus } from '../utils/api'

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

  const uptime = data?.uptime_s
  const uptimeStr = !uptime ? '—'
    : uptime < 60 ? `${uptime.toFixed(0)}s`
    : uptime < 3600 ? `${(uptime / 60).toFixed(0)}m`
    : `${(uptime / 3600).toFixed(1)}h`

  const mode = data?.trading_mode ?? 'disabled'

  return (
    <div className="bg-gray-900 border-b border-gray-800 px-4 py-2 flex items-center justify-between text-xs">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-green-400 font-medium">
            {data?.status === 'running' ? 'Brain Running' : 'Connecting...'}
          </span>
        </div>
        <span className={`border px-2 py-0.5 rounded-full font-medium ${MODE_STYLE[mode]}`}>
          {MODE_LABEL[mode]}
        </span>
        {data?.dry_run && (
          <span className="bg-yellow-900/50 text-yellow-400 border border-yellow-800 px-2 py-0.5 rounded-full">
            DRY-RUN
          </span>
        )}
        <span className="text-gray-600">
          {data?.workers ?? 0} workers · {data?.market?.price_contexts ?? 0} price contexts
        </span>
      </div>
      <div className="flex items-center gap-4 text-gray-500">
        <span>v{data?.version ?? '—'}</span>
        <span>Up {uptimeStr}</span>
      </div>
    </div>
  )
}
