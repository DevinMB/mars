import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { duration, relativeTime } from '../lib/format'
import { Alert, EmptyState, PageHeader, Spinner, StatePill } from '../components/ui'

// A failure only counts as a problem while it is still the latest word on that
// job and nobody has said they dealt with it. Everything else is history, and a
// list that keeps showing history is one people stop reading.
const isProblem = (r) =>
  (['failed', 'restarting'].includes(r.state) || r.restarts > 0) &&
  !r.superseded && !r.acknowledged

// Every job's runs in one list, newest first.
//
// Runs were only reachable one job at a time, so "what happened overnight?" meant
// opening each job in turn — which is the question an operator actually asks, and
// the one the console was worst at answering.
export default function Activity() {
  const { user } = useAuth()
  const canWrite = ['admin', 'editor'].includes(user?.role)
  const [runs, setRuns] = useState(null)
  const [busy, setBusy] = useState(null)
  const [reload, setReload] = useState(0)
  const [error, setError] = useState(null)
  const [onlyProblems, setOnlyProblems] = useState(true)

  const acknowledge = async (run, undo) => {
    setBusy(run.run_id)
    try { await api.acknowledgeRun(run.run_id, undo); setReload((n) => n + 1) }
    catch (e) { setError(e.message) }
    finally { setBusy(null) }
  }

  useEffect(() => {
    let alive = true
    const load = () =>
      api.activity(200)
        .then((r) => {
          if (!alive) return
          setRuns(r)
          setError(null)
        })
        .catch((e) => { if (alive) setError(e.message) })
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [reload])

  if (error && !runs) return <Alert level="danger" title="Could not load activity">{error}</Alert>
  if (!runs) return <Spinner label="Loading activity" />

  const shown = onlyProblems ? runs.filter(isProblem) : runs
  const problems = runs.filter(isProblem).length

  return (
    <>
      <PageHeader
        title="Activity"
        subtitle={`${runs.length} run${runs.length === 1 ? '' : 's'}, newest first`}
        actions={
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={onlyProblems}
                   className="rounded border-slate-300 text-brand-600 focus:ring-brand-500/30"
                   onChange={(e) => setOnlyProblems(e.target.checked)} />
            Outstanding issues
            {problems > 0 && <span className="text-xs text-slate-400">({problems})</span>}
          </label>
        }
      />

      {error && <div className="mb-4"><Alert level="warning" title="Updates paused">Showing the last loaded activity. {error}</Alert></div>}
      {runs.length === 0 ? (
        <EmptyState title="Nothing has run yet">
          Runs from every job appear here as they happen.
        </EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState title="No outstanding issues">
          Nothing outstanding in the last {runs.length} runs. Failures that a later
          run has already replaced are not counted.
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="tbl">
            <thead><tr><th>State</th><th>Job</th><th>Started</th><th>Duration</th><th>Triggered by</th><th><span className="sr-only">Actions</span></th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((r) => (
                <tr key={r.run_id} className="hover:bg-slate-50/60">
                  <td className="px-4 py-3 w-px whitespace-nowrap">
                    <StatePill state={r.state} />
                  </td>
                  <td className="px-4 py-3">
                    <Link to={`/jobs/${encodeURIComponent(r.job)}`}
                          className="font-medium text-slate-900 hover:text-brand-700">
                      {r.job}
                    </Link>
                    {r.error_summary && (
                      <div className="text-xs text-red-700 truncate max-w-xl">
                        {r.error_summary}
                      </div>
                    )}
                    {r.restored_from && (
                      <div className="text-xs text-slate-500">
                        resumed from saved state
                      </div>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600 whitespace-nowrap">
                    {relativeTime(r.started_at)}
                  </td>
                  <td className="px-4 py-3 text-slate-600 whitespace-nowrap">
                    {duration(r.started_at, r.ended_at)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500 whitespace-nowrap">
                    {r.triggered_by_schedule ? 'scheduled' : r.submitted_by || '—'}
                    {r.restarts > 0 && (
                      <span className="text-amber-700 ml-2">
                        {r.restarts} restart{r.restarts === 1 ? '' : 's'}
                      </span>
                    )}
                    {r.superseded && ['failed', 'restarting'].includes(r.state) && (
                      <span className="ml-2 text-slate-400"
                            title="A later run of this job has replaced it.">
                        superseded
                      </span>
                    )}
                    {r.acknowledged && (
                      <span className="ml-2 text-slate-400"
                            title={`Marked as dealt with by ${r.acknowledged_by || 'someone'}`}>
                        dismissed
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right whitespace-nowrap w-px">
                    {canWrite && ['failed', 'restarting'].includes(r.state) && !r.superseded && (
                      r.acknowledged ? (
                        <button className="text-xs link" disabled={busy === r.run_id}
                                onClick={() => acknowledge(r, true)}>Undo</button>
                      ) : (
                        <button className="text-xs link" disabled={busy === r.run_id}
                                title="Hide this from the problems view. It stays in the history."
                                onClick={() => acknowledge(r, false)}>Dismiss</button>
                      )
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
