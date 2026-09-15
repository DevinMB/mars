import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Spinner } from './ui'

// Reads a few records from a source while it is still being defined.
//
// Defining a source is exactly when someone wants to know what is in the topic,
// and requiring a save first means committing a definition to find out whether it
// was right. Nothing is created: the definition is rendered, used once, and
// discarded.
export default function SourcePeek({ connector, options, columns, name }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [start, setStart] = useState('earliest')

  const run = async () => {
    setBusy(true); setResult(null)
    try {
      setResult(await api.sampleDraft({
        connector, options, name: name || 'draft_source',
        columns: (columns || []).map((c) => ({ name: c.name, sqlType: c.sqlType })),
        limit: 5, start,
      }))
    } catch (e) {
      setResult({ error: e.message })
    } finally {
      setBusy(false)
    }
  }

  const nested = Object.entries(result?.nested || {})

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <div className="flex items-center gap-3 flex-wrap">
        <button type="button" className="btn-secondary text-sm" onClick={run} disabled={busy}>
          {busy ? 'Reading…' : 'Look inside'}
        </button>
        <select className="input w-auto text-sm" value={start} disabled={busy}
                onChange={(e) => setStart(e.target.value)}>
          <option value="earliest">from the start</option>
          <option value="latest">only new records</option>
        </select>
        <span className="text-xs text-slate-500">
          Reads a few real records with a throwaway consumer group, so it cannot
          disturb anything already running.
        </span>
      </div>

      {busy && <div className="mt-3"><Spinner label="Starting a reader and waiting for records" /></div>}

      {result?.error && !busy && (
        <div className="mt-3"><Alert level="warning">{result.error}</Alert></div>
      )}

      {result && !result.error && !busy && (
        <div className="mt-3 space-y-3">
          <div className="overflow-x-auto rounded-md border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                  {result.columns.map((c) => (
                    <th key={c} className="px-3 py-2 font-medium mono">{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {result.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((cell, j) => (
                      <td key={j} className="px-3 py-1.5 mono text-xs text-slate-700 max-w-xs truncate"
                          title={cell === null ? 'null' : String(cell)}>
                        {cell === null ? <span className="text-slate-400">null</span> : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* The part a declared schema cannot tell you: what is inside a
              document carried as text. */}
          {nested.map(([column, fields]) => (
            <div key={column}>
              <p className="text-xs text-slate-500 mb-1">
                Inside <code className="mono">{column}</code>, across {result.rows.length}{' '}
                record{result.rows.length === 1 ? '' : 's'}:
              </p>
              <div className="flex flex-wrap gap-1.5">
                {fields.map((f) => (
                  <span key={f.name}
                        title={f.example ? `e.g. ${f.example}` : undefined}
                        className={`text-xs px-2 py-0.5 rounded mono ${
                          f.type.includes(' or ')
                            ? 'bg-amber-50 text-amber-800'
                            : 'bg-slate-100 text-slate-700'
                        }`}>
                    {f.name}
                    <span className="text-slate-400 ml-1">{f.type}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
