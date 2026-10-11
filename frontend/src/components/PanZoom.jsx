import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

const MIN = 0.3
const MAX = 2
const READABLE = 0.75
const MARGIN = 60 // of the drawing kept in view, so it cannot be dragged away
const DRAG = 4 // pixels moved before a press becomes a drag rather than a click

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/**
 * A viewport you grab and pull around, for a drawing larger than the page.
 *
 * Drag to pan; wheel or trackpad pans too; ctrl/⌘ + wheel (or a trackpad pinch)
 * zooms around the pointer. Arrow keys pan and + / - / 0 zoom and fit when it has
 * focus. A press that moves is a drag, and does not click what it started on.
 *
 * children: SVG content drawn at scale 1, within width × height.
 * fitKey: when it changes, the view refits, e.g. after a filter changes the drawing.
 */
export default function PanZoom({ width, height, fitKey, label, children }) {
  const box = useRef(null)
  const press = useRef(null)
  const dragged = useRef(false)
  const [size, setSize] = useState({ w: 0, h: 0 })
  const [view, setView] = useState({ x: 0, y: 0, k: 1 })
  const [grabbing, setGrabbing] = useState(false)

  useLayoutEffect(() => {
    const el = box.current
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight })
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const bound = useCallback((v) => ({
    k: v.k,
    x: clamp(v.x, MARGIN - width * v.k, size.w - MARGIN),
    y: clamp(v.y, MARGIN - height * v.k, size.h - MARGIN),
  }), [width, height, size])

  // readable: the first view of a drawing too wide for the screen stays legible
  // and starts at the left, for dragging along; Fit shows all of it however small.
  const fit = useCallback((readable = false) => {
    if (!size.w) return
    const whole = clamp(Math.min(size.w / width, size.h / height), MIN, 1)
    const k = readable ? Math.max(whole, READABLE) : whole
    const place = (room, extent) => (extent * k <= room ? (room - extent * k) / 2 : 0)
    setView({ k, x: place(size.w, width), y: place(size.h, height) })
  }, [size, width, height])

  useEffect(() => { fit(true) }, [fitKey, size.w > 0]) // eslint-disable-line react-hooks/exhaustive-deps

  const zoomAt = useCallback((factor, cx, cy) => {
    setView((v) => {
      const k = clamp(v.k * factor, MIN, MAX)
      // Keep the point under the pointer where it is.
      return bound({ k, x: cx - ((cx - v.x) * k) / v.k, y: cy - ((cy - v.y) * k) / v.k })
    })
  }, [bound])

  // Wheel needs a non-passive listener to stop the page scrolling instead.
  useEffect(() => {
    const el = box.current
    const onWheel = (e) => {
      const r = el.getBoundingClientRect()
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault()
        zoomAt(Math.exp(-e.deltaY * 0.0025), e.clientX - r.left, e.clientY - r.top)
        return
      }
      // A vertical scroll over a drawing that already fits top to bottom is
      // meant for the page.
      const fitsVertically = height * view.k <= size.h
      if (fitsVertically && Math.abs(e.deltaY) > Math.abs(e.deltaX) && !e.shiftKey) return
      e.preventDefault()
      const dx = e.shiftKey ? e.deltaY : e.deltaX
      const dy = e.shiftKey ? 0 : e.deltaY
      setView((v) => bound({ ...v, x: v.x - dx, y: v.y - dy }))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt, bound, height, view.k, size.h])

  const onPointerDown = (e) => {
    if (e.button !== 0) return
    press.current = { id: e.pointerId, px: e.clientX, py: e.clientY, x: view.x, y: view.y, moving: false }
  }
  const onPointerMove = (e) => {
    const p = press.current
    if (!p || p.id !== e.pointerId) return
    const dx = e.clientX - p.px, dy = e.clientY - p.py
    if (!p.moving) {
      if (Math.hypot(dx, dy) < DRAG) return
      // Captured only once it is a drag, so a plain click still reaches the node.
      p.moving = true
      setGrabbing(true)
      box.current.setPointerCapture(e.pointerId)
    }
    setView((v) => bound({ ...v, x: p.x + dx, y: p.y + dy }))
  }
  const onPointerUp = (e) => {
    const p = press.current
    if (!p || p.id !== e.pointerId) return
    dragged.current = p.moving
    press.current = null
    setGrabbing(false)
  }
  const onClickCapture = (e) => {
    if (dragged.current) { e.stopPropagation(); e.preventDefault(); dragged.current = false }
  }
  const onKeyDown = (e) => {
    if (e.target !== box.current) return // keys on a node are the node's
    const step = 60
    const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }
    if (moves[e.key]) {
      e.preventDefault()
      setView((v) => bound({ ...v, x: v.x + moves[e.key][0], y: v.y + moves[e.key][1] }))
    } else if (e.key === '+' || e.key === '=') zoomAt(1.2, size.w / 2, size.h / 2)
    else if (e.key === '-') zoomAt(1 / 1.2, size.w / 2, size.h / 2)
    else if (e.key === '0') fit()
  }

  const viewportHeight = Math.max(260, Math.min(height, Math.round(window.innerHeight * 0.7)))

  return (
    <div className="relative">
      <div ref={box} tabIndex={0} role="group"
           aria-label={`${label}. Drag or use the arrow keys to move around; plus and minus zoom; 0 fits.`}
           className={`overflow-hidden touch-none select-none focus:outline-hidden focus-visible:ring-2 focus-visible:ring-accent-400 rounded-[inherit] ${grabbing ? 'cursor-grabbing' : 'cursor-grab'}`}
           style={{ height: viewportHeight }}
           onPointerDown={onPointerDown} onPointerMove={onPointerMove}
           onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
           onClickCapture={onClickCapture} onKeyDown={onKeyDown}>
        <svg width="100%" height="100%" className="block" role="img" aria-label={label}>
          <g transform={`translate(${view.x} ${view.y}) scale(${view.k})`}>{children}</g>
        </svg>
      </div>
      <div className="absolute top-2 right-2 flex rounded-md border border-slate-200 bg-surface shadow-sm text-[13px] text-slate-700">
        <button type="button" className="px-2.5 py-1 hover:bg-slate-100" aria-label="Zoom out"
                onClick={() => zoomAt(1 / 1.25, size.w / 2, size.h / 2)}>−</button>
        <button type="button" className="px-2.5 py-1 border-x border-slate-200 hover:bg-slate-100" aria-label="Zoom in"
                onClick={() => zoomAt(1.25, size.w / 2, size.h / 2)}>+</button>
        <button type="button" className="px-2.5 py-1 hover:bg-slate-100" onClick={() => fit()}>Fit</button>
      </div>
    </div>
  )
}
