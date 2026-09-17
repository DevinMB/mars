import { useEffect, useRef, useState } from 'react'

/**
 * Flink SQL types, as a list you can choose from.
 *
 * The field used to be free text defaulting to STRING, which asks someone to
 * already know a type system in order to describe their own data. Most people
 * know they have "a whole number" or "a true/false"; the name Flink gives that is
 * the part worth looking up for them.
 *
 * Anything not on this list can still be typed in — the list is a shortcut, never
 * a limit, and Flink accepts far more than is worth putting in a dropdown
 * (ARRAY, MAP, ROW, DECIMAL with its own precision).
 */
const TYPES = [
  { sql: 'STRING', label: 'Text', note: 'Any text. Also the right choice for a whole JSON document.' },
  { sql: 'BOOLEAN', label: 'True or false' },
  { sql: 'INT', label: 'Whole number', note: 'Up to about 2 billion.' },
  { sql: 'BIGINT', label: 'Big whole number', note: 'For ids, counts and epoch timestamps.' },
  { sql: 'DOUBLE', label: 'Decimal number', note: 'Measurements, averages, anything with a fraction.' },
  { sql: 'FLOAT', label: 'Decimal number, less precise' },
  { sql: 'DECIMAL(10, 2)', label: 'Exact decimal', note: 'Money. Never use DOUBLE for money.' },
  { sql: 'TIMESTAMP(3)', label: 'Date and time', note: 'No timezone. Milliseconds.' },
  { sql: 'TIMESTAMP_LTZ(3)', label: 'Date and time, with zone', note: 'Interpreted in the session timezone.' },
  { sql: 'DATE', label: 'Date only' },
  { sql: 'TIME(3)', label: 'Time only' },
  { sql: 'BYTES', label: 'Raw bytes', note: 'For binary payloads that are not text.' },
  { sql: 'SMALLINT', label: 'Small whole number' },
  { sql: 'TINYINT', label: 'Tiny whole number' },
]

export default function TypePicker({ value, onChange, id }) {
  const [open, setOpen] = useState(false)
  const wrap = useRef(null)

  // Close when focus or a click leaves the control, so it never strands itself
  // open over the field below.
  useEffect(() => {
    if (!open) return
    const away = (e) => { if (!wrap.current?.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', away)
    document.addEventListener('focusin', away)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('focusin', away)
    }
  }, [open])

  const known = TYPES.find((t) => t.sql === (value || '').trim().toUpperCase())

  return (
    <div className="relative w-44 max-w-full shrink-0" ref={wrap} onKeyDown={(e) => { if (e.key === 'Escape') { setOpen(false); e.stopPropagation() } }}>
      <div className="flex">
        {/* Still typeable: ARRAY<STRING>, ROW<...> and DECIMAL with its own
            precision are all valid and none of them belong in a dropdown. */}
        <input
          id={id}
          className="input mono rounded-r-none"
          placeholder="STRING"
          value={value}
          onFocus={() => setOpen(true)}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Column type"
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-label="Choose a type"
          className="px-2 border border-l-0 border-slate-300 rounded-r-md bg-slate-50
                     text-slate-500 hover:text-slate-800 hover:bg-slate-100 text-xs"
        >
          ▾
        </button>
      </div>

      {known?.note && !open && (
        <p className="hint">{known.note}</p>
      )}

      {open && (
        <div className="absolute z-20 mt-1 w-[19rem] max-w-[calc(100vw-2rem)] left-0 sm:left-auto sm:right-0 border border-slate-200
                        rounded-md bg-surface shadow-card overflow-hidden">
          <ul className="max-h-72 overflow-y-auto">
            {TYPES.map((t) => (
              <li key={t.sql}>
                <button
                  type="button"
                  onClick={() => { onChange(t.sql); setOpen(false) }}
                  className={`w-full text-left px-3 py-1.5 hover:bg-slate-50 ${
                    t.sql === value ? 'bg-brand-50' : ''
                  }`}
                >
                  <span className="flex items-baseline gap-2">
                    <span className="text-[13px] text-slate-800">{t.label}</span>
                    <code className="mono text-[11px] text-slate-500 ml-auto">{t.sql}</code>
                  </span>
                  {t.note && <span className="block text-[11px] text-slate-400">{t.note}</span>}
                </button>
              </li>
            ))}
          </ul>
          <p className="px-3 py-1.5 text-[11px] text-slate-400 border-t border-slate-100">
            Or type anything Flink accepts, such as <code className="mono">ARRAY&lt;STRING&gt;</code>.
          </p>
        </div>
      )}
    </div>
  )
}
