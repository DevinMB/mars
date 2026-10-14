import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { bytes } from '../lib/format'
import { BatchProgress } from './BulkJobs'
import { Alert, Spinner } from './ui'

const GB = 1024 ** 3

// "a few seconds", "about 4 minutes", "about 1 hour 10 minutes".
function roughly(seconds) {
  if (seconds < 20) return 'a few seconds'
  if (seconds < 90) return `about ${Math.round(seconds / 10) * 10} seconds`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `about ${minutes} minutes`
  const h = Math.floor(minutes / 60), m = minutes % 60
  return `about ${h} hour${h === 1 ? '' : 's'}${m ? ` ${m} minutes` : ''}`
}

/**
 * Moves a job to another cluster with its state: a savepoint here, a resume
 * there, undone if the resume fails. The console runs it, as a bulk action of
 * one, so a long move carries on if this page is closed. MARS checks each
 * cluster first and says how long the job will be stopped, from its state size.
 */
export default function MoveJob({ job, running, onClose, onMoved }) {
  const [options, setOptions] = useState(null)
  const [chosen, setChosen] = useState('')
  const [native, setNative] = useState(false)
  const [batch, setBatch] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const here = job.target_name || 'the default cluster'

  useEffect(() => {
    api.moveOptions(job.name).then((o) => {
      setOptions(o)
      const ready = o.filter((x) => x.ok)
      if (ready.length === 1) setChosen(ready[0].cluster)
    }).catch((err) => setError(err.message))
  }, [job.name])

  // Follow the move the console is making.
  const open = ['running', 'stopping'].includes(batch?.status)
  useEffect(() => {
    if (!open) return
    const t = setInterval(async () => {
      try {
        const b = await api.batch(batch.id)
        setBatch(b)
        if (!['running', 'stopping'].includes(b.status)) onMoved(b)
      } catch { /* next tick */ }
    }, 2000)
    return () => clearInterval(t)
  }, [open, batch?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const move = async () => {
    setBusy(true); setError(null)
    try { setBatch(await api.startBatch('move', [job.name], chosen, native)) }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  if (batch) {
    return <BatchProgress batch={batch} canWrite onStop={() => api.stopBatch(batch.id)}
                          onDismiss={onClose} />
  }

  const size = options?.[0]?.state_bytes
  const pause = options?.[0]?.pause_seconds
  const measured = options?.[0]?.rate_measured
  const large = size != null && size >= GB

  return (
    <div className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">Move to another cluster</h2>
          <p className="text-[13px] text-slate-600 mt-1 max-w-2xl">
            {running
              ? `It stops on ${here} with its state saved, then carries on from the same place on the cluster you pick. If it cannot start there, it goes back to ${here}. The console does this, so you can close this page.`
              : `It is not running, so it only changes cluster; it continues from its saved state the next time it starts.`}
          </p>
          {running && size != null && (
            <p className={`text-[13px] mt-2 ${large ? 'text-amber-800' : 'text-slate-600'}`}>
              {bytes(size)} of state: expect it to be stopped for {roughly(pause)}
              {large && (measured
                ? ', from how fast savepoints have been here.'
                : '. A guess at 50 MB/s; the first large savepoint here measures the real speed.')}
            </p>
          )}
        </div>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" onClick={onClose}>Close</button>
      </div>

      {!options && !error && <div className="mt-3"><Spinner label="Checking the clusters" /></div>}
      {options && options.length === 0 && (
        <p className="text-[13px] text-slate-500 mt-3">There is no other cluster. <Link className="link" to="/cluster">Add one</Link> first.</p>
      )}
      {options && options.length > 0 && (
        <fieldset className="mt-4 space-y-1.5" disabled={busy}>
          <legend className="sr-only">Destination cluster</legend>
          {options.map((o) => (
            <label key={o.cluster} className={`flex items-start gap-2 rounded-md border px-3 py-2 ${
              !o.ok ? 'border-slate-200 opacity-75' : chosen === o.cluster ? 'border-accent-400 bg-accent-50 cursor-pointer' : 'border-slate-200 hover:border-slate-300 cursor-pointer'}`}>
              <input type="radio" name="dest" className="mt-1" disabled={!o.ok}
                     checked={chosen === o.cluster} onChange={() => setChosen(o.cluster)} />
              <span className="min-w-0">
                <span className="block mono text-[13px] text-slate-900">{o.cluster}</span>
                <span className="block text-[12px] text-slate-500">
                  {o.ok ? 'Ready' : o.reasons.join(' ')}
                  {!o.ok && o.reasons.some((r) => r.includes('Job moves are not set up')) && (
                    <> <Link className="link" to="/cluster">Clusters</Link></>
                  )}
                </span>
              </span>
            </label>
          ))}
        </fieldset>
      )}

      {running && large && (
        <label className="mt-3 flex items-start gap-2 text-[13px] text-slate-700">
          <input type="checkbox" className="mt-1" checked={native} onChange={(e) => setNative(e.target.checked)} />
          <span>
            Use the native savepoint format
            <span className="block text-[12px] text-slate-500">
              Copies the state backend's files instead of re-serializing every key: much faster
              for large RocksDB state. It can only be restored with the same state backend.
            </span>
          </span>
        </label>
      )}

      {error && <div className="mt-3"><Alert level="danger">{error}</Alert></div>}
      {options && options.some((o) => o.ok) && (
        <div className="mt-4">
          <button type="button" className="btn-primary" disabled={!chosen || busy} onClick={move}>
            {busy ? 'Starting…' : chosen ? `Move to ${chosen}` : 'Move'}
          </button>
        </div>
      )}
    </div>
  )
}
