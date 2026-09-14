import { useState } from 'react'
import { api } from '../lib/api'
import { Alert, Field } from './ui'

// Adding a cluster without a way to check it means saving a guess and finding out
// at the first submission, so the form probes both URLs before it will save.
export default function TargetForm({ initial, onSaved, onCancel }) {
  const editing = Boolean(initial)
  const [name, setName] = useState(initial?.name || '')
  const [description, setDescription] = useState(initial?.description || '')
  const [restUrl, setRestUrl] = useState(initial?.flink_rest_url || '')
  const [gatewayUrl, setGatewayUrl] = useState(initial?.gateway_url || '')
  const [labels, setLabels] = useState(
    Object.entries(initial?.labels || {}).map(([k, v]) => `${k}=${v}`).join(', '),
  )
  const [enabled, setEnabled] = useState(initial?.enabled ?? true)
  const [isDefault, setIsDefault] = useState(initial?.is_default ?? false)

  const [probe, setProbe] = useState(null)
  const [probing, setProbing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  const parsedLabels = () =>
    Object.fromEntries(
      labels
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean)
        .map((pair) => {
          const i = pair.indexOf('=')
          return i < 0 ? [pair, ''] : [pair.slice(0, i).trim(), pair.slice(i + 1).trim()]
        }),
    )

  const runProbe = async () => {
    setProbing(true)
    setError(null)
    try {
      setProbe(await api.probeTarget(restUrl, gatewayUrl))
    } catch (err) {
      setError(err.message)
    } finally {
      setProbing(false)
    }
  }

  const save = async () => {
    setSaving(true)
    setError(null)
    const body = {
      name,
      description: description || null,
      flink_rest_url: restUrl,
      gateway_url: gatewayUrl,
      labels: parsedLabels(),
      enabled,
      is_default: isDefault,
    }
    try {
      if (editing) await api.updateTarget(initial.name, body)
      else await api.createTarget(body)
      onSaved()
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const reachable = probe?.flink_ok && probe?.gateway_ok
  const canSave = name && restUrl && gatewayUrl && !saving

  const Result = ({ ok, label, detail }) => (
    <div className="flex items-start gap-2 text-[12px]">
      <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${ok ? 'bg-emerald-500' : 'bg-red-500'}`} />
      <span className="min-w-0">
        <span className="font-medium text-slate-700">{label}</span>{' '}
        <span className={ok ? 'text-slate-600' : 'text-red-700'}>{detail}</span>
      </span>
    </div>
  )

  return (
    <div className="card p-5 mb-4">
      <h2 className="eyebrow-accent mb-4">
        {editing ? `Edit ${initial.name}` : 'Add an execution target'}
      </h2>

      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Name"
          required
          hint={editing
            ? 'A target cannot be renamed — jobs reference it by name.'
            : 'Short and stable. Jobs reference it by name and it cannot be renamed later.'}
        >
          <input
            className="input mono"
            value={name}
            disabled={editing}
            placeholder="rack-2"
            onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, ''))}
          />
        </Field>

        <Field label="Description">
          <input className="input" value={description} placeholder="What runs here, and why"
                 onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <Field label="Flink REST url" required hint="Used for job status and cancellation.">
          <input className="input mono" value={restUrl} placeholder="http://newhost:8081"
                 onChange={(e) => { setRestUrl(e.target.value); setProbe(null) }} />
        </Field>

        <Field label="SQL Gateway url" required hint="Used to submit jobs.">
          <input className="input mono" value={gatewayUrl} placeholder="http://newhost:8083"
                 onChange={(e) => { setGatewayUrl(e.target.value); setProbe(null) }} />
        </Field>

        <Field label="Labels" hint="Free-form, comma separated. Descriptive only for now.">
          <input className="input mono" value={labels} placeholder="zone=rack-2, profile=memory"
                 onChange={(e) => setLabels(e.target.value)} />
        </Field>

        <div className="flex flex-col justify-end gap-2 pb-1">
          <label className="inline-flex items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)}
                   className="rounded border-slate-300 text-brand-600 focus:ring-brand-500/30" />
            Accepts jobs
          </label>
          <label className="inline-flex items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" checked={isDefault} onChange={(e) => setIsDefault(e.target.checked)}
                   className="rounded border-slate-300 text-brand-600 focus:ring-brand-500/30" />
            Make this the default
            <span className="text-[11px] text-slate-400">(jobs naming no target run here)</span>
          </label>
        </div>
      </div>

      {probe && (
        <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3 space-y-1.5">
          <Result ok={probe.flink_ok} label="Flink REST" detail={probe.flink_detail} />
          <Result ok={probe.gateway_ok} label="SQL Gateway" detail={probe.gateway_detail} />
          {!reachable && (
            <p className="text-[11px] text-slate-500 pt-1">
              It can still be saved — a target that is down is not a mistake, and MARS
              will show it as unreachable until it comes back.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 mt-4">
        <button className="btn-secondary" onClick={runProbe}
                disabled={probing || !restUrl || !gatewayUrl}>
          {probing ? 'Testing…' : 'Test connection'}
        </button>
        <button className="btn-primary" onClick={save} disabled={!canSave}>
          {saving ? 'Saving…' : editing ? 'Save changes' : 'Add target'}
        </button>
        <button className="btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}
