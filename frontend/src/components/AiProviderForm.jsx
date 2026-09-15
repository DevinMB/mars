import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Field, Spinner } from './ui'

const KINDS = [
  { id: 'ollama', label: 'Ollama', needsKey: false,
    urlPlaceholder: 'http://192.168.1.10:11434',
    modelPlaceholder: 'qwen3:8b',
    note: 'A model you run yourself. Nothing leaves your network.' },
  { id: 'anthropic', label: 'Claude', needsKey: true,
    urlPlaceholder: 'https://api.anthropic.com',
    modelPlaceholder: 'claude-sonnet-5',
    note: 'Anthropic’s hosted API. Prompts are sent to Anthropic.' },
  { id: 'openai-compatible', label: 'OpenAI-compatible', needsKey: true,
    urlPlaceholder: 'http://localhost:8000',
    modelPlaceholder: 'gpt-4o-mini',
    note: 'Anything serving the OpenAI chat API — vLLM, LM Studio, a gateway.' },
]

export default function AiProviderForm({ secretNames = [] }) {
  const [form, setForm] = useState(null)
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
      }))
      .catch((e) => setError(e.message))
  }, [])

  if (error && !form) return <Alert level="danger">{error}</Alert>
  if (!form) return <Spinner />

  const kind = KINDS.find((k) => k.id === form.kind) || KINDS[0]
  const set = (patch) => { setForm({ ...form, ...patch }); setResult(null); setSaved(false) }

  const body = () => ({
    kind: form.kind,
    base_url: form.base_url,
    model: form.model,
    secret_name: form.secret_name || null,
    enabled: form.enabled,
    timeout_seconds: Number(form.timeout_seconds) || 120,
  })

  const test = async () => {
    setTesting(true); setError(null)
    // Tests what is on screen, not what is stored, so settings can be proven
    // before they are committed.
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
    <div className="card p-5 mb-4">
      <h2 className="font-medium text-slate-900 mb-1">AI provider</h2>
      <p className="text-xs text-slate-500 mb-4">
        Configured once here and used by every feature in MARS that needs a model.
        Until it is enabled, those features stay off and nothing is sent anywhere.
      </p>

      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
      {saved && <div className="mb-3"><Alert level="success" onDismiss={() => setSaved(false)}>Saved.</Alert></div>}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Provider" hint={kind.note}>
          <select className="input" value={form.kind}
                  onChange={(e) => {
                    const next = KINDS.find((k) => k.id === e.target.value)
                    set({ kind: e.target.value, base_url: next.id === 'anthropic' ? '' : form.base_url })
                  }}>
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
            : 'Where the server is reachable from the MARS container.'}
        >
          <input className="input mono" value={form.base_url}
                 placeholder={kind.urlPlaceholder}
                 onChange={(e) => set({ base_url: e.target.value })} />
        </Field>

        <Field
          label="API key"
          required={kind.needsKey}
          hint={kind.needsKey
            ? 'Held in the secret store, encrypted, like any other credential.'
            : 'Not needed for a local Ollama.'}
        >
          <select className="input" value={form.secret_name}
                  disabled={!kind.needsKey}
                  onChange={(e) => set({ secret_name: e.target.value })}>
            <option value="">{kind.needsKey ? 'Choose a secret…' : 'Not required'}</option>
            {secretNames.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </Field>
      </div>

      <label className="flex items-center gap-2 mt-4 text-sm text-slate-700">
        <input type="checkbox" checked={form.enabled}
               className="rounded border-slate-300 text-brand-600 focus:ring-brand-500/30"
               onChange={(e) => set({ enabled: e.target.checked })} />
        Enable AI features
      </label>

      {result && (
        <div className="mt-3">
          <Alert level={result.ok ? 'success' : 'warning'}>
            {result.detail}
            {result.models?.length > 0 && (
              <div className="mt-1 text-xs">
                Available: {result.models.slice(0, 12).join(', ')}
                {result.models.length > 12 ? '…' : ''}
              </div>
            )}
          </Alert>
        </div>
      )}

      <div className="flex gap-2 mt-4">
        <button className="btn-secondary text-sm" onClick={test} disabled={testing}>
          {testing ? 'Testing…' : 'Test connection'}
        </button>
        <button className="btn-primary text-sm" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}
