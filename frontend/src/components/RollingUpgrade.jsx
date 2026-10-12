import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Copyable, Step } from './AddClusterGuide'
import { BatchProgress } from './BulkJobs'
import { Alert } from './ui'

// Which cluster a job is on; jobs that name none run on the default.
const clusterOf = (job, def) => job.target_name || def

function remember(key, value) {
  try { localStorage.setItem(key, value ? '1' : '') } catch { /* per-viewer only */ }
}
function recall(key) {
  try { return localStorage.getItem(key) === '1' } catch { return false }
}

function hostOf(target) {
  try { return new URL(target.flink_rest_url).hostname } catch { return '' }
}

/**
 * Upgrading Flink or connectors without stopping the whole pipeline: empty one
 * cluster, upgrade it, move every job onto it (each one checked healthy before
 * the next), then upgrade the other. MARS cannot replace a cluster's containers
 * itself, so those steps are instructions; it does the moving, and works out
 * which step you are on from where the jobs actually are.
 */
export default function RollingUpgrade({ targets, moves, onClose }) {
  const def = targets.find((t) => t.is_default)
  const ready = moves.filter((m) => m.state === 'ready').map((m) => targets.find((t) => t.name === m.cluster)).filter(Boolean)
  const [other, setOther] = useState(ready[0]?.name || '')
  const [jobs, setJobs] = useState(null)
  const [version, setVersion] = useState(null)
  const [batch, setBatch] = useState(null)
  const [native, setNative] = useState(false)
  const [error, setError] = useState(null)
  const [, bump] = useState(0)

  const load = useCallback(async () => {
    try {
      const [j, b] = await Promise.all([api.jobs(), api.latestBatch()])
      setJobs(j); setBatch(b)
    } catch (err) { setError(err.message) }
  }, [])
  useEffect(() => { load(); api.version().then(setVersion).catch(() => {}) }, [load])
  const open = ['running', 'stopping'].includes(batch?.status)
  useEffect(() => {
    if (!open) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [open, load])

  if (!def || !ready.length) return null
  const pair = [def, targets.find((t) => t.name === other) || ready[0]]
  const on = (t) => (jobs || []).filter((j) => clusterOf(j, def.name) === t.name)
  // Upgrade first whichever has fewer jobs: emptying it costs the fewest moves.
  const [first, second] = on(pair[0]).length <= on(pair[1]).length ? pair : [pair[1], pair[0]]
  const key = (t) => `mars.upgrade.${t.name}.${version?.latest?.revision || 'next'}`
  const upgraded = (t) => recall(key(t))
  const mark = (t, v) => { remember(key(t), v); bump((n) => n + 1) }

  const flink = version?.flink
  const repo = (flink?.image || '').replace(/@sha256:.*$/, '').replace(/:[^/]*$/, '')
  const newRef = version?.latest?.revision && repo ? `${repo}:sha-${version.latest.revision}` : null

  const moveAll = async (from, to) => {
    setError(null)
    try { setBatch(await api.startBatch('move', on(from).map((j) => j.name), to.name, native)) }
    catch (err) { setError(err.message) }
  }

  const howTo = (t) => {
    if (t.is_default) {
      const cmd = flink?.how_to_update?.command
      return cmd ? (
        <>
          <p className="text-[12px] text-slate-600">On the MARS machine, run your usual Flink update. With no jobs on {t.name}, nothing stops:</p>
          <Copyable>{cmd}</Copyable>
        </>
      ) : (
        <>
          <p className="text-[12px] text-slate-600">On the MARS machine, in its folder:</p>
          <Copyable>{`${newRef ? `docker pull ${newRef}\n# set MARS_FLINK_IMAGE in .env to the digest that prints:\n#   docker image inspect --format '{{index .RepoDigests 0}}' ${newRef}\n` : '# set MARS_FLINK_IMAGE in .env to the new image\n'}docker compose up -d --no-deps jobmanager taskmanager sql-gateway`}</Copyable>
        </>
      )
    }
    return (
      <>
        <p className="text-[12px] text-slate-600">
          On {hostOf(t) || 'its machine'}, in the folder with its docker-compose.yml: set <code className="mono">image:</code> on
          jobmanager, taskmanager and sql-gateway to the new image, then restart it.
        </p>
        <Copyable>{`${newRef ? `docker pull ${newRef}\n` : ''}docker compose up -d`}</Copyable>
      </>
    )
  }

  const firstEmpty = jobs && on(first).length === 0
  const secondEmpty = jobs && on(second).length === 0

  return (
    <div className="card p-5 mb-8">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-[15px] font-medium text-slate-900">Upgrade without stopping the pipeline</h3>
          <p className="text-[13px] text-slate-600 mt-1 max-w-3xl">
            One cluster at a time: empty one, upgrade it, move every job onto it, then upgrade the
            other. Each job pauses for its own move only, and the next moves only once it is
            checkpointing on the new cluster. Moves go one way, onto the newer Flink: a savepoint
            does not restore onto an older version.
          </p>
          {newRef && flink?.update_available && (
            <p className="text-[12px] text-slate-500 mt-1">New Flink image: <code className="mono">{newRef}</code></p>
          )}
        </div>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" onClick={onClose}>Close</button>
      </div>
      {ready.length > 1 && (
        <label className="mt-3 flex items-center gap-2 text-[13px] text-slate-700">
          With
          <select className="input w-auto" value={other} onChange={(e) => setOther(e.target.value)}>
            {ready.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
          </select>
        </label>
      )}
      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
      {batch && (open || batch.status === 'failed') && (
        <div className="mt-4"><BatchProgress batch={batch} canWrite onStop={() => api.stopBatch(batch.id).then(load)} onDismiss={() => setBatch(null)} /></div>
      )}

      <ol className="space-y-5 mt-4">
        <Step n={1} title={`Empty ${first.name}`}>
          {!jobs ? null : firstEmpty
            ? <p className="text-[12px] text-emerald-700">No jobs on {first.name}.</p>
            : (
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className="btn-secondary" disabled={open} onClick={() => moveAll(first, second)}>
                  Move its {on(first).length} job{on(first).length === 1 ? '' : 's'} to {second.name}
                </button>
                <span className="text-[12px] text-slate-500">Before {first.name} is upgraded, while both run the same version.</span>
              </div>
            )}
        </Step>
        <Step n={2} title={`Upgrade ${first.name}`}>
          {howTo(first)}
          <p className="text-[12px] text-slate-500">{first.name} reports Flink {first.flink_version || '?'}{first.reachable ? '' : ', and is not answering'}.</p>
          <label className="flex items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" disabled={!firstEmpty} checked={upgraded(first)} onChange={(e) => mark(first, e.target.checked)} />
            {first.name} runs the new image
          </label>
        </Step>
        <Step n={3} title={`Move the jobs to ${first.name}`}>
          {secondEmpty ? (
            <p className="text-[12px] text-emerald-700">All jobs are on {first.name}.</p>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3">
                <button type="button" className="btn-primary" disabled={open || !upgraded(first) || !first.reachable} onClick={() => moveAll(second, first)}>
                  Move {on(second).length} job{on(second).length === 1 ? '' : 's'} to {first.name}
                </button>
                {!upgraded(first) && <span className="text-[12px] text-slate-500">After step 2.</span>}
              </div>
              <label className="flex items-start gap-2 text-[12px] text-slate-600">
                <input type="checkbox" className="mt-0.5" checked={native} onChange={(e) => setNative(e.target.checked)} />
                Native savepoint format, for jobs with large RocksDB state
              </label>
              <p className="text-[12px] text-slate-500">One at a time; the next moves once the last is checkpointing on {first.name}. The batch stops at the first that is not, and leaves the rest where they are.</p>
            </>
          )}
        </Step>
        <Step n={4} title={`Upgrade ${second.name}`}>
          {howTo(second)}
          <label className="flex items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" disabled={!secondEmpty} checked={upgraded(second)} onChange={(e) => mark(second, e.target.checked)} />
            {second.name} runs the new image
          </label>
        </Step>
        <Step n={5} title="Done">
          <p className="text-[12px] text-slate-600">
            Both clusters run the new image. The jobs can stay on {first.name}, or move back to {second.name} with
            Move to cluster on the Jobs page, now that both run the same version.
          </p>
        </Step>
      </ol>
    </div>
  )
}
