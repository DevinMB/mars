import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, Field, PageHeader, Spinner } from '../components/ui'

const KINDS = [
  {
    id: 'ollama', label: 'Ollama',
    urlPlaceholder: 'http://ollama.example.test:11434',
    modelPlaceholder: 'qwen3:8b',
    note: 'A model you run yourself. Nothing leaves your network.',
    auth: 'none', header: '',
  },
  {
    id: 'anthropic', label: 'Claude (Anthropic)',
    urlPlaceholder: 'https://api.anthropic.com',
    modelPlaceholder: 'claude-sonnet-5',
    note: 'Anthropic’s hosted API. Prompts are sent to Anthropic.',
    auth: 'header', header: 'x-api-key',
  },
  {
    id: 'openai-compatible', label: 'OpenAI-compatible',
    urlPlaceholder: 'http://localhost:8000',
    modelPlaceholder: 'gpt-4o-mini',
    note: 'Anything serving the OpenAI chat API — vLLM, LM Studio, Azure, a gateway.',
    auth: 'bearer', header: '',
  },
]

const AUTH = [
  { id: 'none', label: 'None',
    hint: 'For a server on your own network that does not ask for a credential.' },
  { id: 'bearer', label: 'Bearer token',
    hint: 'Sent as Authorization: Bearer <secret>.' },
  { id: 'header', label: 'API key in a header',
    hint: 'Sent as <header>: <secret>. Anthropic uses x-api-key; Azure uses api-key.' },
  { id: 'basic', label: 'Username and password',
    hint: 'Sent as HTTP basic auth, with the secret as the password.' },
]

