import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import { duration, relativeTime } from '../lib/format'
import SqlEditor from '../components/SqlEditor'
import Diagnostics from '../components/Diagnostics'
import { Alert, Badge, CodeBlock, Field, PageHeader, Spinner, StatePill } from '../components/ui'

const ACTIVE = ['running', 'submitting', 'restarting']

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
  const [mode, setMode] = useState(job.schedule?.mode || (job.job_type === 'batch' ? 'cron' : 'supervisor'))
  const [cron, setCron] = useState(job.schedule?.cron_expr || '0 * * * *')
  const [error, setError] = useState(null)

  const save = async () => {
    setError(null)
    try {
      await api.setSchedule(job.name, { mode, cron_expr: mode === 'cron' ? cron : null, enabled: true })
      onChange()
    } catch (err) { setError(err.message) }
  }
  const clear = async () => {
    try { await api.clearSchedule(job.name); onChange() }
    catch (err) { setError(err.message) }
  }

  return (
    <div className="card p-4">
      <h3 className="text-sm font-medium text-slate-900 mb-3">Schedule</h3>
      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="space-y-3">
        <select className="input" value={mode} onChange={(e) => setMode(e.target.value)}>
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
          <button className="btn-primary text-sm" onClick={save}>Save</button>
          {job.schedule && <button className="btn-secondary text-sm" onClick={clear}>Remove</button>}
        </div>

        {job.schedule?.next_fire_at && (
          <p className="text-xs text-slate-500">Next run {relativeTime(job.schedule.next_fire_at)}</p>
        )}
      </div>
    </div>
  )
}

export default function JobDetail() {
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

  const load = useCallback(async () => {
    try {
      const [j, r, v] = await Promise.all([
        api.job(name), api.jobRuns(name), api.jobVersions(name),
      ])
      setJob(j); setRuns(r); setVersions(v); setError(null)
    } catch (err) { setError(err.message) }
  }, [name])

  useEffect(() => { load() }, [load])

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
        subtitle={job.description}
        back={{ to: '/jobs', label: 'Jobs' }}
        actions={
          <>
            <button className="btn-secondary" onClick={validate} disabled={busy === 'validate'}>
              {busy === 'validate' ? 'Checking…' : 'Validate'}
            </button>
            <Link to={`/jobs/${encodeURIComponent(job.name)}/edit`} className="btn-secondary">Edit</Link>
            {isActive ? (
              <button className="btn-danger" disabled={busy === 'cancel'}
                      onClick={() => act('cancel', () => api.cancelJob(name))}>
                {busy === 'cancel' ? 'Stopping…' : 'Stop'}
              </button>
            ) : (
              <button className="btn-primary" disabled={busy === 'run'}
                      onClick={() => act('run', () => api.runJob(name))}>
                {busy === 'run' ? 'Starting…' : 'Run'}
              </button>
            )}
          </>
        }
      />

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

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div className="card overflow-hidden">
            <div className="flex border-b border-slate-200">
              {[['sql', 'Statement'], ['diagnostics', 'Diagnostics'],
                ['script', 'What actually runs'], ['history', 'Versions']].map(([id, label]) => (
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
              {tab === 'sql' && <SqlEditor value={job.sql_text} onChange={() => {}} readOnly rows={12} />}

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
              <table className="w-full text-sm">
                <tbody className="divide-y divide-slate-100">
                  {runs.map((r) => (
                    <tr key={r.id}>
                      <td className="px-4 py-3"><StatePill state={r.state} /></td>
                      <td className="px-4 py-3 text-slate-600">{relativeTime(r.started_at)}</td>
                      <td className="px-4 py-3 text-slate-600">{duration(r.started_at, r.ended_at)}</td>
                      <td className="px-4 py-3 text-slate-500 text-xs">
                        {r.triggered_by_schedule ? 'scheduled' : r.submitted_by || '—'}
                        {r.restarts > 0 && <span className="text-amber-700 ml-2">{r.restarts} restarts</span>}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500 max-w-xs truncate">
                        {r.error_summary || ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <aside className="space-y-4">
          <div className="card p-4">
            <h3 className="text-sm font-medium text-slate-900 mb-3">Details</h3>
            <dl className="space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">State</dt>
                <dd><StatePill state={run?.state} /></dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Type</dt><dd className="text-slate-800">{job.job_type}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-slate-500">Version</dt><dd className="text-slate-800">v{job.version}</dd>
              </div>
              {run?.flink_job_id && (
                <div className="flex justify-between gap-3">
                  <dt className="text-slate-500">Flink job</dt>
                  <dd className="mono text-xs text-slate-600 truncate max-w-[9rem]">{run.flink_job_id}</dd>
                </div>
              )}
            </dl>
          </div>

          <div className="card p-4">
            <h3 className="text-sm font-medium text-slate-900 mb-2">Tables used</h3>
            {job.catalog_refs.length === 0 ? (
              <p className="text-xs text-slate-500">None.</p>
            ) : (
              <ul className="space-y-1">
                {job.catalog_refs.map((r) => (
                  <li key={r}>
                    <Link to={`/catalog/${encodeURIComponent(r)}/edit`}
                          className="mono text-sm link">{r}</Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <ScheduleCard job={job} onChange={load} />

          <div className="card p-4">
            <button
              className="btn-danger w-full justify-center text-sm"
              disabled={isActive}
              title={isActive ? 'Stop the job before deleting it' : undefined}
              onClick={async () => {
                if (!confirm(`Delete job "${job.name}"? This cannot be undone.`)) return
                try { await api.deleteJob(job.name); navigate('/jobs') }
                catch (err) { setError(err.message) }
              }}
            >
              Delete job
            </button>
          </div>
        </aside>
      </div>
    </>
  )
}
