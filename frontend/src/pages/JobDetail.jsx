import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import ActionMenu from '../components/ActionMenu'
import { useConfirm, useNotify } from '../components/InteractionProvider'
import { api } from '../lib/api'
import { cronText, duration, millis, relativeTime } from '../lib/format'
import SqlEditor from '../components/SqlEditor'
import Diagnostics from '../components/Diagnostics'
import MoveJob from '../components/MoveJob'
import MarsMark from '../components/MarsMark'
import { Alert, Badge, CodeBlock, Field, PageHeader, Spinner, StatePill } from '../components/ui'

const ACTIVE = ['running', 'submitting', 'restarting']

// The last path segment names a savepoint or checkpoint well enough to tell
// them apart; the full path is in the tooltip.
const pointName = (path) => path?.replace(/\/+$/, '').split('/').pop() || path
const isCheckpoint = (path) => /\/chk-\d+\/?$/.test(path || '')

// The facts an operator checks first, in one row under the title, instead of
// spread between the header, the sidebar and the runs table.
function Vitals({ job, run, isActive }) {
  const age = job.checkpoint_age_ms
  const stale = age != null && age >= 120000
  const point = job.restore_point
  const cell = (label, value, extra = '') => (
    <div className={`bg-surface px-4 py-2.5 min-w-0 ${extra}`}>
      <dt className="text-[12px] text-slate-500">{label}</dt>
      <dd className="text-[13px] text-slate-900 flex items-center gap-1.5 min-w-0">{value}</dd>
    </div>
  )
  return (
    // Hairline separators come from the gap showing the border colour through,
    // so they stay right however many columns the width allows.
    <dl className="card overflow-hidden mb-6 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-px bg-slate-200">
      {cell('State', <>
        <StatePill state={run?.state} />
        {isActive && run?.started_at && <span className="text-slate-500 tabular-nums">for {duration(run.started_at)}</span>}
      </>)}
      {cell('Last checkpoint', job.job_type !== 'streaming' || !isActive
        ? <span className="text-slate-400">n/a</span>
        : age == null
          ? <span className="text-slate-400">none yet</span>
          : <span className={`tabular-nums ${stale ? (age >= 600000 ? 'text-red-700 font-medium' : 'text-amber-700') : ''}`}
                  title={stale ? 'A job that is running but no longer checkpointing is not making progress.' : undefined}>
              {millis(age)} ago
            </span>)}
      {cell('Saved state', point
        ? <span className="flex items-center gap-1.5 min-w-0" title={point.path}>
            {point.kind === 'savepoint' && <MarsMark size={14} />}
            <span className="truncate">{point.kind}, {relativeTime(point.taken_at)}</span>
          </span>
        : <span className="text-slate-400">none</span>)}
      {cell('Cluster', <span className="truncate">{job.target_name || 'default'}</span>)}
      {cell('Version', <span>v{job.version} <span className="text-slate-400">· {job.job_type}</span></span>)}
    </dl>
  )
}

