import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Field, Spinner } from './ui'

const AUTH = [
  { id: 'none', label: 'None' },
  { id: 'basic', label: 'Username and password' },
  { id: 'bearer', label: 'Bearer token' },
]

// Optional. Configure one and the catalog editor can read an Avro schema and
// write the columns for you; leave it alone and nothing about Avro appears.
export default function RegistryPanel({ secretNames = [] }) {
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.schemaRegistry()
      .then((r) => setForm({
        url: r.url, auth_method: r.auth_method, username: r.username,
        secret_name: r.secret_name || '', enabled: r.enabled,
        timeout_seconds: r.timeout_seconds,
      }))
      .catch((e) => setError(e.message))
  }, [])

  if (error && !form) return <Alert level="danger">{error}</Alert>
  if (!form) return <div className="card p-5 mb-4"><Spinner /></div>

  const needsSecret = form.auth_method !== 'none'
  const set = (patch) => { setForm({ ...form, ...patch }); setResult(null); setSaved(false) }
  const body = () => ({ ...form, secret_name: form.secret_name || null,
                        timeout_seconds: Number(form.timeout_seconds) || 10 })

  const act = async (label, fn) => {
    setBusy(label); setError(null)
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  return (
    <div className="card p-5 mb-4">
      <h2 className="font-medium text-slate-900 mb-1">Schema registry</h2>
      <p className="text-xs text-slate-500 mb-4">
        Optional. With one configured, a Kafka source using Avro can have its columns
        read straight from the registered schema instead of typed by hand — which
        matters more for Avro than for JSON, because with Avro the columns are the
        contract and a mismatch fails at runtime rather than arriving empty.
      </p>

      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
      {saved && <div className="mb-3"><Alert level="success" onDismiss={() => setSaved(false)}>Saved.</Alert></div>}
      {result && (
        <div className="mb-3">
          <Alert level={result.ok ? 'success' : 'warning'}>{result.detail}</Alert>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Address" hint="As reachable from the MARS container.">
          <input className="input mono" value={form.url}
                 placeholder="http://schema-registry:8081"
                 onChange={(e) => set({ url: e.target.value })} />
        </Field>
        <Field label="Authentication">
          <select className="input" value={form.auth_method}
                  onChange={(e) => set({ auth_method: e.target.value })}>
            {AUTH.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
          </select>
        </Field>
        {form.auth_method === 'basic' && (
          <Field label="Username">
            <input className="input mono" value={form.username}
                   onChange={(e) => set({ username: e.target.value })} />
          </Field>
        )}
        <Field
          label={form.auth_method === 'basic' ? 'Password (secret)' : 'Credential (secret)'}
          required={needsSecret}
          hint={needsSecret ? 'Held in the secret store, like any other.' : 'Not needed.'}
        >
          <select className="input" value={form.secret_name} disabled={!needsSecret}
                  onChange={(e) => set({ secret_name: e.target.value })}>
            <option value="">{needsSecret ? 'Choose a secret…' : 'Not required'}</option>
            {secretNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
      </div>

      <label className="flex items-center gap-2 mt-4 text-sm text-slate-700">
        <input type="checkbox" checked={form.enabled}
               className="rounded border-slate-300 text-brand-600 focus:ring-brand-500/30"
               onChange={(e) => set({ enabled: e.target.checked })} />
        Use this registry
      </label>

      <div className="flex gap-2 mt-4">
        <button className="btn-secondary text-sm" disabled={busy === 'test'}
                onClick={() => act('test', async () => setResult(await api.testSchemaRegistry(body())))}>
          {busy === 'test' ? 'Testing…' : 'Test connection'}
        </button>
        <button className="btn-primary text-sm" disabled={busy === 'save'}
                onClick={() => act('save', async () => { await api.setSchemaRegistry(body()); setSaved(true) })}>
          {busy === 'save' ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}
