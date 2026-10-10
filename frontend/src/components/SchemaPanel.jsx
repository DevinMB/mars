import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Spinner } from './ui'

// Most sources here carry an opaque JSON document in one STRING column, so the
// declared schema reads `record_key, doc` and says nothing about what can be
// selected. The declared columns are always shown; the fields inside a document
// need a real record, which is what "Look inside" fetches.
export default function SchemaPanel({ entry, onInsert, onSampled }) {
  const [sample, setSample] = useState(null)
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)

  const look = async () => {
    setLoading(true)
    setOpen(true)
    try {
      const s = await api.sampleEntry(entry.name, 5)
      setSample(s)
      // Hand the discovered fields up: completion and the description box both
      // need them, and nobody else can discover them without sampling again.
      if (!s.error && onSampled) {
        onSampled(entry.name, Object.fromEntries(
          Object.entries(s.nested || {}).map(([column, fields]) => [
            column, fields.map((f) => f.name),
          ]),
        ))
      }
    }
    catch (err) { setSample({ error: err.message }) }
    finally { setLoading(false) }
  }

  const columns = entry.columns || []
  // A single opaque column is the tell-tale of raw passthrough.
  const opaque = columns.filter((c) => /STRING/i.test(c.type)).map((c) => c.name)

  return (
    <div className="border-t border-slate-100 pt-2 mt-2">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-xs font-medium text-slate-700">{entry.name}</span>
        <button
          onClick={look}
          disabled={loading}
          className="text-xs link shrink-0"
          title="Reads a few real records. Uses a throwaway consumer group, so it cannot disturb a running job."
        >
          {loading ? 'Reading…' : 'Look inside'}
        </button>
      </div>

      {columns.length === 0 ? (
        <p className="text-xs text-slate-400">No columns could be read from this definition.</p>
      ) : (
        <ul className="space-y-0.5">
          {columns.map((c) => (
            <li key={c.name}>
              <button
                onClick={() => onInsert?.(c.name)}
                className="group w-full text-left flex items-baseline gap-2 hover:bg-slate-50 rounded-sm px-1 -mx-1"
                title="Insert into the statement"
              >
                <code className="mono text-xs text-slate-800 group-hover:text-brand-700">
                  {c.name}
                </code>
                <span className="text-[11px] text-slate-400 truncate">{c.type}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <div className="mt-2">
          {loading && <Spinner label="Reading a few records" />}

          {!loading && sample?.error && (
            <Alert level="warning">{sample.error}</Alert>
          )}

          {!loading && sample && !sample.error && (
            <>
              {Object.keys(sample.nested || {}).length === 0 ? (
                <p className="text-xs text-slate-500">
                  The records are not JSON objects, so the columns above are the whole
                  story.
                </p>
              ) : (
                Object.entries(sample.nested).map(([column, fields]) => (
                  <div key={column} className="mt-1">
                    <p className="text-[11px] text-slate-500 mb-1">
                      Inside <code className="mono">{column}</code>, from{' '}
                      {sample.rows.length} record{sample.rows.length === 1 ? '' : 's'}:
                    </p>
                    <ul className="space-y-0.5">
                      {fields.map((f) => (
                        <li key={f.name}>
                          <button
                            onClick={() =>
                              // JSON_VALUE is how a field is pulled out of a
                              // document without declaring a typed schema for it.
                              onInsert?.(`JSON_VALUE(${column}, '$.${f.name}')`)
                            }
                            className="group w-full text-left flex items-baseline gap-2 hover:bg-slate-50 rounded-sm px-1 -mx-1"
                            title={`Insert JSON_VALUE(${column}, '$.${f.name}')`}
                          >
                            <code className="mono text-xs text-slate-700 group-hover:text-brand-700">
                              {f.name}
                            </code>
                            <span className={`text-[11px] truncate ${
                              f.type.includes(' or ') ? 'text-amber-700' : 'text-slate-400'
                            }`}>
                              {f.type}
                            </span>
                            {f.example && (
                              <span className="text-[11px] text-slate-400 truncate ml-auto">
                                {f.example}
                              </span>
                            )}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                ))
              )}
            </>
          )}
        </div>
      )}

      {opaque.length > 0 && !open && (
        <p className="text-[11px] text-slate-400 mt-1">
          Carries a document as text. Look inside to see its fields.
        </p>
      )}
    </div>
  )
}
