import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { duration, relativeTime } from '../lib/format'
import { Alert, EmptyState, PageHeader, Spinner, StatePill } from '../components/ui'

// Every job's runs in one list, newest first.
//
// Runs were only reachable one job at a time, so "what happened overnight?" meant
// opening each job in turn — which is the question an operator actually asks, and
// the one the console was worst at answering.
export default function Activity() {
  const [runs, setRuns] = useState(null)
  const [error, setError] = useState(null)
  const [onlyProblems, setOnlyProblems] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () =>
      api.activity(200)
        .then((r) => { if (alive) { setRuns(r); setError(null) } })
        .catch((e) => { if (alive) setError(e.message) })
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (error && !runs) return <Alert level="danger" title="Could not load activity">{error}</Alert>
  if (!runs) return <Spinner label="Loading activity" />

  const shown = onlyProblems
    ? runs.filter((r) => ['failed', 'restarting'].includes(r.state) || r.restarts > 0)
    : runs
  const problems = runs.filter(
    (r) => ['failed', 'restarting'].includes(r.state) || r.restarts > 0,
  ).length

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
            Only what went wrong
            {problems > 0 && <span className="text-xs text-slate-400">({problems})</span>}
          </label>
        }
      />

      {runs.length === 0 ? (
        <EmptyState title="Nothing has run yet">
          Runs from every job appear here as they happen.
        </EmptyState>
      ) : shown.length === 0 ? (
        <EmptyState title="Nothing has gone wrong">
          No failures or restarts in the last {runs.length} runs.
        </EmptyState>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
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
