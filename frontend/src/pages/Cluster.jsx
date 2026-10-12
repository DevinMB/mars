import { useConfirm } from '../components/InteractionProvider'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import AddClusterGuide from '../components/AddClusterGuide'
import { JobMovesGuide, JobMovesLine } from '../components/JobMoves'
import RollingUpgrade from '../components/RollingUpgrade'
import TargetForm from '../components/TargetForm'
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

// A cluster is a Flink cluster jobs can be sent to ("target" in the API).
//
// Worth stating plainly on this page, because it is the thing people expect to work
// differently: a session cluster's scheduler puts tasks in whatever slot is free,
// and there is no supported way to pin a job to a machine within one. Choosing where
// a job runs means choosing which cluster receives it.
function TargetCard({ target, defaultVersion, canManage, onEdit, onRemove, moves, onJobMoves }) {
  // Clusters on different Flink versions can disagree about connectors and state,
  // which shows up as a job that works on one and fails on another.
  const mismatch = target.reachable && defaultVersion && !target.is_default
    && target.flink_version !== defaultVersion
  const labels = Object.entries(target.labels || {})
  return (
    <div className="card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="mono text-[13px] font-medium text-slate-900">{target.name}</span>
            {target.is_default && <Badge tone="accent">default</Badge>}
            {!target.enabled && <Badge>disabled</Badge>}
            {mismatch && (
              <span title={`This cluster runs Flink ${target.flink_version}; the default runs ${defaultVersion}`}>
                <Badge tone="amber">differs from default</Badge>
              </span>
            )}
          </div>
          {target.description && (
            <p className="text-[12px] text-slate-500 mt-0.5">{target.description}</p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
        <span className="flex items-center gap-1.5 text-[12px]">
          <span className={`w-2 h-2 rounded-full ${target.reachable ? 'bg-emerald-500' : 'bg-red-500'}`} />
          <span className={target.reachable ? 'text-slate-600' : 'text-red-700'}>
            {target.reachable ? `Flink ${target.flink_version}` : 'unreachable'}
          </span>
        </span>
        {canManage && (
          <span className="flex items-center gap-2 text-[12px]">
            <button onClick={() => onEdit(target)}
                    className="link">Edit</button>
            {!target.is_default && (
              <button onClick={() => onRemove(target)}
                      className="text-slate-400 hover:text-red-600">Remove</button>
            )}
          </span>
        )}
        </div>
      </div>

      <dl className="grid grid-cols-2 sm:grid-cols-3 gap-3 mt-3 text-[12px]">
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
            <span key={k} className="text-[11px] bg-slate-100 text-slate-600 rounded-sm px-1.5 py-0.5">
              {k}={v}
            </span>
          ))}
        </div>
      )}
      <JobMovesLine moves={moves} canManage={canManage} onOpen={onJobMoves} />
    </div>
  )
}

