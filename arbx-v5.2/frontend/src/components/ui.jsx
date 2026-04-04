import React from 'react'

export function Card({ title, subtitle, children, className = '', action }) {
  return (
    <div className={`bg-gray-900 border border-gray-800 rounded-xl p-5 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-200 uppercase tracking-wider">{title}</h2>
            {subtitle && <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </div>
  )
}

export function StatusDot({ status }) {
  const colors = {
    healthy:    'bg-green-400 animate-pulse',
    degraded:   'bg-yellow-400 animate-pulse',
    blocked:    'bg-red-500 animate-pulse',
    overloaded: 'bg-orange-400 animate-pulse',
    dead:       'bg-gray-600',
    starting:   'bg-blue-400 animate-pulse',
  }
  return (
    <span className={`inline-block w-2 h-2 rounded-full mr-2 ${colors[status] || 'bg-gray-600'}`} />
  )
}

export function StatusBadge({ status }) {
  const styles = {
    healthy:    'bg-green-900/50 text-green-400 border-green-800',
    degraded:   'bg-yellow-900/50 text-yellow-400 border-yellow-800',
    blocked:    'bg-red-900/50 text-red-400 border-red-800',
    overloaded: 'bg-orange-900/50 text-orange-400 border-orange-800',
    dead:       'bg-gray-800 text-gray-500 border-gray-700',
    starting:   'bg-blue-900/50 text-blue-400 border-blue-800',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${styles[status] || styles.dead}`}>
      {status}
    </span>
  )
}

export function ConfidenceBadge({ value }) {
  const v = (value || '').toUpperCase()
  if (v === 'HIGH')   return <span className="bg-green-900/50 text-green-400 border border-green-800 text-xs px-2 py-0.5 rounded-full">HIGH</span>
  if (v === 'MEDIUM') return <span className="bg-yellow-900/50 text-yellow-400 border border-yellow-800 text-xs px-2 py-0.5 rounded-full">MED</span>
  return <span className="bg-red-900/50 text-red-400 border border-red-800 text-xs px-2 py-0.5 rounded-full">LOW</span>
}

export function Stat({ label, value, color = 'text-white', sub }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      <span className={`text-2xl font-bold mt-1 ${color}`}>{value}</span>
      {sub && <span className="text-xs text-gray-500 mt-0.5">{sub}</span>}
    </div>
  )
}

export function EmptyState({ message = 'No data yet', icon = '📭' }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-gray-600">
      <span className="text-3xl mb-3">{icon}</span>
      <p className="text-sm">{message}</p>
    </div>
  )
}

export function Spinner() {
  return (
    <div className="flex items-center justify-center py-8">
      <div className="w-6 h-6 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

export function WsBadge({ status }) {
  const colors = {
    connected:    'bg-green-900/50 text-green-400 border-green-800',
    connecting:   'bg-yellow-900/50 text-yellow-400 border-yellow-800',
    reconnecting: 'bg-red-900/50 text-red-400 border-red-800',
  }
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full border ${colors[status] || colors.connecting}`}>
      {status}
    </span>
  )
}

export function Table({ headers, rows, onRowClick }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-800">
            {headers.map((h, i) => (
              <th key={i} className="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={i}
              onClick={() => onRowClick && onRowClick(row)}
              className={`border-b border-gray-800/40 ${onRowClick ? 'cursor-pointer hover:bg-gray-800/40' : ''} transition-colors`}
            >
              {row.cells.map((cell, j) => (
                <td key={j} className="py-2.5 pr-4 text-gray-300">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Button({ children, onClick, variant = 'default', size = 'sm', disabled = false }) {
  const variants = {
    default:  'bg-gray-800 text-gray-300 hover:bg-gray-700 border border-gray-700',
    danger:   'bg-red-900/50 text-red-400 hover:bg-red-900 border border-red-800',
    success:  'bg-green-900/50 text-green-400 hover:bg-green-900 border border-green-800',
    primary:  'bg-green-700 text-white hover:bg-green-600',
  }
  const sizes = { sm: 'text-xs px-3 py-1.5', md: 'text-sm px-4 py-2' }
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`rounded transition-colors disabled:opacity-40 disabled:cursor-not-allowed
        ${variants[variant]} ${sizes[size]}`}
    >
      {children}
    </button>
  )
}
