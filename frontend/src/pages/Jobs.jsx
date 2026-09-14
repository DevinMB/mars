import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { relativeTime, duration } from '../lib/format'
import { Alert, EmptyState, PageHeader, Spinner, StatePill } from '../components/ui'
import SearchInput from '../components/SearchInput'

export default function Jobs() {
  const [jobs, setJobs] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')

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

  // Filter over name, description and current state, so "failed" or "restarting"
  // narrows to what needs attention as readily as a name does.
  const q = query.trim().toLowerCase()
  const shown = !q
    ? jobs
    : jobs.filter(
        (j) =>
          j.name.toLowerCase().includes(q) ||
          (j.description || '').toLowerCase().includes(q) ||
          (j.latest_run?.state || '').toLowerCase().includes(q) ||
          j.job_type.toLowerCase().includes(q),
      )

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle={jobs.length ? `${jobs.length} job${jobs.length === 1 ? '' : 's'}` : null}
        actions={
          <>
            {jobs.length > 6 && (
              <div className="w-56">
                <SearchInput value={query} onChange={setQuery}
                             placeholder="Filter jobs…" count={shown.length} />
              </div>
            )}
            <Link to="/jobs/new" className="btn-primary">New job</Link>
          </>
        }
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
          <table className="tbl">
            <thead>
              <tr>
                <th>Job</th><th>State</th><th>Runs on</th><th>Type</th>
                <th>Last run</th><th>For</th><th>Schedule</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((job) => {
                const run = job.latest_run
                return (
                  <tr key={job.id} className="hover:bg-slate-50/60">
                    <td className="">
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
                    <td className="">
                      <StatePill state={run?.state} />
                      {run?.restarts > 0 && (
                        <span className="ml-2 text-xs text-amber-700">
                          {run.restarts} restart{run.restarts === 1 ? '' : 's'}
                        </span>
                      )}
                    </td>
                    <td className="text-slate-600">
                      {job.target_name ? (
                        <span className="mono text-[12px] text-slate-700">{job.target_name}</span>
                      ) : (
                        <span className="text-slate-400">default</span>
                      )}
                    </td>
                    <td className="text-slate-600">{job.job_type}</td>
                    <td className=" text-slate-600">{relativeTime(run?.started_at)}</td>
                    <td className=" text-slate-600">
                      {run ? duration(run.started_at, run.ended_at) : '—'}
                    </td>
                    <td className=" text-slate-600">
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
