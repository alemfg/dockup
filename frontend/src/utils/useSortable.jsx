/**
 * useSortable — shared sortable-column hook (v6.6)
 *
 * Usage:
 *   const { sorted, col, dir, toggle } = useSortable(rows, 'spread_pct', 'desc')
 *
 *   <thead><tr>
 *     <SortTh col="pair" sortCol={col} sortDir={dir} onSort={toggle}>Pair</SortTh>
 *     <SortTh col="spread_pct" sortCol={col} sortDir={dir} onSort={toggle}>Spread</SortTh>
 *   </tr></thead>
 *   <tbody>{sorted.map(row => ...)}</tbody>
 *
 * SortTh is a standalone component (not nested inside the hook) so React
 * does not create a new component type on every render — fixes sort not working.
 */
import { useState, useMemo } from 'react'

// SortTh must be defined OUTSIDE the hook so React sees a stable component
// reference across renders. Defining it inside the hook causes React to
// unmount/remount on every render (new function reference = new type).
export function SortTh({ col, sortCol, sortDir, onSort, children, className = '' }) {
  const active = col === sortCol
  return (
    <th
      onClick={() => onSort(col)}
      className={`text-left py-2 px-2 text-gray-500 uppercase text-[10px] cursor-pointer select-none
        hover:text-gray-300 transition-colors ${active ? 'text-gray-300' : ''} ${className}`}
    >
      <span className="flex items-center gap-1">
        {children}
        <span className="text-[8px] opacity-60">
          {active ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
        </span>
      </span>
    </th>
  )
}

export function useSortable(rows = [], defaultCol = '', defaultDir = 'asc') {
  const [col, setCol] = useState(defaultCol)
  const [dir, setDir] = useState(defaultDir)

  const sorted = useMemo(() => {
    if (!col) return rows
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

  const toggle = (newCol) => {
    if (newCol === col) {
      setDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setCol(newCol)
      setDir('asc')
    }
  }

  return { sorted, col, dir, toggle }
}
