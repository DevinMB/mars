import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Spinner } from './ui'

/**
 * Moves a job to another cluster with its state: a savepoint here, a resume
 * there, undone if the resume fails. MARS checks each cluster first, so the list
 * says plainly which ones can take the job now and why the others cannot.
 */
export default function MoveJob({ job, running, onClose, onMoved }) {
  const [options, setOptions] = useState(null)
  const [chosen, setChosen] = useState('')
  const [moving, setMoving] = useState(false)
  const [error, setError] = useState(null)
  const here = job.target_name || 'the default cluster'

  useEffect(() => {
    api.moveOptions(job.name).then((o) => {
      setOptions(o)
      const ready = o.filter((x) => x.ok)
      if (ready.length === 1) setChosen(ready[0].cluster)
    }).catch((err) => setError(err.message))
  }, [job.name])

  const move = async () => {
    setMoving(true); setError(null)
    try { onMoved(await api.moveJob(job.name, chosen)) }
    catch (err) { setError(err.message) } finally { setMoving(false) }
  }

  return (
    <div className="card p-5 mb-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-medium text-slate-900">Move to another cluster</h2>
          <p className="text-[13px] text-slate-600 mt-1 max-w-2xl">
            {running
              ? `It stops on ${here} with its state saved, then carries on from the same place on the cluster you pick, usually within a minute. If it cannot start there, MARS resumes it on ${here}.`
              : `It is not running, so it only changes cluster; it continues from its saved state the next time it starts.`}
          </p>
        </div>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" disabled={moving} onClick={onClose}>Close</button>
      </div>

      {!options && !error && <div className="mt-3"><Spinner label="Checking the clusters" /></div>}
      {options && options.length === 0 && (
        <p className="text-[13px] text-slate-500 mt-3">There is no other cluster. <Link className="link" to="/cluster">Add one</Link> first.</p>
      )}
      {options && options.length > 0 && (
        <fieldset className="mt-4 space-y-1.5" disabled={moving}>
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

      {error && <div className="mt-3"><Alert level="danger">{error}</Alert></div>}
      {options && options.some((o) => o.ok) && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="button" className="btn-primary" disabled={!chosen || moving} onClick={move}>
            {moving ? 'Moving…' : chosen ? `Move to ${chosen}` : 'Move'}
          </button>
          {moving && running && (
            <span className="text-[12px] text-slate-500">Saving its state on {here}, then starting it on {chosen}.</span>
          )}
        </div>
      )}
    </div>
  )
}