// Runs as a timeline. Every run that saved its state wears the acorn -- the
// mark is "something stored, kept, and found again", which is what a savepoint
// is -- and a run that resumed from one links back to the run that saved it.
function RunTimeline({ runs }) {
  const savedBy = new Map(runs.filter((r) => r.savepoint_path).map((r) => [r.savepoint_path, r.id]))
  return (
    <ol className="px-4 py-2">
      {runs.map((r, i) => {
        const saved = Boolean(r.savepoint_path)
        const from = r.restored_from
        const fromRun = from && savedBy.get(from)
        return (
          <li key={r.id} id={`run-${r.id}`} className="relative grid grid-cols-[20px_minmax(0,1fr)_auto] gap-3 py-2.5 scroll-mt-20">
            {i < runs.length - 1 && <span aria-hidden="true" className="absolute left-[9.5px] top-8 -bottom-2.5 w-px bg-slate-200" />}
            <span className="h-5 grid place-items-center" aria-hidden="true">
              {saved
                ? <span className={r.savepoint_removed_at ? 'opacity-40 grayscale' : ''}><MarsMark size={16} /></span>
                // A plain node: the state's own dot is in the pill beside it.
                : <span className="w-2 h-2 rounded-full border border-slate-400 bg-surface" />}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-slate-900">
                <StatePill state={r.state} />
                {saved && (
                  <span className="text-slate-600">
                    state saved as <span className="mono text-[12px] text-slate-800" title={r.savepoint_path}>{pointName(r.savepoint_path)}</span>
                    {r.savepoint_removed_at && <span className="text-slate-400"> (removed by retention)</span>}
                  </span>
                )}
              </div>
              <div className="text-xs text-slate-500 mt-0.5 flex flex-wrap gap-x-1.5">
                <span>Run {r.id}</span>
                <span>· {duration(r.started_at, r.ended_at)}</span>
                <span>· {r.triggered_by_schedule ? 'scheduled' : r.submitted_by || 'unknown'}</span>
                {r.restarts > 0 && <span className="text-amber-700">· {r.restarts} restart{r.restarts === 1 ? '' : 's'}</span>}
                {from && (
                  <span title={from}>
                    · resumed from{' '}
                    {isCheckpoint(from)
                      ? <>checkpoint <span className="mono text-[11.5px]">{pointName(from)}</span></>
                      : fromRun
                        ? <a href={`#run-${fromRun}`} className="link inline-flex items-center gap-1 align-bottom"><MarsMark size={12} /><span className="mono text-[11.5px]">{pointName(from)}</span></a>
                        : <span className="inline-flex items-center gap-1 align-bottom"><MarsMark size={12} /><span className="mono text-[11.5px]">{pointName(from)}</span></span>}
                  </span>
                )}
              </div>
              {r.error_summary && (
                <div className="text-xs text-red-700 mt-1 truncate" title={r.error_summary}>{r.error_summary}</div>
              )}
            </div>
            <time className="text-xs text-slate-500 whitespace-nowrap tabular-nums" dateTime={r.started_at}
                  title={new Date(r.started_at).toLocaleString()}>
              {relativeTime(r.started_at)}
            </time>
          </li>
        )
      })}
    </ol>
  )
}

function Warnings({ warnings }) {
  if (!warnings?.length) return null
  return (
    <div className="space-y-2">
      {warnings.map((w, i) => (
        <Alert key={i} level={w.level === 'danger' ? 'danger' : 'warning'}
               title={w.level === 'danger' ? 'Likely to cause a problem' : 'Worth checking'}>
          {w.message}
        </Alert>
      ))}
    </div>
  )
}

