import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { relativeTime, duration } from '../lib/format'
import { Alert, EmptyState, PageHeader, Spinner, StatePill } from '../components/ui'

export default function Jobs() {
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await api.jobs()
        if (alive) { setJobs(data); setError(null) }
      } catch (err) {
        if (alive) setError(err.message)
      }
    }
    load()
    // Jobs change without the user doing anything, so the list refreshes itself.
    const t = setInterval(load, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (error) return <Alert level="danger" title="Could not load jobs">{error}</Alert>
  if (!jobs) return <Spinner label="Loading jobs" />

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle={jobs.length ? `${jobs.length} job${jobs.length === 1 ? '' : 's'}` : null}
        actions={<Link to="/jobs/new" className="btn-primary">New job</Link>}
      />

      {jobs.length === 0 ? (
        <EmptyState
          title="No jobs yet"
          action={<Link to="/jobs/new" className="btn-primary">Create your first job</Link>}
        >
          A job is a SQL statement that moves data from a source to a sink. Define those
          in the Catalog first, then write the statement that connects them.
        </EmptyState>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-4 py-2.5 font-semibold">Job</th>
                <th className="px-4 py-2.5 font-semibold">State</th>
                <th className="px-4 py-2.5 font-semibold">Type</th>
                <th className="px-4 py-2.5 font-semibold">Last run</th>
                <th className="px-4 py-2.5 font-semibold">For</th>
                <th className="px-4 py-2.5 font-semibold">Schedule</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((job) => {
                const run = job.latest_run
                return (
                  <tr key={job.id} className="hover:bg-slate-50/60">
                    <td className="px-4 py-3">
                      <Link to={`/jobs/${encodeURIComponent(job.name)}`}
                            className="font-medium text-slate-900 hover:text-brand-700">
                        {job.name}
                      </Link>
                      {job.description && (
                        <div className="text-xs text-slate-500 truncate max-w-md">{job.description}</div>
                      )}
                      {run?.state === 'restarting' && run.error_summary && (
                        <div className="text-xs text-amber-700 truncate max-w-md mt-0.5">
                          {run.error_summary}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <StatePill state={run?.state} />
                      {run?.restarts > 0 && (
                        <span className="ml-2 text-xs text-amber-700">
                          {run.restarts} restart{run.restarts === 1 ? '' : 's'}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{job.job_type}</td>
                    <td className="px-4 py-3 text-slate-600">{relativeTime(run?.started_at)}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {run ? duration(run.started_at, run.ended_at) : '—'}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {job.schedule
                        ? job.schedule.mode === 'cron'
                          ? <code className="mono text-xs">{job.schedule.cron_expr}</code>
                          : 'Keep running'
                        : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
