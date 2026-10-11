import { useState } from 'react'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { Alert } from './ui'

const ACTIVE = ['running', 'restarting', 'submitting']
const isActive = (job) => ACTIVE.includes(job.latest_run?.state)
const clusterOf = (job, defaultName) => job.target_name || defaultName

const ITEM = {
  waiting: { dot: 'bg-slate-300', text: 'Waiting' },
  working: { dot: 'bg-accent-500 animate-pulse', text: 'In progress…' },
  done: { dot: 'bg-emerald-500', text: 'Done' },
  skipped: { dot: 'bg-slate-300', text: 'Skipped' },
  failed: { dot: 'bg-red-500', text: 'Failed' },
  notrun: { dot: 'bg-slate-200', text: 'Not attempted' },
}
const NOUN = { move: 'Move', stop: 'Stop', resume: 'Resume' }

function Items({ rows }) {
  return (
    <ul className="mt-4 divide-y divide-slate-100 text-[13px]">
      {rows.map((r) => {
        const look = ITEM[r.status] || ITEM.waiting
        return (
          <li key={r.job} className="flex flex-wrap items-start gap-x-3 gap-y-0.5 py-1.5">
            <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${look.dot}`} />
            <span className="mono text-slate-900 min-w-40">{r.job}</span>
            <span className={`min-w-0 flex-1 ${r.status === 'failed' ? 'text-red-700' : 'text-slate-500'}`}>
              {r.note || look.text}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/**
 * Choosing what a bulk action will do, before it starts. Starting hands it to
 * the console, which carries on whether or not this page stays open.
 */
export function BulkPlan({ mode, jobs, targets, defaultName, onClose, onStarted }) {
  const [dest, setDest] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const plan = jobs.map((job) => {
    if (mode === 'move') {
      if (!dest) return { job: job.name, act: true, note: '' }
      if (clusterOf(job, defaultName) === dest) return { job: job.name, act: false, note: `Already on ${dest}` }
      return { job: job.name, act: true, note: isActive(job) ? 'Moves with its state' : 'Not running: only changes cluster' }
    }
    if (mode === 'stop') return isActive(job) ? { job: job.name, act: true, note: '' } : { job: job.name, act: false, note: 'Not running' }
    return isActive(job) ? { job: job.name, act: false, note: 'Already running' } : { job: job.name, act: true, note: '' }
  })
  const todo = plan.filter((p) => p.act)
  const destTarget = targets.find((t) => t.name === dest)
  const slotsNeeded = mode === 'move' && dest
    ? jobs.filter((j) => isActive(j) && clusterOf(j, defaultName) !== dest).length : 0
  const short = destTarget?.slots_available != null && slotsNeeded > destTarget.slots_available

  const start = async () => {
    setBusy(true); setError(null)
    try { onStarted(await api.startBatch(mode, todo.map((p) => p.job), mode === 'move' ? dest : null)) }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <div className="card p-5 mb-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">
            {{ move: 'Move', stop: 'Stop', resume: 'Resume' }[mode]} {jobs.length} job{jobs.length === 1 ? '' : 's'}
            {mode === 'move' ? ' to another cluster' : mode === 'stop' ? ' with their state saved' : ''}
          </h2>
          <p className="text-[13px] text-slate-600 mt-1 max-w-2xl">
            {mode === 'move' && 'One job at a time: each stops with its state saved and carries on from the same place on the cluster you pick. If one cannot start there, it goes back where it was and the rest are left alone.'}
            {mode === 'stop' && 'One job at a time, each saving its state first so it can resume where it left off. Kafka keeps what arrives meanwhile.'}
            {mode === 'resume' && 'One job at a time, each from its newest saved state.'}
            {' '}The console does this itself: you can close this page, and anyone can follow it here.
          </p>
        </div>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" onClick={onClose}>Cancel</button>
      </div>

      {mode === 'move' && (
        <fieldset className="mt-4 flex flex-wrap gap-2">
          <legend className="text-[12px] text-slate-500 mb-1.5">Move to</legend>
          {targets.filter((t) => t.enabled !== false).map((t) => (
            <label key={t.name} className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-[13px] cursor-pointer ${
              dest === t.name ? 'border-accent-400 bg-accent-50' : 'border-slate-200 hover:border-slate-300'}`}>
              <input type="radio" name="bulk-dest" checked={dest === t.name} onChange={() => setDest(t.name)} />
              <span className="mono">{t.name}</span>
              {t.slots_available != null && <span className="text-[11px] text-slate-500">{t.slots_available} slots free</span>}
            </label>
          ))}
        </fieldset>
      )}

      <Items rows={plan.map((p) => ({ job: p.job, status: p.act ? 'waiting' : 'skipped', note: p.note }))} />

      {short && (
        <div className="mt-3"><Alert level="warning">
          {dest} has {destTarget.slots_available} free slot{destTarget.slots_available === 1 ? '' : 's'} and
          {' '}{slotsNeeded} running job{slotsNeeded === 1 ? '' : 's'} would move. The move stops at the first
          {' '}one that does not fit, which stays where it is. Add slots, or move fewer.
        </Alert></div>
      )}
      {error && <div className="mt-3"><Alert level="danger">{error}</Alert></div>}

      <div className="mt-4 flex items-center gap-3">
        <button type="button" className="btn-primary" disabled={busy || !todo.length || (mode === 'move' && !dest)} onClick={start}>
          {busy ? 'Starting…' : mode === 'move' && dest ? `Move ${todo.length} to ${dest}` : `${NOUN[mode]} ${todo.length}`}
        </button>
        {!todo.length && (mode !== 'move' || dest) && (
          <span className="text-[12px] text-slate-500">Nothing to do for the selected jobs.</span>
        )}
      </div>
    </div>
  )
}

