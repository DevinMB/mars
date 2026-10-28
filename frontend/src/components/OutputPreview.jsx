import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Spinner } from './ui'

// The rows a statement would produce, before it is deployed anywhere.
//
// Only the source tables are created to run this; the sink is never defined, so
// a preview cannot write to Kafka, a database or a light switch. Worth saying in
// the UI, because "run my job and show me" is otherwise a frightening button.
// `controls` goes on the editor's bar; `panel` (progress and rows) below it.
export function useOutputPreview({ sql, refs, targetName }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [start, setStart] = useState('earliest')

  const run = async () => {
    setBusy(true); setError(null); setResult(null)
    try {
      setResult(await api.previewJob({
        sql_text: sql, catalog_refs: refs, target_name: targetName || null,
        limit: 20, start,
      }))
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const controls = (
    <>
      <select aria-label="Preview starting position" className="input input-compact w-auto" value={start}
              onChange={(e) => setStart(e.target.value)} disabled={busy}>
        <option value="earliest">from the start of the topic</option>
        <option value="latest">only new records</option>
      </select>
      <button type="button" className="btn-secondary py-1!" onClick={run}
              disabled={busy || !sql.trim() || refs.length === 0}
              title="Runs the query with no sink attached, so it cannot write anything.">
        {busy ? 'Running…' : 'Preview output'}
      </button>
    </>
  )

  const panel = (busy || error || result) && (
    <div className="mt-3">

      {busy && (
        <div className="mt-3">
          <Spinner label="Starting the query and waiting for rows — this takes a moment" />
        </div>
      )}

      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {result?.error && !busy && (
        <div className="mt-3"><Alert level="warning">{result.error}</Alert></div>
      )}

      {result && !result.error && !busy && (
        <div className="mt-3">
          <p className="text-xs text-slate-500 mb-1">
            {result.rows.length} row{result.rows.length === 1 ? '' : 's'}, as they would
            be written.
          </p>
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
                      <td key={j} className="px-3 py-1.5 mono text-xs text-slate-700
                                             max-w-xs truncate"
                          title={cell === null ? 'null' : String(cell)}>
                        {cell === null
                          ? <span className="text-slate-400">null</span>
                          : String(cell)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )

  return { controls, panel }
}

export default function OutputPreview(props) {
  const { controls, panel } = useOutputPreview(props)
  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <div className="flex items-center gap-3 flex-wrap">{controls}</div>
      {panel}
    </div>
  )
}
