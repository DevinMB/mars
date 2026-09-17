import { useMemo, useState } from 'react'

// Completion shared by the SQL editor and the description box. One index serves
// both: the same tables, columns and sampled document fields are what you refer
// to whether you are writing SQL or describing what you want in words.
//
// The list is anchored under the field rather than at the caret. Positioning at
// the caret inside a textarea means measuring text with a mirrored element, and
// it goes wrong on wrapping and scrolling in ways that are worse than a list
// that is simply always in the same place.

/** Builds the index from the tables a job has selected. */
export function buildCompletions(entries, refs, documentFields = {}) {
  const items = []
  for (const name of refs) {
    const entry = entries.find((e) => e.name === name)
    if (!entry) continue

    items.push({
      insert: entry.name,
      label: entry.name,
      detail: entry.kind,
      kind: 'table',
    })

    for (const column of entry.columns || []) {
      items.push({
        insert: column.name,
        label: column.name,
        detail: `${column.type} · ${entry.name}`,
        kind: 'column',
      })
    }

    // Fields found by sampling a record. These are the ones nobody can guess,
    // and the reason a raw-passthrough source is hard to write against.
    const sampled = documentFields[entry.name] || {}
    for (const [column, fields] of Object.entries(sampled)) {
      for (const field of fields) {
        items.push({
          insert: `JSON_VALUE(${column}, '$.${field}')`,
          mention: `${column}.${field}`,
          label: field,
          detail: `in ${column} · ${entry.name}`,
          kind: 'field',
        })
      }
    }
  }
  // Same name from two tables is worth showing once.
  const seen = new Set()
  return items.filter((i) => {
    const key = `${i.kind}:${i.label}:${i.detail}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

const KIND_STYLE = {
  table: 'bg-brand-50 text-brand-700',
  column: 'bg-slate-100 text-slate-600',
  field: 'bg-amber-50 text-amber-800',
}

/**
 * Completion state for one textarea.
 *
 * `mode` is 'sql' -- complete any word -- or 'mention', which only fires after
 * an @ so ordinary prose is never interrupted.
 */
export function useCompletion({ value, onChange, taRef, items, mode = 'sql' }) {
  const [active, setActive] = useState(0)
  const [dismissed, setDismissed] = useState('')

  const caret = () => taRef.current?.selectionStart ?? value.length

  const token = useMemo(() => {
    const before = value.slice(0, caret())
    const match = mode === 'mention'
      ? before.match(/@([\w.]*)$/)
      : before.match(/([A-Za-z_][\w.]*)$/)
    if (!match) return null
    return { text: match[1], start: match.index, end: before.length }
    // The caret is not reactive, so recompute whenever the text changes; the
    // handlers below also recompute on every keystroke.
  }, [value, mode, taRef])

  const matches = useMemo(() => {
    if (!token) return []
    if (mode === 'sql' && token.text.length < 2) return []
    if (dismissed && dismissed === token.text) return []
    const q = token.text.toLowerCase()
    const scored = items
      .map((item) => {
        const label = item.label.toLowerCase()
        if (!q) return { item, score: 2 }
        if (label.startsWith(q)) return { item, score: 0 }
        if (label.includes(q)) return { item, score: 1 }
        return null
      })
      .filter(Boolean)
      .sort((a, b) => a.score - b.score || a.item.label.length - b.item.label.length)
    return scored.slice(0, 8).map((s) => s.item)
  }, [items, token, mode, dismissed])

  const open = matches.length > 0

  const accept = (item) => {
    if (!token) return
    // In prose, insert the readable name; in SQL, insert what actually runs.
    const text = mode === 'mention' ? (item.mention || item.insert) : item.insert
    const start = mode === 'mention' ? token.start : token.start
    const head = value.slice(0, start) + (mode === 'mention' ? '@' : '')
    const next = `${head}${text}${value.slice(token.end)}`
    onChange(next)
    const position = head.length + text.length
    requestAnimationFrame(() => {
      const ta = taRef.current
      if (!ta) return
      ta.focus()
      ta.selectionStart = ta.selectionEnd = position
    })
    setActive(0)
    setDismissed('')
  }

  const onKeyDown = (e) => {
    if (!open) return false
    if (e.key === 'ArrowDown') {
      e.preventDefault(); setActive((i) => (i + 1) % matches.length); return true
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault(); setActive((i) => (i - 1 + matches.length) % matches.length); return true
    }
    if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
      // Enter must still make a new line when nothing is being completed, which
      // is why this only runs while the list is open.
      e.preventDefault(); accept(matches[Math.min(active, matches.length - 1)]); return true
    }
    if (e.key === 'Escape') {
      e.preventDefault(); setDismissed(token?.text || ''); return true
    }
    return false
  }

  return { open, matches, active, setActive, accept, onKeyDown, token }
}

export function CompletionList({ matches, active, onPick }) {
  if (!matches.length) return null
  return (
    <div className="mt-1 border border-slate-200 rounded-md bg-surface shadow-card overflow-hidden">
      <ul className="max-h-56 overflow-y-auto">
        {matches.map((item, i) => (
          <li key={`${item.kind}-${item.label}-${item.detail}-${i}`}>
            <button
              type="button"
              // Mouse down rather than click: the textarea must not lose focus
              // before the insertion happens.
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onPick(item)}
              className={`w-full text-left px-3 py-1.5 flex items-baseline gap-2 ${
                i === active ? 'bg-brand-50' : 'hover:bg-slate-50'
              }`}
            >
              <span className={`text-[10px] px-1.5 py-0.5 rounded shrink-0 ${KIND_STYLE[item.kind]}`}>
                {item.kind}
              </span>
              <code className="mono text-xs text-slate-800">{item.label}</code>
              <span className="text-[11px] text-slate-400 truncate ml-auto">{item.detail}</span>
            </button>
          </li>
        ))}
      </ul>
      <div className="px-3 py-1 text-[11px] text-slate-400 border-t border-slate-100">
        ↑↓ to choose · Tab or Enter to insert · Esc to dismiss
      </div>
    </div>
  )
}
