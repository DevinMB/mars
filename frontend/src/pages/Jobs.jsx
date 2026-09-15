import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { relativeTime, duration, millis } from '../lib/format'
import { Alert, Badge, EmptyState, PageHeader, Spinner, StatePill } from '../components/ui'
import SearchInput from '../components/SearchInput'

const COLUMNS = 7

// A job with no target named runs on the default cluster. Resolving that here
// rather than showing a blank keeps every job attributable to exactly one
// cluster, which is what makes grouping meaningful.
function clusterOf(job, defaultName) {
  return job.target_name || defaultName || 'default'
}

/** Cluster selector. Only worth showing once there is more than one. */
function ClusterTabs({ targets, counts, value, onChange, total }) {
  const tab = (id, label, count, extra) => (
    <button
      key={id}
      onClick={() => onChange(id)}
      className={`px-3 py-1.5 text-sm font-medium rounded-md transition-colors ${
        value === id
          ? 'bg-white text-slate-900 shadow-sm ring-1 ring-slate-200'
          : 'text-slate-600 hover:text-slate-900'
      }`}
    >
      {label}
      <span className="ml-1.5 text-xs text-slate-400 tabular-nums">{count}</span>
      {extra}
    </button>
  )

  return (
    <div className="mb-4 flex items-center gap-1 p-1 bg-slate-100 rounded-lg w-fit">
      {tab('all', 'All clusters', total)}
      {targets.map((t) =>
        tab(
          t.name,
          t.name,
          counts[t.name] || 0,
          t.reachable === false && (
            <span className="ml-1.5 w-1.5 h-1.5 rounded-full bg-red-500 inline-block align-middle"
                  title="This cluster is not answering" />
          ),
        ),
      )}
    </div>
  )
}

/** The band above each cluster's jobs when the list is grouped. */
function ClusterHeading({ target, jobs }) {
  const running = jobs.filter((j) => j.latest_run?.state === 'running').length
  const unhealthy = jobs.filter((j) =>
    ['failed', 'restarting'].includes(j.latest_run?.state)).length

  return (
    <tr className="bg-slate-50/80 border-y border-slate-200">
      <td colSpan={COLUMNS} className="px-4 py-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium text-slate-900">{target.name}</span>
          {target.is_default && <Badge tone="slate">default</Badge>}
          {target.reachable === false && <Badge tone="amber">not answering</Badge>}
          {target.description && (
            <span className="text-xs text-slate-500">{target.description}</span>
          )}
          <span className="ml-auto flex items-center gap-3 text-xs text-slate-500 tabular-nums">
            <span>{jobs.length} job{jobs.length === 1 ? '' : 's'}</span>
            {running > 0 && <span className="text-emerald-700">{running} running</span>}
            {unhealthy > 0 && (
              <span className="text-red-700 font-medium">{unhealthy} need attention</span>
            )}
            {target.slots_total != null && (
              <span>
                {target.slots_total - (target.slots_available ?? 0)}/{target.slots_total} slots
              </span>
            )}
          </span>
        </div>
      </td>
    </tr>
  )
}

// Says when a job has stopped checkpointing, and says nothing otherwise.
//
// Deliberately absent when healthy. The running pill already carries a green dot,
// so a second one beside it was two green circles saying the same thing, and a
// row full of indicators that are always fine trains people to stop reading them.
//
// The thresholds are a heuristic and not a judgement: this list does not know each
// job's configured interval, and fetching it per row would double the requests
// behind a view that refreshes every ten seconds. The Diagnostics tab does know
// the interval and is the authority; this is a prompt to go and look.
function Staleness({ ms }) {
  if (ms === null || ms === undefined || ms < 120000) return null
  const bad = ms >= 600000
  return (
    <span className={`ml-2 text-xs ${bad ? 'text-red-700 font-medium' : 'text-amber-700'}`}
          title="A job that is running but no longer checkpointing is not making progress.">
      no checkpoint for {millis(ms)}
    </span>
  )
}

function JobRow({ job, showCluster }) {
  const run = job.latest_run
  return (
    <tr className="hover:bg-slate-50/60">
      <td>
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
      <td>
        <StatePill state={run?.state} />
        <Staleness ms={job.checkpoint_age_ms} />
        {run?.restarts > 0 && (
          <span className="ml-2 text-xs text-amber-700">
            {run.restarts} restart{run.restarts === 1 ? '' : 's'}
          </span>
        )}
      </td>
      <td className="text-slate-600">
        {/* Redundant once the rows are already grouped under their cluster. */}
        {showCluster ? (
          job.target_name
            ? <span className="mono text-[12px] text-slate-700">{job.target_name}</span>
            : <span className="text-slate-400">default</span>
        ) : null}
      </td>
      <td className="text-slate-600">{job.job_type}</td>
      <td className="text-slate-600">{relativeTime(run?.started_at)}</td>
      <td className="text-slate-600">{run ? duration(run.started_at, run.ended_at) : '—'}</td>
      <td className="text-slate-600">
        {job.schedule
          ? job.schedule.mode === 'cron'
            ? <code className="mono text-xs">{job.schedule.cron_expr}</code>
            : 'Keep running'
          : '—'}
      </td>
    </tr>
  )
}

