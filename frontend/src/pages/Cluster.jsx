import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, PageHeader, Spinner } from '../components/ui'

function Stat({ label, value, tone = 'slate' }) {
  const tones = { slate: 'text-slate-900', good: 'text-emerald-600', bad: 'text-red-600' }
  return (
    <div className="card p-4">
      <div className="eyebrow">{label}</div>
      <div className={`text-[22px] font-semibold mt-1 tabular-nums ${tones[tone]}`}>{value}</div>
    </div>
  )
}

// A target is a Flink cluster jobs can be sent to.
//
// Worth stating plainly on this page, because it is the thing people expect to work
// differently: a session cluster's scheduler puts tasks in whatever slot is free,
// and there is no supported way to pin a job to a machine within one. Choosing where
// a job runs means choosing which cluster receives it.
function TargetCard({ target }) {
  const labels = Object.entries(target.labels || {})
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="mono text-[13px] font-medium text-slate-900">{target.name}</span>
            {target.is_default && <Badge tone="accent">default</Badge>}
            {!target.enabled && <Badge>disabled</Badge>}
          </div>
          {target.description && (
            <p className="text-[12px] text-slate-500 mt-0.5">{target.description}</p>
          )}
        </div>
        <span className="flex items-center gap-1.5 text-[12px] shrink-0">
          <span className={`w-2 h-2 rounded-full ${target.reachable ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <span className={target.reachable ? 'text-slate-600' : 'text-red-700'}>
            {target.reachable ? `Flink ${target.flink_version}` : 'unreachable'}
          </span>
        </span>
      </div>

      <dl className="grid grid-cols-3 gap-3 mt-3 text-[12px]">
        <div>
          <dt className="text-slate-500">Jobs</dt>
          <dd className="text-slate-900 tabular-nums">{target.job_count}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Slots free</dt>
          <dd className="text-slate-900 tabular-nums">
            {target.reachable ? `${target.slots_available} / ${target.slots_total}` : '—'}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className="text-slate-500">REST</dt>
          <dd className="mono text-[11px] text-slate-500 truncate">{target.flink_rest_url}</dd>
        </div>
      </dl>

      {labels.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-3">
          {labels.map(([k, v]) => (
            <span key={k} className="text-[11px] bg-slate-100 text-slate-600 rounded px-1.5 py-0.5">
              {k}={v}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function Cluster() {
  const [targets, setTargets] = useState(null)
  const [connectors, setConnectors] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [t, k] = await Promise.all([api.targets(), api.connectors()])
        if (alive) { setTargets(t); setConnectors(k); setError(null) }
      } catch (err) {
        if (alive) setError(err.message)
      }
    }
    load()
    const id = setInterval(load, 10000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (error && !targets) return <Alert level="danger" title="Could not load targets">{error}</Alert>
  if (!targets) return <Spinner label="Reading clusters" />

  const up = targets.filter((t) => t.reachable)
  const slotsTotal = up.reduce((n, t) => n + (t.slots_total || 0), 0)
  const slotsFree = up.reduce((n, t) => n + (t.slots_available || 0), 0)

  return (
    <>
      <PageHeader
        title="Cluster"
        subtitle={
          targets.length === 1
            ? 'One execution target. Add another to run jobs on separate hardware.'
            : `${targets.length} execution targets, ${up.length} reachable`
        }
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <Stat label="Targets" value={`${up.length} / ${targets.length}`}
              tone={up.length < targets.length ? 'bad' : 'slate'} />
        <Stat label="Slots free" value={`${slotsFree} / ${slotsTotal}`}
              tone={slotsFree === 0 ? 'bad' : 'slate'} />
        <Stat label="Jobs placed" value={targets.reduce((n, t) => n + t.job_count, 0)} />
        <Stat label="Connectors" value={connectors.length} />
      </div>

      <h2 className="eyebrow-accent mb-3">Execution targets</h2>
      <p className="text-[12px] text-slate-500 mb-3 max-w-2xl">
        A target is a Flink cluster jobs can be sent to. A cluster schedules tasks into
        whatever slot is free, so choosing where a job runs means choosing the cluster —
        there is no supported way to pin a job to one machine inside a cluster.
      </p>
      <div className="grid gap-3 lg:grid-cols-2 mb-8">
        {targets.map((t) => <TargetCard key={t.name} target={t} />)}
      </div>

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h2 className="font-medium text-slate-900 text-[14px]">Installed connectors</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Each contributes its own form. Drop a connector JAR containing a manifest into
            the Flink library directory and it appears here.
          </p>
        </div>
        <table className="tbl">
          <thead>
            <tr><th>Connector</th><th>Use</th><th>Options</th><th>Provided by</th></tr>
          </thead>
          <tbody>
            {connectors.map((c) => (
              <tr key={c.connector}>
                <td>
                  <div className="font-medium text-slate-900">{c.displayName}</div>
                  {c.description && (
                    <div className="text-[11px] text-slate-500 max-w-lg">{c.description}</div>
                  )}
                </td>
                <td className="text-slate-600">{c.kinds.join(', ')}</td>
                <td className="text-slate-600 tabular-nums">{c.options.length}</td>
                <td><code className="mono text-[11px] text-slate-500">{c.source}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
