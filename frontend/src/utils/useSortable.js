/**
 * useSortable — shared sortable-column hook (v6.5)
 *
 * Usage:
 *   const { sorted, SortTh } = useSortable(rows, 'spread_pct', 'desc')
 *
 *   <thead><tr>
 *     <SortTh col="pair">Pair</SortTh>
 *     <SortTh col="spread_pct">Spread</SortTh>
 *   </tr></thead>
 *   <tbody>{sorted.map(row => ...)}</tbody>
 *
 * SortTh renders a <th> that shows ▲/▼ on the active column and is clickable.
 * Clicking the active column flips direction. Clicking a new column sorts asc.
 */
import { useState, useMemo } from 'react'

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

  function SortTh({ col: c, children, className = '' }) {
    const active = c === col
    return (
      <th
        onClick={() => toggle(c)}
        className={`text-left py-2 px-2 text-gray-500 uppercase text-[10px] cursor-pointer select-none
          hover:text-gray-300 transition-colors ${active ? 'text-gray-300' : ''} ${className}`}
      >
        <span className="flex items-center gap-1">
          {children}
          <span className="text-[8px] opacity-60">
            {active ? (dir === 'asc' ? '▲' : '▼') : '⇅'}
          </span>
        </span>
      </th>
    )
  }

  return { sorted, col, dir, toggle, SortTh }
}