/** A bulk action the console is running, or ran last, as it reports it. */
export function BatchProgress({ batch, canWrite, onStop, onDismiss }) {
  const open = ['running', 'stopping'].includes(batch.status)
  const counts = batch.items.reduce((c, i) => ({ ...c, [i.status]: (c[i.status] || 0) + 1 }), {})
  const finished = (counts.done || 0) + (counts.skipped || 0) + (counts.failed || 0) + (counts.notrun || 0)
  const what = batch.kind === 'move' ? `Moving ${batch.items.length} job${batch.items.length === 1 ? '' : 's'} to ${batch.cluster}`
    : batch.kind === 'stop' ? `Stopping ${batch.items.length} job${batch.items.length === 1 ? '' : 's'}`
      : `Resuming ${batch.items.length} job${batch.items.length === 1 ? '' : 's'}`
  const outcome = {
    done: counts.failed ? `Finished, ${counts.failed} failed` : 'Finished',
    failed: 'Stopped at a failure',
    stopped: 'Stopped on request',
  }[batch.status]

  return (
    <div className="card p-5 mb-5" role="status" aria-live="polite">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">{what}</h2>
          <p className="text-[12px] text-slate-500 mt-0.5">
            Started by {batch.created_by || 'someone'} {relativeTime(batch.created_at)}
            {open ? ` · ${finished} of ${batch.items.length} done` : ` · ${outcome}`}
            {batch.status === 'stopping' && ' · stopping after the current job'}
          </p>
        </div>
        <span className="flex gap-3 text-[12px]">
          {open && canWrite && batch.status === 'running' && (
            <button type="button" className="text-slate-500 hover:text-red-700" onClick={onStop}>Stop after this job</button>
          )}
          {!open && <button type="button" className="text-slate-500 hover:text-slate-800" onClick={onDismiss}>Dismiss</button>}
        </span>
      </div>
      {open && (
        <p className="text-[12px] text-slate-500 mt-2">The console is doing this; it carries on if you close the page.</p>
      )}
      <Items rows={batch.items} />
      {!open && batch.status !== 'done' && (
        <div className="mt-3"><Alert level={batch.status === 'failed' ? 'danger' : 'warning'}>
          {batch.status === 'failed'
            ? 'The move stopped at the job that failed, which is back where it was. The jobs after it were not touched. The reason is beside it.'
            : 'Stopped as asked. The jobs after the one in progress were not touched.'}
        </Alert></div>
      )}
    </div>
  )
}