export default function Jobs() {
  const [jobs, setJobs] = useState(null)
  const [targets, setTargets] = useState([])
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [cluster, setCluster] = useState('all')

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await api.jobs()
        if (alive) { setJobs(data); setError(null) }
      } catch (err) {
        if (alive) setError(err.message)
      }
      try {
        const t = await api.targets()
        // A viewer may not be allowed to list clusters; the page still works,
        // it just cannot group by something it cannot see.
        if (alive) setTargets(Array.isArray(t) ? t : [])
      } catch { /* not fatal */ }
    }
    load()
    // Jobs change without the user doing anything, so the list refreshes itself.
    const t = setInterval(load, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const defaultName = useMemo(
    () => targets.find((t) => t.is_default)?.name || 'default',
    [targets],
  )

  // Below two clusters there is nothing to separate, and a selector over a single
  // option is furniture. It appears when it starts earning its place.
  const multi = targets.length > 1

  const shown = useMemo(() => {
    if (!jobs) return []
    const q = query.trim().toLowerCase()
    return jobs.filter((j) => {
      if (multi && cluster !== 'all' && clusterOf(j, defaultName) !== cluster) return false
      if (!q) return true
      return (
        j.name.toLowerCase().includes(q) ||
        (j.description || '').toLowerCase().includes(q) ||
        (j.latest_run?.state || '').toLowerCase().includes(q) ||
        j.job_type.toLowerCase().includes(q) ||
        // So typing a cluster name narrows to it, the same as a state does.
        clusterOf(j, defaultName).toLowerCase().includes(q)
      )
    })
  }, [jobs, query, cluster, multi, defaultName])

  const counts = useMemo(() => {
    const out = {}
    for (const j of jobs || []) {
      const name = clusterOf(j, defaultName)
      out[name] = (out[name] || 0) + 1
    }
    return out
  }, [jobs, defaultName])

  if (error) return <Alert level="danger" title="Could not load jobs">{error}</Alert>
  if (!jobs) return <Spinner label="Loading jobs" />

  const grouped = multi && cluster === 'all'
  // Clusters with no jobs are still worth a heading: an empty business unit is a
  // fact about the estate, not a reason to hide the cluster.
  const groups = grouped
    ? targets.map((t) => [t, shown.filter((j) => clusterOf(j, defaultName) === t.name)])
    : []

  // A job can name a cluster that no longer exists -- the target was deleted, or
  // the account cannot see it. Grouping only by known clusters drops those rows
  // from the page with no indication, which is a worse failure than the one this
  // grouping exists to fix: the job is still there, still holding slots, still
  // possibly broken. Collect the leftovers into their own group.
  const known = new Set(targets.map((t) => t.name))
  const orphans = grouped
    ? shown.filter((j) => !known.has(clusterOf(j, defaultName)))
    : []

  return (
    <>
      <PageHeader
        title="Jobs"
        subtitle={jobs.length ? `${jobs.length} job${jobs.length === 1 ? '' : 's'}${
          multi ? ` across ${targets.length} clusters` : ''}` : null}
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

      {multi && (
        <ClusterTabs targets={targets} counts={counts} value={cluster}
                     onChange={setCluster} total={jobs.length} />
      )}

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
                <th>Job</th><th>State</th><th>{grouped ? '' : 'Runs on'}</th><th>Type</th>
                <th>Last run</th><th>For</th><th>Schedule</th>
              </tr>
            </thead>

            {grouped ? (
              <>
                {groups.map(([target, rows]) => (
                  <tbody key={target.name}>
                    <ClusterHeading target={target} jobs={rows} />
                    {rows.length === 0 ? (
                      <tr>
                        <td colSpan={COLUMNS} className="px-4 py-4 text-sm text-slate-500">
                          No jobs on this cluster.
                        </td>
                      </tr>
                    ) : (
                      rows.map((job) => <JobRow key={job.id} job={job} showCluster={false} />)
                    )}
                  </tbody>
                ))}

                {orphans.length > 0 && (
                  <tbody>
                    <tr className="bg-amber-50/70 border-y border-amber-200">
                      <td colSpan={COLUMNS} className="px-4 py-2">
                        <span className="font-medium text-amber-900">Unknown cluster</span>
                        <span className="ml-2 text-xs text-amber-800">
                          These jobs name a cluster that no longer exists, or one you
                          cannot see. They will not run until their cluster is restored
                          or they are pointed at another.
                        </span>
                      </td>
                    </tr>
                    {orphans.map((job) => (
                      <JobRow key={job.id} job={job} showCluster />
                    ))}
                  </tbody>
                )}
              </>
            ) : (
              <tbody>
                {shown.length === 0 ? (
                  <tr>
                    <td colSpan={COLUMNS} className="px-4 py-8 text-sm text-slate-500 text-center">
                      No jobs match.
                    </td>
                  </tr>
                ) : (
                  shown.map((job) => (
                    <JobRow key={job.id} job={job} showCluster={!multi || cluster === 'all'} />
                  ))
                )}
              </tbody>
            )}
          </table>
        </div>
      )}
    </>
  )
}
