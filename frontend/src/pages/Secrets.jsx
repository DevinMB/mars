import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { Alert, EmptyState, Field, PageHeader, Spinner } from '../components/ui'

export default function Secrets() {
  const [secrets, setSecrets] = useState(null)
  const [error, setError] = useState(null)
  const [adding, setAdding] = useState(false)
  const [name, setName] = useState('')
  const [value, setValue] = useState('')
  const [description, setDescription] = useState('')

  const load = async () => {
    try { setSecrets(await api.secrets()); setError(null) }
    catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [])

  const save = async (e) => {
    e.preventDefault()
    try {
      await api.putSecret(name, value, description || undefined)
      setName(''); setValue(''); setDescription(''); setAdding(false)
      load()
    } catch (err) { setError(err.message) }
  }

  const remove = async (n) => {
    if (!confirm(`Delete secret "${n}"?`)) return
    try { await api.deleteSecret(n); load() }
    catch (err) { setError(err.message) }
  }

  if (!secrets) return <Spinner label="Loading secrets" />

  return (
    <>
      <PageHeader
        title="Secrets"
        subtitle="Referenced from table definitions, never stored in them. Administrators only."
        actions={!adding && <button className="btn-primary" onClick={() => setAdding(true)}>New secret</button>}
      />

      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="mb-6">
        <Alert level="info">
          A secret is written once and never readable again — not through the API, not by
          an administrator. Table definitions hold a reference like{' '}
          <code className="mono">{'${secret:couch_password}'}</code>, and the value is
          substituted only as a job is handed to Flink.
        </Alert>
      </div>

      {adding && (
        <form onSubmit={save} className="card p-6 space-y-4 mb-6 max-w-lg">
          <Field label="Name" required hint="Letters, digits, dot, dash or underscore.">
            <input className="input mono" value={name} autoFocus
                   onChange={(e) => setName(e.target.value)} placeholder="couch_password" />
          </Field>
          <Field label="Value" required>
            <input className="input" type="password" value={value}
                   onChange={(e) => setValue(e.target.value)} />
          </Field>
          <Field label="Description">
            <input className="input" value={description}
                   onChange={(e) => setDescription(e.target.value)} placeholder="CouchDB admin on 192.168.1.250" />
          </Field>
          <div className="flex gap-2">
            <button className="btn-primary" disabled={!name || !value}>Save secret</button>
            <button type="button" className="btn-secondary" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </form>
      )}

      {secrets.length === 0 && !adding ? (
        <EmptyState title="No secrets yet" action={<button className="btn-primary" onClick={() => setAdding(true)}>Add one</button>}>
          Store connection passwords here so they stay out of your SQL.
        </EmptyState>
      ) : secrets.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-semibold">Name</th>
                <th className="px-4 py-2.5 font-semibold">Description</th>
                <th className="px-4 py-2.5 font-semibold">Updated</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {secrets.map((s) => (
                <tr key={s.name} className="hover:bg-slate-50/60">
                  <td className="px-4 py-3 mono text-slate-900">{s.name}</td>
                  <td className="px-4 py-3 text-slate-600">{s.description || '—'}</td>
                  <td className="px-4 py-3 text-slate-500">{relativeTime(s.updated_at)}</td>
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => remove(s.name)}
                            className="text-slate-400 hover:text-red-600 text-sm">Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
