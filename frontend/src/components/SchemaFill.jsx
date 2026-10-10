import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Spinner } from './ui'

// Reads an Avro schema from the registry and writes the columns.
//
// Only appears when the format is Avro and a registry is configured — the point
// is that it is optional, not that it is hidden.
//
// This matters more than sampling a JSON topic does. With JSON an undeclared
// field is merely absent; with Avro the columns are the contract, and getting one
// type wrong is a runtime failure. The registry holds the right answer already.
export default function SchemaFill({ topic, onColumns }) {
  const [available, setAvailable] = useState(null)
  const [subjects, setSubjects] = useState(null)
  const [subject, setSubject] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.schemaRegistry()
      .then((r) => setAvailable(Boolean(r.configured)))
      .catch(() => setAvailable(false))
  }, [])

  // The convention is <topic>-value, so offer it rather than making someone
  // remember it — but let them pick anything, because conventions get broken.
  useEffect(() => {
    if (topic && !subject) setSubject(`${topic}-value`)
  }, [topic]) // eslint-disable-line react-hooks/exhaustive-deps

  if (available === null) return null
  if (!available) {
    return (
      <div className="mt-4 border-t border-slate-200 pt-4">
        <p className="text-xs text-slate-500">
          With a schema registry configured under Administration, the columns for an
          Avro topic can be read from its registered schema instead of typed by hand.
        </p>
      </div>
    )
  }

  const browse = async () => {
    setBusy(true); setError(null)
    try { setSubjects(await api.registrySubjects()) }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }

  const fetchSchema = async () => {
    setBusy(true); setError(null); setResult(null)
    try {
      const r = await api.registrySchema(subject)
      setResult(r)
      onColumns(r.columns.map((c) => ({ name: c.name, sqlType: c.sqlType })))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <div className="flex items-end gap-2 flex-wrap">
        <label className="flex-1 min-w-56">
          <span className="label">Subject</span>
          <input className="input mono" value={subject} list="registry-subjects"
                 placeholder="my-topic-value"
                 onChange={(e) => setSubject(e.target.value)} />
        </label>
        <datalist id="registry-subjects">
          {(subjects || []).map((s) => <option key={s} value={s} />)}
        </datalist>
        <button type="button" className="btn-secondary text-sm" onClick={browse} disabled={busy}>
          {subjects ? `${subjects.length} subjects` : 'List subjects'}
        </button>
        <button type="button" className="btn-primary text-sm" onClick={fetchSchema}
                disabled={busy || !subject.trim()}>
          Fill columns from the schema
        </button>
      </div>

      {busy && <div className="mt-3"><Spinner label="Reading the registry" /></div>}
      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {result && !busy && (
        <div className="mt-3 space-y-2">
          <Alert level="success">
            {result.columns.length} column{result.columns.length === 1 ? '' : 's'} from{' '}
            <code className="mono">{result.subject}</code>
            {result.version ? `, version ${result.version}` : ''}. The list below has been
            replaced — check it before saving.
          </Alert>
          {/* Said out loud, because a silent mapping is one nobody can check. */}
          {result.columns.some((c) => c.note) && (
            <ul className="text-xs text-slate-500 space-y-0.5">
              {result.columns.filter((c) => c.note).map((c) => (
                <li key={c.name}>
                  <code className="mono text-slate-700">{c.name}</code> — {c.note}
                </li>
              ))}
            </ul>
          )}
          {result.warnings.map((w, i) => (
            <Alert key={i} level="warning">{w}</Alert>
          ))}
        </div>
      )}
    </div>
  )
}
