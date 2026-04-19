/**
 * useSortable (v6.8) — stable sortable-column hook
 *
 * Key fix: toggle() is wrapped in useCallback so it has a stable reference
 * across renders. Without this, components that receive toggle as a prop
 * see a new function every render and may re-mount, losing click state.
 *
 * Usage:
 *   const { sorted, col, dir, toggle } = useSortable(rows, 'spread', 'desc')
 *   <SortTh col="pair" sortCol={col} sortDir={dir} onSort={toggle}>Pair</SortTh>
 */
import { useState, useMemo, useCallback } from 'react'

export function SortTh({ col, sortCol, sortDir, onSort, children, className = '' }) {
  const active = col === sortCol
  return (
    <th
      onClick={() => onSort(col)}
      className={`text-left py-2 px-2 text-gray-500 uppercase text-[10px]
        cursor-pointer select-none hover:text-gray-300 transition-colors
        ${active ? 'text-indigo-400' : ''} ${className}`}
    >
      <span className="flex items-center gap-1">
        {children}
        <span className={`text-[9px] ${active ? 'opacity-100' : 'opacity-40'}`}>
          {active ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
        </span>
      </span>
    </th>
  )
}

export function useSortable(rows = [], defaultCol = '', defaultDir = 'asc') {
  const [col, setCol] = useState(defaultCol)
  const [dir, setDir] = useState(defaultDir)

  // useCallback gives toggle a stable reference — prevents child remounts
  const toggle = useCallback((newCol) => {
    setCol(prev => {
      if (newCol !== prev) {
        setDir('asc')
        return newCol
      }
      // Same column — flip direction
      setDir(d => d === 'asc' ? 'desc' : 'asc')
      return prev
    })
  }, [])

  const sorted = useMemo(() => {
    if (!col || !rows.length) return rows
    return [...rows].sort((a, b) => {
      const av = a[col]
      const bv = b[col]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      const cmp = typeof av === 'string'
        ? av.localeCompare(bv, undefined, { sensitivity: 'base' })
        : av < bv ? -1 : av > bv ? 1 : 0
      return dir === 'asc' ? cmp : -cmp
    })
  }, [rows, col, dir])

  return { sorted, col, dir, toggle }
}
