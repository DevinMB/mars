import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

// A disclosure of ordinary links and buttons, retaining native Tab navigation.
export default function ActionMenu({ label = 'More', children, primary = false }) {
  const [position, setPosition] = useState(null)
  const trigger = useRef(null)
  const panel = useRef(null)
  const id = useId()
  const close = () => setPosition(null)
  useEffect(() => {
    if (!position) return
    panel.current?.querySelector('a, button, input')?.focus()
    const outside = (e) => {
      if (!panel.current?.contains(e.target) && !trigger.current?.contains(e.target)) close()
    }
    const escape = (e) => {
      if (e.key === 'Escape') { close(); trigger.current?.focus(); e.stopPropagation() }
    }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('focusin', outside)
    document.addEventListener('keydown', escape)
    window.addEventListener('resize', close)
    const scroll = (e) => { if (!panel.current?.contains(e.target)) close() }
    window.addEventListener('scroll', scroll, true)
    return () => {
      document.removeEventListener('pointerdown', outside)
      document.removeEventListener('focusin', outside)
      document.removeEventListener('keydown', escape)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', scroll, true)
    }
  }, [position])
  return <>
    <button ref={trigger} type="button" className={primary ? 'btn-primary' : 'btn-secondary'}
      aria-expanded={Boolean(position)} aria-controls={position ? id : undefined}
      onClick={() => {
        if (position) { close(); return }
        const r = trigger.current.getBoundingClientRect()
        setPosition({ right: Math.max(12, window.innerWidth - r.right),
          ...(r.bottom + 250 > window.innerHeight && r.top > 250
            ? { bottom: window.innerHeight - r.top + 6 } : { top: r.bottom + 6 }) })
      }}>
      {label}<span aria-hidden="true" className="opacity-60 text-[10px]">▾</span>
    </button>
    {position && createPortal(
      <div id={id} ref={panel} className="action-menu" style={position}
        onClick={(e) => {
          if (e.target.closest('[data-keep-open]')) return
          if (e.target.closest('a, button')) { close(); trigger.current?.focus() }
        }}>{children}</div>, document.body)}
  </>
}
