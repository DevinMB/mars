import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import SqlEditor from '../components/SqlEditor'
import ValidationPanel from '../components/ValidationPanel'
import TablePicker from '../components/TablePicker'
import { Alert, Field, PageHeader, Spinner } from '../components/ui'

export default function JobEditor() {
  const { name: editing } = useParams()
  const navigate = useNavigate()

  const [entries, setEntries] = useState(null)
  const [targets, setTargets] = useState([])
  const [target, setTarget] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [jobType, setJobType] = useState('streaming')
  const [sql, setSql] = useState('')
  const [refs, setRefs] = useState([])
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [check, setCheck] = useState(null)
  const [checking, setChecking] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    (async () => {
      setEntries(await api.catalog())
      setTargets(await api.targets().catch(() => []))
      if (editing) {
        const j = await api.job(editing)
        setName(j.name)
        setDescription(j.description || '')
        setJobType(j.job_type)
        setSql(j.sql_text)
        setRefs(j.catalog_refs)
        setTarget(j.target_name || '')
      }
    })().catch((err) => setError(err.message))
  }, [editing])

  // Checking costs a Flink planner round trip, so it waits for a pause in typing
  // rather than firing on every keystroke. Each result carries the text it was
  // computed from: replies can arrive out of order, and showing "compiles" for a
  // statement two edits old is worse than showing nothing.
  const latest = useRef(0)
  const runCheck = useCallback(async (sqlText, catalogRefs, targetName, jobName, type) => {
    if (!sqlText.trim()) { setCheck(null); setDirty(false); return }
    const token = ++latest.current
    setChecking(true)
    try {
      const r = await api.validateDraft({
        name: jobName || 'draft',
        sql_text: sqlText,
        catalog_refs: catalogRefs,
        target_name: targetName || null,
        job_type: type,
      })
      if (token === latest.current) { setCheck(r); setDirty(false) }
    } catch {
      // A console that cannot reach its own API should not bury the editor in
      // red; saving will report the real problem.
      if (token === latest.current) setCheck(null)
    } finally {
      if (token === latest.current) setChecking(false)
    }
  }, [])

  useEffect(() => {
    if (!sql.trim()) { setCheck(null); return }
    setDirty(true)
    const t = setTimeout(() => runCheck(sql, refs, target, editing || name, jobType), 700)
    return () => clearTimeout(t)
  }, [sql, refs, target, jobType, name, editing, runCheck])

  const toggleRef = (entryName) =>
    setRefs((prev) =>
      prev.includes(entryName) ? prev.filter((r) => r !== entryName) : [...prev, entryName],
    )

  const save = async () => {
    setSaving(true)
    setError(null)
    const body = {
      name, description, job_type: jobType, sql_text: sql,
      catalog_refs: refs, note: note || undefined,
      target_name: target || null,
    }
    try {
      if (editing) await api.updateJob(editing, body)
      else await api.createJob(body)
      navigate(`/jobs/${encodeURIComponent(name)}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!entries) return <Spinner />

  const sources = entries.filter((e) => e.kind === 'source')
  const sinks = entries.filter((e) => e.kind === 'sink')

  return (
    <>
      <PageHeader
        title={editing ? `Edit ${editing}` : 'New job'}
        back={{ to: editing ? `/jobs/${encodeURIComponent(editing)}` : '/jobs', label: editing ? editing : 'Jobs' }}
        actions={
          <>
            {check && !check.ok && !dirty && (
              <span className="text-xs text-red-700 self-center mr-1">
                Will not compile
              </span>
            )}
            <button className="btn-primary" disabled={saving || !name || !sql} onClick={save}>
              {saving ? 'Saving…' : editing ? 'Save changes' : 'Create job'}
            </button>
          </>
        }
      />

      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div className="card p-6 space-y-4">
            <Field label="Name" required>
              <input className="input mono" value={name} disabled={!!editing}
                     onChange={(e) => setName(e.target.value)} placeholder="whispers_to_couch" />
            </Field>
            <Field label="Description">
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            {targets.length > 1 && (
              <Field
                label="Runs on"
                hint={
                  'Which Flink cluster receives this job. A cluster schedules tasks into ' +
                  'any free slot it has, so choosing where a job runs means choosing the ' +
                  'cluster \u2014 not a machine within one.'
                }
              >
                <select className="input" value={target} onChange={(e) => setTarget(e.target.value)}>
                  <option value="">
                    {targets.find((t) => t.is_default)?.name || 'default'} (default)
                  </option>
                  {targets
                    .filter((t) => !t.is_default && t.enabled)
                    .map((t) => (
                      <option key={t.name} value={t.name}>
                        {t.name}
                        {t.description ? ` \u2014 ${t.description}` : ''}
                      </option>
                    ))}
                </select>
              </Field>
            )}

            <Field
              label="Type"
              hint={
                jobType === 'streaming'
                  ? 'Runs continuously until cancelled.'
                  : 'Reads a finite input and finishes. Only this type can be put on a cron schedule.'
              }
            >
              <div className="flex gap-2">
                {['streaming', 'batch'].map((t) => (
                  <button key={t} type="button" onClick={() => setJobType(t)}
                          className={jobType === t ? 'btn-primary' : 'btn-secondary'}>
                    {t === 'streaming' ? 'Streaming' : 'Batch'}
                  </button>
                ))}
              </div>
            </Field>
          </div>

          <div className="card p-6">
            <h2 className="font-medium text-slate-900 mb-1">Statement</h2>
            <p className="text-xs text-slate-500 mb-4">
              The tables you tick on the right are created before this runs, so refer to
              them by name.
            </p>
            <SqlEditor
              value={sql}
              onChange={setSql}
              rows={14}
              marker={check && !check.ok && check.line
                ? { line: check.line, message: check.error }
                : null}
            />
            <ValidationPanel result={check} checking={checking} dirty={dirty} />
          </div>

          {editing && (
            <div className="card p-6">
              <Field label="What changed?" hint="Saved with this version, so the history reads like a story.">
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)}
                       placeholder="Switched the sink to the -flink database" />
              </Field>
            </div>
          )}
        </div>

        <aside>
          <div className="card p-4 sticky top-20">
            <h3 className="text-sm font-medium text-slate-900 mb-1">Tables this job uses</h3>
            <p className="text-xs text-slate-500 mb-3">
              Their definitions are replayed each time the job runs.
            </p>

            <TablePicker
              entries={entries}
              selected={refs}
              onToggle={toggleRef}
            />
          </div>
        </aside>
      </div>
    </>
  )
}
