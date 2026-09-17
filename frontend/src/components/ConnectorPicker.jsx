import { useMemo, useState } from 'react'
import SearchInput from './SearchInput'

// Choosing a connector from a dropdown stops working once there are more than a
// handful: the option text is just an identifier, so you cannot tell couchdb from
// http without already knowing. This shows the description alongside, and filters,
// because the list grows every time somebody drops a connector JAR in.
export default function ConnectorPicker({ connectors, value, onChange, disabled }) {
  const [query, setQuery] = useState('')

  const hits = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return connectors
    return connectors.filter(
      (c) =>
        c.connector.toLowerCase().includes(q) ||
        c.displayName.toLowerCase().includes(q) ||
        (c.description || '').toLowerCase().includes(q),
    )
  }, [connectors, query])

  if (disabled) {
    const current = connectors.find((c) => c.connector === value)
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-md border border-slate-200
                      bg-slate-50 text-sm text-slate-600">
        <span className="font-medium text-slate-800">{current?.displayName || value}</span>
        <span className="mono text-xs text-slate-400">{value}</span>
        <span className="ml-auto text-xs text-slate-400">cannot be changed</span>
      </div>
    )
  }

  return (
    <div>
      {connectors.length > 5 && (
        <div className="mb-2">
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Filter connectors…"
            count={hits.length}
          />
        </div>
      )}

      {hits.length === 0 ? (
        <p className="text-xs text-slate-500 py-2">No connector matches “{query}”.</p>
      ) : (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {hits.map((c) => {
            const on = c.connector === value
            return (
              <button
                key={c.connector}
                type="button"
                aria-pressed={on}
                onClick={() => onChange(c.connector)}
                className={`text-left px-3 py-2.5 rounded-md border transition-colors ${
                  on
                    ? 'border-brand-500 bg-brand-50/60 ring-1 ring-brand-500/20'
                    : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-medium ${on ? 'text-brand-800' : 'text-slate-800'}`}>
                    {c.displayName}
                  </span>
                  <span className="mono text-[11px] text-slate-400">{c.connector}</span>
                </div>
                {c.description && (
                  <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">{c.description}</p>
                )}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
