/**
 * Tooltip component — shows explanatory text on hover.
 * Usage:
 *   <Tip text="Explanation here">
 *     <span>hover me</span>
 *   </Tip>
 *
 * Or inline on any element via the TipIcon helper:
 *   <TipIcon text="What this means" />
 */
import React, { useState, useRef } from 'react'

export function Tip({ text, children, pos = 'top', wide = false }) {
  const [show, setShow] = useState(false)
  const ref = useRef(null)

  const posClasses = {
    top:    'bottom-full left-1/2 -translate-x-1/2 mb-2',
    bottom: 'top-full left-1/2 -translate-x-1/2 mt-2',
    left:   'right-full top-1/2 -translate-y-1/2 mr-2',
    right:  'left-full top-1/2 -translate-y-1/2 ml-2',
  }

  return (
    <span
      ref={ref}
      className="relative inline-flex items-center"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span className={`
          absolute z-50 pointer-events-none
          ${posClasses[pos]}
          ${wide ? 'w-72' : 'w-56'}
          bg-gray-800 border border-gray-600 text-gray-200
          text-xs rounded-lg px-3 py-2 shadow-xl leading-relaxed
        `}>
          {text}
          {/* Arrow */}
          {pos === 'top' && (
            <span className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-gray-600" />
          )}
          {pos === 'bottom' && (
            <span className="absolute bottom-full left-1/2 -translate-x-1/2 border-4 border-transparent border-b-gray-600" />
          )}
        </span>
      )}
    </span>
  )
}

/** Small ⓘ icon with tooltip — drop anywhere next to a label */
export function TipIcon({ text, pos = 'top', wide = false }) {
  return (
    <Tip text={text} pos={pos} wide={wide}>
      <span className="text-gray-600 hover:text-gray-400 cursor-help ml-1 text-xs select-none">ⓘ</span>
    </Tip>
  )
}

export default Tip
