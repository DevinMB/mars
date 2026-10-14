import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import { relativeTime, duration, millis } from '../lib/format'
import { Alert, Badge, EmptyState, PageHeader, Spinner, StatePill } from '../components/ui'
import SearchInput from '../components/SearchInput'
import { BatchProgress, BulkPlan } from '../components/BulkJobs'
import BulkTags from '../components/BulkTags'
import TagChips from '../components/TagChips'

const COLUMNS = 6

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
          ? 'bg-surface text-slate-900 shadow-xs ring-1 ring-slate-200'
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
function ClusterHeading({ target, jobs, cols }) {
  const running = jobs.filter((j) => j.latest_run?.state === 'running').length
  const unhealthy = jobs.filter((j) =>
    ['failed', 'restarting'].includes(j.latest_run?.state)).length

  return (
    <tr className="bg-slate-50/80 border-y border-slate-200">
      <td colSpan={cols} className="px-4 py-2">
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

function JobRow({ job, showCluster, selectable, checked, onToggle, tag, onTag }) {
  const run = job.latest_run
  return (
    <tr className={checked ? 'bg-accent-50/60' : 'hover:bg-slate-50/60'}>
      {selectable && (
        <td className="w-8 pr-0!">
          <input type="checkbox" aria-label={`Select ${job.name}`} checked={checked} onChange={() => onToggle(job.name)} />
        </td>
      )}
      <td>
        <Link to={`/jobs/${encodeURIComponent(job.name)}`}
              className="block max-w-48 sm:max-w-md wrap-break-word font-medium text-slate-900 hover:text-brand-700">
          {job.name}
        </Link>
        {job.description && (
          <div className="text-xs text-slate-500 truncate max-w-48 sm:max-w-md">{job.description}</div>
        )}
        <TagChips tags={job.tags} active={tag} onPick={onTag} className="mt-1" />
        {run?.state === 'restarting' && run.error_summary && (
          <div className="text-xs text-amber-700 truncate max-w-48 sm:max-w-md mt-0.5">
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
      {showCluster && <td className="text-slate-600">
        {/* Redundant once the rows are already grouped under their cluster. */}
        {showCluster ? (
          job.target_name
            ? <span className="mono text-[12px] text-slate-700">{job.target_name}</span>
            : <span className="text-slate-400">default</span>
        ) : null}
      </td>}
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
  const { user } = useAuth()
  const canWrite = ['admin', 'editor'].includes(user?.role)
  const [state, setState] = useState('all')
  const [reload, setReload] = useState(0)
  const [jobs, setJobs] = useState(null)
  const [targets, setTargets] = useState([])
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [cluster, setCluster] = useState('all')
  // In the address, so a tag chip elsewhere can link to its jobs.
  const [params, setParams] = useSearchParams()
  const tag = params.get('tag') || ''
  const setTag = (t) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    if (t) next.set('tag', t); else next.delete('tag')
    return next
  }, { replace: true })
  // Jobs ticked for a bulk action, by name; and which action's panel is open.
  const [selected, setSelected] = useState(() => new Set())
  const [bulk, setBulk] = useState(null)
  // The bulk action the console is running, or ran last.
  const [batch, setBatch] = useState(null)
  const [dismissed, setDismissed] = useState(() => {
    try { return Number(localStorage.getItem('mars.batch.dismissed')) || 0 } catch { return 0 }
  })
  const allBox = useRef(null)

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
    api.latestBatch().then((b) => alive && setBatch(b)).catch(() => {})
    // Jobs change without the user doing anything, so the list refreshes itself.
    const t = setInterval(load, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [reload])

  // While a bulk action runs, follow it closely, and the jobs it changes with it.
  const batchOpen = ['running', 'stopping'].includes(batch?.status)
  useEffect(() => {
    if (!batchOpen) return
    const t = setInterval(async () => {
      try {
        const b = await api.batch(batch.id)
        setBatch(b)
        setJobs(await api.jobs())
      } catch { /* the next tick tries again */ }
    }, 2000)
    return () => clearInterval(t)
  }, [batchOpen, batch?.id])

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
      if (state !== 'all' && (j.latest_run?.state || 'never') !== state) return false
      if (multi && cluster !== 'all' && clusterOf(j, defaultName) !== cluster) return false
      if (tag && !(j.tags || []).includes(tag)) return false
      if (!q) return true
      return (
        j.name.toLowerCase().includes(q) ||
        (j.description || '').toLowerCase().includes(q) ||
        (j.latest_run?.state || '').toLowerCase().includes(q) ||
        j.job_type.toLowerCase().includes(q) ||
        (j.tags || []).some((t) => t.includes(q)) ||
        // So typing a cluster name narrows to it, the same as a state does.
        clusterOf(j, defaultName).toLowerCase().includes(q)
      )
    })
  }, [jobs, query, cluster, multi, defaultName, state, tag])

  const counts = useMemo(() => {
    const out = {}
    for (const j of jobs || []) {
      const name = clusterOf(j, defaultName)
      out[name] = (out[name] || 0) + 1
    }
    return out
  }, [jobs, defaultName])

  const toggle = (name) => setSelected((prev) => {
    const next = new Set(prev)
    if (next.has(name)) next.delete(name); else next.add(name)
    return next
  })
  // Select all means all that is shown: search or filter first, then select.
  const shownSelected = shown.filter((j) => selected.has(j.name)).length
  const allShown = shown.length > 0 && shownSelected === shown.length
  useEffect(() => {
    if (allBox.current) allBox.current.indeterminate = shownSelected > 0 && !allShown
  })
  const toggleAll = () => setSelected((prev) => {
    const next = new Set(prev)
    for (const j of shown) { if (allShown) next.delete(j.name); else next.add(j.name) }
    return next
  })

  if (error && !jobs) return <Alert level="danger" title="Could not load jobs">{error}</Alert>
  if (!jobs) return <Spinner label="Loading jobs" />

  // Jobs deleted since they were ticked simply drop out.
  const chosen = jobs.filter((j) => selected.has(j.name))
  const hiddenSelected = chosen.length - shownSelected
  const selectable = canWrite
  const cols = COLUMNS + (selectable ? 1 : 0)
  const rowProps = (job) => ({ selectable, checked: selected.has(job.name), onToggle: toggle, tag, onTag: setTag })
  const allTags = [...new Set(jobs.flatMap((j) => j.tags || []))].sort()

  // Nothing matching is one answer, not an empty band under every cluster.
  const grouped = multi && cluster === 'all' && shown.length > 0
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
        actions={canWrite && <Link to="/jobs/new" className="btn-primary">New job</Link>}
      />
      {error && <div className="mb-4"><Alert level="warning" title="Updates paused">
        Showing the last loaded jobs. {error}
        <button className="link ml-2" onClick={() => setReload((n) => n + 1)}>Retry</button>
      </Alert></div>}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="w-full sm:w-72"><SearchInput value={query} onChange={setQuery} placeholder="Search jobs…" count={shown.length} /></div>
        <select className="input w-auto" aria-label="Filter by state" value={state} onChange={(e) => setState(e.target.value)}>
          <option value="all">All states</option>
          {['running', 'restarting', 'failed', 'finished', 'canceled', 'submitting', 'never'].map((s) =>
            <option key={s} value={s}>{({ never: 'Never run', canceled: 'Cancelled', submitting: 'Starting' })[s] || s[0].toUpperCase() + s.slice(1)}</option>)}
        </select>
        {(allTags.length > 0 || tag) && (
          <select className="input w-auto" aria-label="Filter by tag" value={tag} onChange={(e) => setTag(e.target.value)}>
            <option value="">All tags</option>
            {allTags.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <span className="text-xs text-slate-500 sm:ml-auto">{shown.length} of {jobs.length} jobs</span>
      </div>

      <p className="sm:hidden text-xs text-slate-500 mb-3">Scroll the table to see all columns.</p>
      {multi && (
        <ClusterTabs targets={targets} counts={counts} value={cluster}
                     onChange={setCluster} total={jobs.length} />
      )}

      {batch && (batchOpen || batch.id !== dismissed) && (
        <BatchProgress batch={batch} canWrite={canWrite}
          onStop={async () => { try { await api.stopBatch(batch.id); setBatch(await api.batch(batch.id)) } catch (err) { setError(err.message) } }}
          onDismiss={() => { setDismissed(batch.id); try { localStorage.setItem('mars.batch.dismissed', String(batch.id)) } catch { /* per-viewer only */ } }} />
      )}
      {selectable && chosen.length > 0 && !bulk && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-accent-200 bg-accent-50 px-3 py-2 text-[13px]">
          <span className="text-slate-900 font-medium">{chosen.length} selected</span>
          {hiddenSelected > 0 && (
            <>
              <span className="text-amber-800" role="status">· {hiddenSelected} hidden by filters</span>
              <button type="button" className="link text-[12px]"
                      onClick={() => setSelected(new Set(shown.filter((j) => selected.has(j.name)).map((j) => j.name)))}>
                Clear hidden selections
              </button>
            </>
          )}
          {batchOpen ? (
            <span className="text-slate-600 ml-1">Another bulk action is running; start the next when it finishes.</span>
          ) : (
            <span className="flex flex-wrap gap-2 ml-1">
              {multi && <button type="button" className="btn-secondary py-1!" onClick={() => setBulk('move')}>Move to cluster…</button>}
              <button type="button" className="btn-secondary py-1!" onClick={() => setBulk('stop')}>Stop and save state</button>
              <button type="button" className="btn-secondary py-1!" onClick={() => setBulk('resume')}>Resume</button>
              <button type="button" className="btn-secondary py-1!" onClick={() => setBulk('tags')}>Tag…</button>
            </span>
          )}
          <button type="button" className="ml-auto link text-[12px]" onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}
      {bulk === 'tags' && (
        <BulkTags jobs={chosen} onClose={() => setBulk(null)}
                  onDone={async () => { setJobs(await api.jobs()) }} />
      )}
      {bulk && bulk !== 'tags' && (
        <BulkPlan key={bulk} mode={bulk} jobs={chosen} targets={targets} defaultName={defaultName}
                  onClose={() => setBulk(null)}
                  onStarted={(b) => { setBatch(b); setBulk(null); setSelected(new Set()) }} />
      )}

      {jobs.length === 0 ? (
        <EmptyState
          title="No jobs yet"
          action={canWrite && <Link to="/jobs/new" className="btn-primary">Create your first job</Link>}
        >
          A job is a SQL statement that moves data from a source to a sink. Define those
          in the Catalog first, then write the statement that connects them.
        </EmptyState>
      ) : (
        <div className="table-scroll">
          <table className="tbl">
            <thead>
              <tr>
                {selectable && (
                  <th className="w-8 pr-0!">
                    <input ref={allBox} type="checkbox" aria-label="Select all shown jobs"
                           checked={allShown} onChange={toggleAll} disabled={!shown.length} />
                  </th>
                )}
                <th>Job</th><th>State</th>{!grouped && <th>Cluster</th>}<th>Type</th>
                <th>Last run</th><th>Duration</th><th>Schedule</th>
              </tr>
            </thead>

            {grouped ? (
              <>
                {groups.map(([target, rows]) => (
                  <tbody key={target.name}>
                    <ClusterHeading target={target} jobs={rows} cols={cols} />
                    {rows.length === 0 ? (
                      <tr>
                        <td colSpan={cols} className="px-4 py-4 text-sm text-slate-500">
                          No jobs on this cluster.
                        </td>
                      </tr>
                    ) : (
                      rows.map((job) => <JobRow key={job.id} job={job} showCluster={false} {...rowProps(job)} />)
                    )}
                  </tbody>
                ))}

                {orphans.length > 0 && (
                  <tbody>
                    <tr className="bg-amber-50/70 border-y border-amber-200">
                      <td colSpan={cols} className="px-4 py-2">
                        <span className="font-medium text-amber-900">Unknown cluster</span>
                        <span className="ml-2 text-xs text-amber-800">
                          These jobs name a cluster that no longer exists, or one you
                          cannot see. They will not run until their cluster is restored
                          or they are pointed at another.
                        </span>
                      </td>
                    </tr>
                    {orphans.map((job) => (
                      <JobRow key={job.id} job={job} showCluster={false} {...rowProps(job)} />
                    ))}
                  </tbody>
                )}
              </>
            ) : (
              <tbody>
                {shown.length === 0 ? (
                  <tr>
                    <td colSpan={cols + 1} className="px-4 py-8 text-sm text-slate-500 text-center">
                      No jobs match.
                    </td>
                  </tr>
                ) : (
                  shown.map((job) => (
                    <JobRow key={job.id} job={job} showCluster={!grouped} {...rowProps(job)} />
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