// Header name/value pairs. A trailing empty row is always present so adding one
// needs no button.
function HeaderRows({ value, onChange }) {
  const rows = Object.entries(value)
  const rename = (from, to) => {
    const next = {}
    for (const [k, v] of rows) next[k === from ? to : k] = v
    onChange(next)
  }
  return (
    <div className="space-y-2">
      {[...rows, ['', '']].map(([k, v], i) => {
        const isNew = i === rows.length
        return (
          <div key={i} className="flex gap-2">
            <input
              className="input mono flex-1 min-w-0" aria-label={`Header ${i + 1} name`} placeholder="header" value={k}
              onChange={(e) => (isNew
                ? onChange({ ...value, [e.target.value]: '' })
                : rename(k, e.target.value))}
            />
            <input
              className="input mono flex-1 min-w-0" aria-label={`Header ${i + 1} value`} placeholder="value" value={v}
              disabled={isNew}
              onChange={(e) => onChange({ ...value, [k]: e.target.value })}
            />
            <button
              type="button"
              className="btn-secondary text-sm shrink-0"
              disabled={isNew}
              onClick={() => {
                const next = { ...value }
                delete next[k]
                onChange(next)
              }}
            >
              Remove
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default function Ai() {
  const [form, setForm] = useState(null)
  const [secretNames, setSecretNames] = useState([])
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.aiProvider()
      .then((p) => setForm({
        kind: p.kind, base_url: p.base_url, model: p.model,
        secret_name: p.secret_name || '', enabled: p.enabled,
        timeout_seconds: p.timeout_seconds,
        auth_method: p.auth_method, auth_header: p.auth_header,
        auth_username: p.auth_username, extra_headers: p.extra_headers || {},
        temperature: p.temperature, max_tokens: p.max_tokens,
      }))
      .catch((e) => setError(e.message))
    api.secrets().then((ss) => setSecretNames(ss.map((x) => x.name))).catch(() => {})
  }, [])

  if (error && !form) return <Alert level="danger" title="Could not load">{error}</Alert>
  if (!form) return <Spinner />

  const kind = KINDS.find((k) => k.id === form.kind) || KINDS[0]
  const auth = AUTH.find((a) => a.id === form.auth_method) || AUTH[0]
  const needsSecret = form.auth_method !== 'none'
  const set = (patch) => { setForm({ ...form, ...patch }); setResult(null); setSaved(false) }

  const body = () => ({
    kind: form.kind,
    base_url: form.base_url,
    model: form.model,
    secret_name: form.secret_name || null,
    enabled: form.enabled,
    timeout_seconds: Number(form.timeout_seconds) || 120,
    auth_method: form.auth_method,
    auth_header: form.auth_header,
    auth_username: form.auth_username,
    extra_headers: form.extra_headers,
    temperature: String(form.temperature),
    max_tokens: Number(form.max_tokens) || 1500,
  })

  const test = async () => {
    setTesting(true); setError(null)
    // Tests what is on screen rather than what is stored, so a configuration can
    // be proven before it is committed.
    try { setResult(await api.testAiProvider(body())) }
    catch (e) { setError(e.message) }
    finally { setTesting(false) }
  }

  const save = async () => {
    setSaving(true); setError(null)
    try { await api.setAiProvider(body()); setSaved(true) }
    catch (e) { setError(e.message) }
    finally { setSaving(false) }
  }

  return (
    <>
      <PageHeader
        title="AI provider"
        subtitle="Configure the model used for SQL drafting."
        actions={
          <>
            <button className="btn-secondary" onClick={test} disabled={testing}>
              {testing ? 'Testing…' : 'Test connection'}
            </button>
            <button className="btn-primary" onClick={save} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </>
        }
      />

      {error && (
        <div className="mb-4">
          <Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert>
        </div>
      )}
      {saved && (
        <div className="mb-4">
          <Alert level="success" onDismiss={() => setSaved(false)}>Saved.</Alert>
        </div>
      )}

      {result && (
        <div className="mb-4">
          <Alert level={result.ok ? 'success' : 'warning'}
                 title={result.ok ? 'Connected' : 'Not usable yet'}>
            {result.detail}
            {result.models?.length > 0 && (
              <div className="mt-1 text-xs">
                Models on that server: {result.models.slice(0, 12).join(', ')}
                {result.models.length > 12 ? '…' : ''}
              </div>
            )}
          </Alert>
        </div>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_240px]">
        <div className="space-y-6 min-w-0">
          <div className="form-section">
            <h2 className="font-medium text-slate-900 mb-1">Provider</h2>
            <p className="text-xs text-slate-500 mb-4">{kind.note}</p>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Provider">
                <select
                  className="input" value={form.kind}
                  onChange={(e) => {
                    const next = KINDS.find((k) => k.id === e.target.value)
                    // The usual auth answer differs per provider, so it moves
                    // with the choice. Still editable: a gateway in front of any
                    // of these can change the answer.
                    set({
                      kind: next.id,
                      auth_method: next.auth,
                      auth_header: next.header,
                      base_url: next.id === 'anthropic' ? '' : form.base_url,
                    })
                  }}
                >
                  {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
                </select>
              </Field>

              <Field label="Model" required hint="Exactly as the provider names it.">
                <input className="input mono" value={form.model}
                       placeholder={kind.modelPlaceholder}
                       onChange={(e) => set({ model: e.target.value })} />
              </Field>

              <Field
                label="Base URL"
                hint={form.kind === 'anthropic'
                  ? 'Optional. Blank uses Anthropic’s own endpoint.'
                  : 'As reachable from the MARS container, not from your laptop.'}
              >
                <input className="input mono" value={form.base_url}
                       placeholder={kind.urlPlaceholder}
                       onChange={(e) => set({ base_url: e.target.value })} />
              </Field>

              <Field label="Request timeout (seconds)"
                     hint="A local model on a busy GPU can take a while.">
                <input className="input mono" value={form.timeout_seconds}
                       onChange={(e) => set({ timeout_seconds: e.target.value })} />
              </Field>
            </div>
          </div>

          <div className="form-section">
            <h2 className="font-medium text-slate-900 mb-1">Authentication</h2>
            <p className="text-xs text-slate-500 mb-4">
              Choose a stored secret for the provider credential.
            </p>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Method" hint={auth.hint}>
                <select className="input" value={form.auth_method}
                        onChange={(e) => set({ auth_method: e.target.value })}>
                  {AUTH.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
                </select>
              </Field>

              {form.auth_method === 'header' && (
                <Field label="Header name" required
                       hint="Anthropic: x-api-key. Azure OpenAI: api-key.">
                  <input className="input mono" value={form.auth_header}
                         placeholder="x-api-key"
                         onChange={(e) => set({ auth_header: e.target.value })} />
                </Field>
              )}

              {form.auth_method === 'basic' && (
                <Field label="Username">
                  <input className="input mono" value={form.auth_username}
                         onChange={(e) => set({ auth_username: e.target.value })} />
                </Field>
              )}

              <Field
                label={form.auth_method === 'basic' ? 'Password (secret)' : 'Credential (secret)'}
                required={needsSecret}
                hint={needsSecret
                  ? 'Add it under Secrets first; it is never shown here.'
                  : 'Not needed for this method.'}
              >
                <select className="input" value={form.secret_name} disabled={!needsSecret}
                        onChange={(e) => set({ secret_name: e.target.value })}>
                  <option value="">{needsSecret ? 'Choose a secret…' : 'Not required'}</option>
                  {secretNames.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </Field>
            </div>

            <div className="mt-4">
              <Field
                label="Extra headers"
                hint="Non-sensitive values only, such as an API version or project ID. These are stored as plain text. Use Authentication for credentials."
              >
                <HeaderRows value={form.extra_headers}
                            onChange={(v) => set({ extra_headers: v })} />
              </Field>
            </div>
          </div>

          <div className="form-section">
            <h2 className="font-medium text-slate-900 mb-4">Generation</h2>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Temperature"
                     hint="0 keeps answers repeatable, which is what drafting SQL wants.">
                <input className="input mono" value={form.temperature}
                       onChange={(e) => set({ temperature: e.target.value })} />
              </Field>
              <Field label="Maximum tokens" hint="The longest answer the model may return.">
                <input className="input mono" value={form.max_tokens}
                       onChange={(e) => set({ max_tokens: e.target.value })} />
              </Field>
            </div>
          </div>
        </div>

        <aside className="space-y-4">
          <div className="border-b border-slate-200 pb-5">
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium text-slate-900">Status</h3>
              {form.enabled ? <Badge tone="accent">On</Badge> : <Badge tone="slate">Off</Badge>}
            </div>
            <label className="flex items-start gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={form.enabled}
                     className="mt-0.5 rounded border-slate-300 text-brand-600 focus:ring-brand-500/30"
                     onChange={(e) => set({ enabled: e.target.checked })} />
              <span>
                Enable AI features
                <span className="block text-xs text-slate-500 mt-0.5">
                  While this is off, every feature that would use a model stays
                  inactive and nothing is sent anywhere.
                </span>
              </span>
            </label>
          </div>

          <div className="border-b border-slate-200 pb-5">
            <h3 className="text-sm font-medium text-slate-900 mb-2">Where this is used</h3>
            <ul className="text-xs text-slate-500 space-y-1.5">
              <li>
                <span className="text-slate-700">Drafting a job from a description</span>{' '}
                — in the job editor, grounded in the tables that job uses.
              </li>
              <li>
                <span className="text-slate-700">Changing a statement you already have</span>{' '}
                — described in words, returned as a diff.
              </li>
            </ul>
            <p className="text-xs text-slate-500 mt-2">
              Review and apply proposed SQL in the job editor. Drafting does not run jobs.
            </p>
          </div>

          {form.kind !== 'ollama' && (
            <Alert level="warning" title="Prompts leave your network">
              Table names, column names and sampled field names are sent to this
              provider when a feature uses it. A model you host yourself keeps them
              on your own network.
            </Alert>
          )}
        </aside>
      </div>
    </>
  )
}
