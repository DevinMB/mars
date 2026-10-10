import { useMemo, useState } from 'react'
import SearchInput from './SearchInput'

// Picks the catalog entries a job depends on.
//
// Filtered because this list only grows: every source and sink a deployment has
// ever defined shows up here, and by the twentieth one an unfiltered column of
// checkboxes is unusable. Matching runs over the name and the connector, so
// "kafka" narrows to Kafka tables and "events" to the events pipeline.
export default function TablePicker({ entries, selected, onToggle }) {
  const [query, setQuery] = useState('')

  const { sources, sinks, total } = useMemo(() => {
    const q = query.trim().toLowerCase()
    const match = (e) =>
      !q ||
      e.name.toLowerCase().includes(q) ||
      e.connector.toLowerCase().includes(q) ||
      (e.description || '').toLowerCase().includes(q)
    const hits = entries.filter(match)
    return {
      sources: hits.filter((e) => e.kind === 'source'),
      sinks: hits.filter((e) => e.kind === 'sink'),
      total: hits.length,
    }
  }, [entries, query])

  const Group = ({ label, rows }) => {
    if (rows.length === 0) return null
    return (
      <div className="mb-4 last:mb-0">
        <div className="flex items-baseline justify-between mb-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
            {label}
          </span>
          <span className="text-[11px] tabular-nums text-slate-400">{rows.length}</span>
        </div>
        <div className="-mx-1">
          {rows.map((e) => {
            const on = selected.includes(e.name)
            return (
              <label
                key={e.id}
                className={`flex items-start gap-2.5 px-1.5 py-1.5 rounded cursor-pointer
                            transition-colors ${on ? 'bg-brand-50/70' : 'hover:bg-slate-50'}`}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => onToggle(e.name)}
                  className="mt-0.5 rounded border-slate-300 text-brand-600
                             focus:ring-brand-500/30 shrink-0"
                />
                <span className="min-w-0 flex-1">
                  <span className="mono text-[13px] text-slate-800 block truncate">{e.name}</span>
                  <span className="text-[11px] text-slate-500">{e.connector}</span>
                </span>
              </label>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-3">
        <SearchInput
          value={query}
          onChange={setQuery}
          placeholder="Filter tables…"
          count={total}
        />
      </div>

      {selected.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {selected.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => onToggle(name)}
              className="mono text-[11px] bg-brand-50 text-brand-800 border border-brand-200
                         rounded px-1.5 py-0.5 hover:bg-brand-100"
              title="Remove"
            >
              {name} ×
            </button>
          ))}
        </div>
      )}

      {entries.length === 0 ? (
        <p className="text-xs text-slate-500">
          Nothing in the catalog yet. Define a source and a sink first.
        </p>
      ) : total === 0 ? (
        <p className="text-xs text-slate-500">No table matches “{query}”.</p>
      ) : (
        <>
          <Group label="Sources" rows={sources} />
          <Group label="Sinks" rows={sinks} />
        </>
      )}
    </div>
  )
}
