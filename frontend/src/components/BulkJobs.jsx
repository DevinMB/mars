import { useState } from 'react'
import { api } from '../lib/api'
import { Alert } from './ui'

const ACTIVE = ['running', 'restarting', 'submitting']
const isActive = (job) => ACTIVE.includes(job.latest_run?.state)
const clusterOf = (job, defaultName) => job.target_name || defaultName

const STATUS = {
  waiting: { dot: 'bg-slate-300', text: 'Waiting' },
  working: { dot: 'bg-accent-500 animate-pulse', text: 'Working…' },
  done: { dot: 'bg-emerald-500', text: 'Done' },
  skipped: { dot: 'bg-slate-300', text: 'Skipped' },
  failed: { dot: 'bg-red-500', text: 'Failed' },
  notrun: { dot: 'bg-slate-200', text: 'Not started' },
}

/**
 * Acts on several jobs at once, one at a time, showing each one's progress.
 *
 * One at a time on purpose: each move or resume briefly needs a free slot and
 * the console's attention, and a clear per-job result is worth more than speed
 * when moving a whole pipeline. A move stops at the first failure (that job is
 * already back where it was): the cause is usually shared, such as the
 * destination running out of slots, and repeating it for every job helps no one.
 * Stops and resumes are independent of each other, so they carry on.
 */
export default function BulkJobs({ mode, jobs, targets, defaultName, onClose, onChanged }) {
  const [dest, setDest] = useState('')
  const [progress, setProgress] = useState(null) // name -> { status, note }
  const [running, setRunning] = useState(false)
  const done = progress && !running

  const plan = jobs.map((job) => {
    if (mode === 'move') {
      if (!dest) return { job, act: false, note: '' }
      if (clusterOf(job, defaultName) === dest) return { job, act: false, note: `Already on ${dest}` }
      return { job, act: true, note: isActive(job) ? 'Moves with its state' : 'Not running: only changes cluster' }
    }
    if (mode === 'stop') return isActive(job) ? { job, act: true, note: '' } : { job, act: false, note: 'Not running' }
    return isActive(job) ? { job, act: false, note: 'Already running' } : { job, act: true, note: '' }
  })
  const todo = plan.filter((p) => p.act)
  const destTarget = targets.find((t) => t.name === dest)
  const slotsNeeded = mode === 'move' ? todo.filter((p) => isActive(p.job)).length : 0
  const short = destTarget && destTarget.slots_available != null && slotsNeeded > destTarget.slots_available

  const start = async () => {
    setRunning(true)
    const state = Object.fromEntries(plan.map((p) => [p.job.name,
      p.act ? { status: 'waiting', note: '' } : { status: 'skipped', note: p.note }]))
    setProgress({ ...state })
    let halted = false
    for (const p of todo) {
      if (halted) { state[p.job.name] = { status: 'notrun', note: 'Stopped after the failure above' }; continue }
      state[p.job.name] = { status: 'working', note: '' }
      setProgress({ ...state })
      try {
        if (mode === 'move') {
          const r = await api.moveJob(p.job.name, dest)
          state[p.job.name] = { status: 'done', note: r.summary }
        } else if (mode === 'stop') {
          await api.stopJob(p.job.name)
          state[p.job.name] = { status: 'done', note: 'Stopped with its state saved' }
        } else {
          await api.runJob(p.job.name, 'latest')
          state[p.job.name] = { status: 'done', note: 'Started' }
        }
      } catch (err) {
        state[p.job.name] = { status: 'failed', note: err.message }
        if (mode === 'move') halted = true
      }
      setProgress({ ...state })
      onChanged()
    }
    setRunning(false)
  }

  const verb = { move: 'Move', stop: 'Stop and save state', resume: 'Resume' }[mode]
  const title = {
    move: `Move ${jobs.length} job${jobs.length === 1 ? '' : 's'} to another cluster`,
    stop: `Stop ${jobs.length} job${jobs.length === 1 ? '' : 's'} with their state saved`,
    resume: `Resume ${jobs.length} job${jobs.length === 1 ? '' : 's'}`,
  }[mode]
  const failed = progress && Object.values(progress).filter((s) => s.status === 'failed').length

  return (
    <div className="card p-5 mb-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">{title}</h2>
          <p className="text-[13px] text-slate-600 mt-1 max-w-2xl">
            {mode === 'move' && 'One job at a time: each stops with its state saved and carries on from the same place on the cluster you pick, usually within seconds. If one cannot start there, it goes back where it was and the rest are left alone.'}
            {mode === 'stop' && 'One job at a time, each saving its state first so it can resume where it left off. Kafka keeps what arrives meanwhile.'}
            {mode === 'resume' && 'One job at a time, each from its newest saved state.'}
          </p>
        </div>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" disabled={running}
                onClick={() => onClose(Boolean(progress))}>{done ? 'Done' : 'Close'}</button>
      </div>

      {mode === 'move' && !progress && (
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

      <ul className="mt-4 divide-y divide-slate-100 text-[13px]">
        {plan.map((p) => {
          const s = progress?.[p.job.name]
          const look = s ? STATUS[s.status] : p.act ? STATUS.waiting : STATUS.skipped
          return (
            <li key={p.job.name} className="flex items-start gap-3 py-1.5">
              <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${look.dot}`} />
              <span className="mono text-slate-900 min-w-40">{p.job.name}</span>
              <span className={`min-w-0 ${s?.status === 'failed' ? 'text-red-700' : 'text-slate-500'}`}>
                {s ? (s.note || look.text) : (p.note || (p.act ? '' : look.text))}
              </span>
            </li>
          )
        })}
      </ul>

      {short && !progress && (
        <div className="mt-3"><Alert level="warning">
          {dest} has {destTarget.slots_available} free slot{destTarget.slots_available === 1 ? '' : 's'} and
          {' '}{slotsNeeded} running job{slotsNeeded === 1 ? '' : 's'} would move. The ones that do not fit will
          {' '}fail and stay where they are. Add slots, or move fewer.
        </Alert></div>
      )}
      {done && failed > 0 && (
        <div className="mt-3"><Alert level="danger">
          {failed} job{failed === 1 ? '' : 's'} did not {mode === 'move' ? 'move' : mode === 'stop' ? 'stop' : 'start'}. The reason is beside each.
        </Alert></div>
      )}

      {!progress && (
        <div className="mt-4 flex items-center gap-3">
          <button type="button" className="btn-primary" disabled={!todo.length || (mode === 'move' && !dest)} onClick={start}>
            {mode === 'move' && dest ? `Move ${todo.length} to ${dest}` : `${verb} ${todo.length || ''}`.trim()}
          </button>
          {!todo.length && (mode !== 'move' || dest) && (
            <span className="text-[12px] text-slate-500">Nothing to do for the selected jobs.</span>
          )}
        </div>
      )}
    </div>
  )
}
