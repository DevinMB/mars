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

  const { groups, total } = useMemo(() => {
    const q = query.trim().toLowerCase()
    const match = (e) =>
      !q ||
      e.name.toLowerCase().includes(q) ||
      e.connector.toLowerCase().includes(q) ||
      (e.description || '').toLowerCase().includes(q)
    const hits = entries.filter(match)
    // Grouped by what each table points at, not a source/sink role: whether this
    // job reads or writes a table is decided by its SQL.
    const byKind = new Map()
    for (const e of hits) {
      const kind = e.resource && !e.resource.key.startsWith('table:') ? e.resource.kind : 'other'
      if (!byKind.has(kind)) byKind.set(kind, [])
      byKind.get(kind).push(e)
    }
    const groups = [...byKind.entries()]
      .sort(([a], [b]) => (a === 'other') - (b === 'other') || a.localeCompare(b))
      .map(([kind, rows]) => ({
        label: kind === 'other' ? 'Other tables' : `${kind[0].toUpperCase()}${kind.slice(1)}s`,
        rows: rows.sort((x, y) => (x.resource?.label || '').localeCompare(y.resource?.label || '')
          || x.name.localeCompare(y.name)),
      }))
    return { groups, total: hits.length }
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
                className={`flex items-start gap-2.5 px-1.5 py-1.5 rounded-sm cursor-pointer
                            transition-colors ${on ? 'bg-brand-50/70' : 'hover:bg-slate-50'}`}
              >
                <input
                  type="checkbox"
                  checked={on}
                  onChange={() => onToggle(e.name)}
                  className="mt-0.5 rounded-sm border-slate-300 text-brand-600
                             focus:ring-brand-500/30 shrink-0"
                />
                <span className="min-w-0 flex-1">
                  <span className="mono text-[13px] text-slate-800 block truncate">{e.name}</span>
                  <span className="text-[11px] text-slate-500">
                    {e.connector}
                    {e.resource && !e.resource.key.startsWith('table:') && <> · <span className="mono">{e.resource.label}</span></>}
                  </span>
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
                         rounded-sm px-1.5 py-0.5 hover:bg-brand-100"
              title="Remove"
            >
              {name} ×
            </button>
          ))}
        </div>
      )}

      {entries.length === 0 ? (
        <p className="text-xs text-slate-500">
          Nothing in the catalog yet. Add the tables this job reads and writes first.
        </p>
      ) : total === 0 ? (
        <p className="text-xs text-slate-500">No table matches “{query}”.</p>
      ) : (
        <>
          {groups.map((g) => <Group key={g.label} label={g.label} rows={g.rows} />)}
        </>
      )}
    </div>
  )
}