export default function Cluster() {
  const confirm = useConfirm()
  const { user } = useAuth()
  // Targets decide where jobs run and what URL they are submitted to, so only an
  // administrator may change them. The API enforces this; hiding the controls
  // keeps the page honest about what this account can actually do.
  const canManage = user?.role === 'admin'

  const [targets, setTargets] = useState(null)
  const [connectors, setConnectors] = useState([])
  const [error, setError] = useState(null)
  const [editing, setEditing] = useState(null)   // target being edited
  const [adding, setAdding] = useState(false)
  const [setup, setSetup] = useState(null)       // how to start a new cluster
  const [defaults, setDefaults] = useState(null) // form values from the guide
  const [added, setAdded] = useState(null)       // name of the cluster just added
  const [storage, setStorage] = useState(null)   // savepoint locations and job moves
  const [guide, setGuide] = useState(null)       // { mode, cluster } of an open job-moves guide
  const [upgrading, setUpgrading] = useState(false) // the rolling upgrade guide is open

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

  // Only matters with a second cluster; reloaded when the set of clusters changes.
  const clusterKey = targets ? targets.map((t) => `${t.name}:${t.enabled}`).join(',') : ''
  const loadStorage = async () => {
    try { setStorage(await api.savepointStorage()) } catch (err) { setError(err.message) }
  }
  useEffect(() => {
    if (targets && targets.length > 1) loadStorage(); else setStorage(null)
  }, [clusterKey]) // eslint-disable-line react-hooks/exhaustive-deps

  const reload = async () => {
    try { setTargets(await api.targets()) } catch (err) { setError(err.message) }
  }

  const startAdding = async () => {
    setAdded(null); setDefaults(null); setAdding(true)
    try { setSetup(await api.clusterSetup()) } catch (err) { setError(err.message) }
  }

  const remove = async (target) => {
    if (!await confirm(`Remove cluster "${target.name}"? Jobs running on it keep running, `
                 + 'but MARS will lose track of them.')) return
    try {
      await api.deleteTarget(target.name)
      await reload()
    } catch (err) { setError(err.message) }
  }

  if (error && !targets) return <Alert level="danger" title="Could not load clusters">{error}</Alert>
  if (!targets) return <Spinner label="Reading clusters" />

  const up = targets.filter((t) => t.reachable)
  const slotsTotal = up.reduce((n, t) => n + (t.slots_total || 0), 0)
  const slotsFree = up.reduce((n, t) => n + (t.slots_available || 0), 0)

  return (
    <>
      <PageHeader
        title="Clusters"
        subtitle={
          targets.length === 1
            ? 'One Flink cluster runs your jobs. Add another to run jobs on separate hardware, or to upgrade without stopping everything at once.'
            : `${targets.length} clusters, ${up.length} reachable`
        }
        actions={
          canManage && !adding && !editing ? (
            <button className="btn-primary" onClick={startAdding}>Add cluster</button>
          ) : null
        }
      />

      {error && (
        <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>
      )}

      {added && (
        <div className="mb-4">
          <Alert level="success" onDismiss={() => setAdded(null)} title={`Cluster ${added} added`}>
            To run a job on it, open the job, choose <b>Edit</b>, and pick{' '}
            <b>{added}</b> under <b>Runs on</b>. For a job to keep its state when it
            moves, set up <b>Job moves</b> on its card first. Without it, a moved job has to
            start fresh.
          </Alert>
        </div>
      )}

      {canManage && (adding || editing) && (
        <TargetForm
          initial={editing}
          defaults={defaults}
          onSaved={async (name) => {
            if (adding) setAdded(name)
            setAdding(false); setEditing(null); setDefaults(null); await reload()
          }}
          onCancel={() => { setAdding(false); setEditing(null); setDefaults(null) }}
        >
          {adding && (setup
            ? <AddClusterGuide
                setup={setup}
                onUse={setDefaults}
                onSlots={async (n) => {
                  try { setSetup(await api.clusterSetup(n)) } catch (err) { setError(err.message) }
                }}
              />
            : <Spinner label="Reading this installation" />)}
        </TargetForm>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 mb-6">
        <Stat label="Clusters" value={`${up.length} / ${targets.length}`}
              tone={up.length < targets.length ? 'bad' : 'slate'} />
        <Stat label="Slots free" value={`${slotsFree} / ${slotsTotal}`}
              tone={slotsFree === 0 ? 'bad' : 'slate'} />
        <Stat label="Jobs placed" value={targets.reduce((n, t) => n + t.job_count, 0)} />
        <Stat label="Connectors" value={connectors.length} />
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-2 mb-3">
        <h2 className="eyebrow-accent">Clusters</h2>
        {canManage && !upgrading && storage?.moves.some((m) => m.state === 'ready') && (
          <button type="button" className="link text-[13px]" onClick={() => setUpgrading(true)}>
            Upgrade one cluster at a time…
          </button>
        )}
      </div>
      {upgrading && storage && (
        <RollingUpgrade targets={targets} moves={storage.moves} onClose={() => setUpgrading(false)} />
      )}
      <div className="grid gap-3 lg:grid-cols-2 mb-8">
        {targets.map((t) => (
          <TargetCard
            key={t.name}
            target={t}
            defaultVersion={targets.find((x) => x.is_default)?.flink_version}
            canManage={canManage}
            onEdit={(x) => { setAdding(false); setAdded(null); setEditing(x) }}
            onRemove={remove}
            moves={storage?.moves.find((m) => m.cluster === t.name)}
            onJobMoves={(mode) => setGuide({ mode, cluster: t.name })}
          />
        ))}
      </div>

      {guide && storage?.moves.some((m) => m.cluster === guide.cluster) && (
        <JobMovesGuide
          key={`${guide.mode}:${guide.cluster}`}
          mode={guide.mode}
          moves={storage.moves.find((m) => m.cluster === guide.cluster)}
          locations={storage.clusters}
          targets={targets}
          onClose={() => setGuide(null)}
          onChanged={loadStorage}
        />
      )}

      <div className="table-scroll">
        <div className="px-4 py-3 border-b border-slate-200">
          <h2 className="font-medium text-slate-900 text-[14px]">Installed connectors</h2>
          <p className="text-[11px] text-slate-500 mt-0.5">
            Available source and sink connectors.
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