function ScheduleCard({ job, onChange }) {
  const notify = useNotify()
  const [busy, setBusy] = useState(false)
  const [mode, setMode] = useState(job.schedule?.mode || (job.job_type === 'batch' ? 'cron' : 'supervisor'))
  const [cron, setCron] = useState(job.schedule?.cron_expr || '0 * * * *')
  const [error, setError] = useState(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.setSchedule(job.name, { mode, cron_expr: mode === 'cron' ? cron : null, enabled: true })
      onChange(); notify('Schedule saved.')
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const clear = async () => {
    setBusy(true)
    try { await api.clearSchedule(job.name); onChange(); notify('Schedule removed.') }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <div className="border-b border-slate-200 pb-5">
      <h3 className="text-sm font-medium text-slate-900 mb-3">Schedule</h3>
      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="space-y-3">
        <select aria-label="Schedule mode" className="input" value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="supervisor">Keep it running</option>
          <option value="cron" disabled={job.job_type === 'streaming'}>
            Run on a schedule{job.job_type === 'streaming' ? ' (batch jobs only)' : ''}
          </option>
        </select>

        {mode === 'cron' ? (
          <Field label="Cron expression" hint="Minute, hour, day of month, month, day of week.">
            <input className="input mono" value={cron} onChange={(e) => setCron(e.target.value)} />
          </Field>
        ) : (
          <p className="text-xs text-slate-500">
            If the job stops or fails, MARS starts it again. It will not start a job that
            has never been run by hand.
          </p>
        )}

        <div className="flex gap-2">
          <button className="btn-secondary text-sm" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save schedule'}</button>
          {job.schedule && <button className="btn-secondary text-sm" disabled={busy} onClick={clear}>Remove</button>}
        </div>

        {job.schedule?.next_fire_at && (
          <p className="text-xs text-slate-500">Next run {relativeTime(job.schedule.next_fire_at)}</p>
        )}
      </div>
    </div>
  )
}

export default function JobDetail() {
  const confirm = useConfirm()
  const notify = useNotify()
  const { user } = useAuth()
  const canWrite = ['admin', 'editor'].includes(user?.role)
  const { name } = useParams()
  const navigate = useNavigate()

  const [job, setJob] = useState(null)
  const [runs, setRuns] = useState([])
  const [versions, setVersions] = useState([])
  const [script, setScript] = useState(null)
  const [validation, setValidation] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(null)
  const [tab, setTab] = useState('sql')
  const [diag, setDiag] = useState(null)
  const [diagBusy, setDiagBusy] = useState(false)
  const [moving, setMoving] = useState(false)       // the move panel is open
  const [clusterCount, setClusterCount] = useState(1)

  const load = useCallback(async () => {
    try {
      const [j, r, v] = await Promise.all([
        api.job(name), api.jobRuns(name), api.jobVersions(name),
      ])
      setJob(j); setRuns(r); setVersions(v); setError(null)
    } catch (err) { setError(err.message) }
  }, [name])

  useEffect(() => { load() }, [load])
  // Moving needs somewhere to move to; with one cluster the option is noise.
  useEffect(() => {
    if (canWrite) api.targets().then((t) => setClusterCount(t.length)).catch(() => {})
  }, [canWrite])

  const loadDiagnostics = useCallback(async () => {
    setDiagBusy(true)
    try { setDiag(await api.jobDiagnostics(name)) }
    catch (err) { setError(err.message) }
    finally { setDiagBusy(false) }
  }, [name])

  // Keep the numbers live while the tab is open: backpressure and lag are only
  // meaningful as something you watch move.
  useEffect(() => {
    if (tab !== 'diagnostics') return
    loadDiagnostics()
    const t = setInterval(loadDiagnostics, 10000)
    return () => clearInterval(t)
  }, [tab, loadDiagnostics])

  // Poll while something is in flight so the page reflects reality without a refresh.
  useEffect(() => {
    const active = job?.latest_run && ACTIVE.includes(job.latest_run.state)
    if (!active) return
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [job, load])

  const act = async (label, fn) => {
    setBusy(label); setError(null)
    try { await fn(); await load() }
    catch (err) { setError(err.message) }
    finally { setBusy(null) }
  }

  const validate = () => act('validate', async () => setValidation(await api.validateJob(name)))
  const showScript = () => act('script', async () => {
    setScript((await api.jobScript(name)).statements)
    setTab('script')
  })

  if (error && !job) return <Alert level="danger" title="Could not load this job">{error}</Alert>
  if (!job) return <Spinner />

  const run = job.latest_run
  const isActive = run && ACTIVE.includes(run.state)

  return (
    <>
      <PageHeader
        title={job.name}
        subtitle={job.tags?.length > 0 && (
          <span className="flex flex-wrap gap-1 mt-1">{job.tags.map((t) => (
            <Link key={t} to={`/jobs?tag=${encodeURIComponent(t)}`} className="text-[11px] leading-4 rounded-sm px-1.5 bg-slate-100 text-slate-600 hover:bg-slate-200">{t}</Link>
          ))}</span>
        )}
        back={{ to: '/jobs', label: 'Jobs' }}
        actions={canWrite && <>
          <Link to={`/jobs/${encodeURIComponent(job.name)}/edit`} className="btn-secondary">Edit</Link>
          {/* Orange is for the constructive action. A running job has none, so
              stopping it is an ordinary button; Run and Resume take the colour. */}
          {isActive ? <button className="btn-secondary" disabled={Boolean(busy)}
            title="Save a checkpoint of the job's state before stopping."
            onClick={() => act('stop', () => api.stopJob(name))}>
            {busy === 'stop' ? 'Saving state…' : 'Stop and save state'}
          </button> : <button className="btn-primary" disabled={Boolean(busy)}
            onClick={() => act('run', () => api.runJob(name, 'latest'))}>
            {busy === 'run' ? 'Starting…' : job.restore_point ? 'Resume' : 'Run'}
          </button>}
          <ActionMenu>
            <button onClick={validate} disabled={Boolean(busy)}>{busy === 'validate' ? 'Checking…' : 'Validate SQL'}</button>
            <Link to={`/jobs/new?from=${encodeURIComponent(job.name)}`}>Duplicate</Link>
            {clusterCount > 1 && <button disabled={Boolean(busy)} onClick={() => setMoving(true)}>Move to cluster…</button>}
            {isActive && <button className="text-red-700" disabled={Boolean(busy)} onClick={async () => {
              if (!await confirm({ title: 'Stop without saving?', message: `Stop “${job.name}” immediately? In-flight state, including unfinished windows and running counts, will be lost. Use “Stop and save state” to resume later.`, confirmLabel: 'Stop without saving' })) return
              act('cancel', () => api.cancelJob(name))
            }}>Stop without saving</button>}
            {!isActive && job.restore_point && <button disabled={Boolean(busy)} onClick={async () => {
              if (!await confirm({ title: 'Start with empty state?', message: 'The saved state will be ignored. The job will start from scratch.', confirmLabel: 'Start fresh' })) return
              act('run-fresh', () => api.runJob(name, 'none'))
            }}>Start fresh</button>}
            <button className="text-red-700" disabled={isActive || Boolean(busy)} title={isActive ? 'Stop the job before deleting it' : undefined}
              onClick={async () => {
                if (!await confirm({ title: `Delete ${job.name}?`, message: 'This job will be permanently deleted. This cannot be undone.', confirmLabel: 'Delete job' })) return
                setBusy('delete')
                try { await api.deleteJob(job.name); notify('Job deleted.'); navigate('/jobs') }
                catch (err) { setError(err.message); setBusy(null) }
              }}>Delete job</button>
          </ActionMenu>
        </>}
      />
      {job.description && <p className="text-sm text-slate-600 -mt-2 mb-4 max-w-3xl">{job.description}</p>}
      <Vitals job={job} run={run} isActive={isActive} />
      {moving && (
        <MoveJob job={job} running={Boolean(isActive)} onClose={() => setMoving(false)}
                 onMoved={async (b) => { setMoving(false); notify(b.items?.[0]?.note || 'Moved.'); await load() }} />
      )}

      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {run?.state === 'restarting' && (
        <div className="mb-4">
          <Alert level="warning" title={`Flink keeps restarting this job (${run.restarts} so far)`}>
            {run.error_summary
              ? run.error_summary
              : 'The job starts and then fails repeatedly. It is not processing anything.'}
            <button onClick={() => setTab('diagnostics')} className="link ml-2 font-medium">
              See why
            </button>
          </Alert>
        </div>
      )}

      {run?.state === 'failed' && run.error_summary && (
        <div className="mb-4">
          <Alert level="danger" title="Last run failed">
            {run.error_summary}
            <button onClick={() => setTab('diagnostics')} className="link ml-2 font-medium">
              See why
            </button>
          </Alert>
        </div>
      )}

      {validation && (
        <div className="mb-4 space-y-2">
          {validation.ok
            ? <Alert level="success" onDismiss={() => setValidation(null)}>This job compiles.</Alert>
            : <Alert level="danger" title="This job will not compile" onDismiss={() => setValidation(null)}>
                {validation.error}
              </Alert>}
          <Warnings warnings={validation.warnings} />
        </div>
      )}

      <div className="editor-grid">
        <div className="space-y-6 min-w-0">
          <div className="card overflow-hidden">
            <div className="flex flex-wrap border-b border-slate-200">
              {[['sql', 'Statement'], ['diagnostics', 'Diagnostics'],
                ['script', 'Execution SQL'], ['history', 'Versions']].map(([id, label]) => (
                <button
                  key={id}
                  onClick={() => (id === 'script' && !script ? showScript() : setTab(id))}
                  className={`px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                    tab === id
                      ? 'border-brand-600 text-brand-700'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="p-4">
              {tab === 'sql' && <SqlEditor value={job.sql_text} onChange={() => {}} readOnly rows={20} minRows={4} />}

              {tab === 'diagnostics' && (
                <Diagnostics data={diag} loading={diagBusy} onRefresh={loadDiagnostics} />
              )}

              {tab === 'script' && (
                <div className="space-y-3">
                  <p className="text-xs text-slate-500">
                    The table definitions this job depends on are replayed first. Secrets stay
                    as references here — they are substituted only on the way to Flink.
                  </p>
                  {script
                    ? script.map((s, i) => <CodeBlock key={i} className="text-xs">{s}</CodeBlock>)
                    : <Spinner label="Building" />}
                </div>
              )}

              {tab === 'history' && (
                <div className="divide-y divide-slate-100">
                  {versions.map((v) => (
                    <div key={v.version} className="py-3 flex items-start gap-3">
                      <Badge tone="blue">v{v.version}</Badge>
                      <div className="min-w-0 flex-1">
                        <div className="text-sm text-slate-800">{v.note || 'No note'}</div>
                        <div className="text-xs text-slate-500">
                          {relativeTime(v.created_at)}{v.created_by ? ` by ${v.created_by}` : ''}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-200">
              <h2 className="font-medium text-slate-900">Runs</h2>
            </div>
            {runs.length === 0 ? (
              <p className="px-4 py-8 text-sm text-slate-500 text-center">This job has never run.</p>
            ) : (
              <RunTimeline runs={runs} />
            )}
          </div>
        </div>

        <aside className="space-y-4">
          {(run?.flink_job_id || (job.job_type === 'streaming' && !job.restore_point)) && (
            <div className="border-b border-slate-200 pb-5">
              {run?.flink_job_id && (
                <dl className="flex justify-between gap-3 text-sm">
                  <dt className="text-slate-500">Flink job</dt>
                  <dd className="mono text-xs text-slate-600 truncate max-w-36" title={run.flink_job_id}>{run.flink_job_id}</dd>
                </dl>
              )}
              {job.job_type === 'streaming' && !job.restore_point && (
                <p className={`text-xs text-slate-500 ${run?.flink_job_id ? 'mt-3' : ''}`}>
                  No state has been saved. Stopping with "Stop and save state" writes
                  one, so the job can resume instead of starting over.
                </p>
              )}
            </div>
          )}

          <div className="border-b border-slate-200 pb-5">
            <h3 className="text-sm font-medium text-slate-900 mb-2">Tables used</h3>
            {job.catalog_refs.length === 0 ? (
              <p className="text-xs text-slate-500">None.</p>
            ) : (
              <ul className="space-y-1">
                {job.catalog_refs.map((r) => (
                  <li key={r}>
                    {canWrite ? <Link to={`/catalog/${encodeURIComponent(r)}/edit`} className="mono text-sm link break-all">{r}</Link> : <span className="mono break-all">{r}</span>}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {canWrite ? <ScheduleCard job={job} onChange={load} /> : <div className="text-sm">
            <h3 className="font-medium mb-2">Schedule</h3>
            <p className="text-slate-600" title={job.schedule?.cron_expr}>{job.schedule ? job.schedule.mode === 'cron' ? cronText(job.schedule.cron_expr) : 'Keep running' : 'No schedule'}</p>
          </div>}

        </aside>
      </div>
    </>
  )
}
