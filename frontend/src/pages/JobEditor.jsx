import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api } from '../lib/api'
import useUnsavedChanges from '../lib/useUnsavedChanges'
import { useNotify } from '../components/InteractionProvider'
import SqlEditor from '../components/SqlEditor'
import ValidationPanel, { ValidationStatus } from '../components/ValidationPanel'
import TablePicker from '../components/TablePicker'
import SchemaPanel from '../components/SchemaPanel'
import PromptPanel from '../components/PromptPanel'
import { useOutputPreview } from '../components/OutputPreview'
import { buildCompletions } from '../components/Completion'
import { Alert, Field, PageHeader, Spinner } from '../components/ui'

export default function JobEditor() {
  const { name: editing } = useParams()
  const navigate = useNavigate()
  const notify = useNotify()
  const [running, setRunning] = useState(false) // a running job changes cluster only by moving
  const [loaded, setLoaded] = useState(false)
  const [initial, setInitial] = useState(null)

  const [entries, setEntries] = useState(null)
  const [targets, setTargets] = useState([])
  const [target, setTarget] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tagText, setTagText] = useState('') // comma-separated; tags organise, they never change a version
  const [jobType, setJobType] = useState('streaming')
  const [sql, setSql] = useState('')
  const [refs, setRefs] = useState([])
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [check, setCheck] = useState(null)
  const [checking, setChecking] = useState(false)
  const preview = useOutputPreview({ sql, refs, targetName: target })
  const [dirty, setDirty] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(true)
  const [docFields, setDocFields] = useState({})
  const [ai, setAi] = useState(null)

  // ?from=<name> opens a copy of an existing job as a new draft. A clone that
  // saved itself immediately would create a half-considered duplicate; this way
  // it is an ordinary unsaved job until someone names it and presses Create.
  const cloneOf = new URLSearchParams(window.location.search).get('from')

  useEffect(() => {
    (async () => {
      setEntries(await api.catalog())
      setTargets(await api.targets().catch(() => []))
      // A viewer without access to the AI settings simply does not see the box.
      setAi(await api.aiProvider().catch(() => null))
      if (!editing && cloneOf) {
        const j = await api.job(cloneOf)
        setName(`${j.name}_copy`)
        setDescription(j.description || '')
        setTagText((j.tags || []).join(', '))
        setJobType(j.job_type)
        setSql(j.sql_text)
        setRefs(j.catalog_refs)
        setTarget(j.target_name || '')
        if ((j.catalog_refs || []).length) setPickerOpen(false)
      }

      if (editing) {
        const j = await api.job(editing)
        setName(j.name)
        setDescription(j.description || '')
        setTagText((j.tags || []).join(', '))
        setJobType(j.job_type)
        setSql(j.sql_text)
        setRefs(j.catalog_refs)
        setTarget(j.target_name || '')
        setRunning(['running', 'restarting', 'submitting'].includes(j.latest_run?.state))
        // Editing an existing job: the tables are already chosen, so lead with
        // the columns instead.
        if ((j.catalog_refs || []).length) setPickerOpen(false)
      }
      setLoaded(true)
    })().catch((err) => setError(err.message))
  }, [editing, cloneOf])

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

  const completions = useMemo(
    () => buildCompletions(entries || [], refs, docFields),
    [entries, refs, docFields],
  )

  const sqlRef = useRef(null)
  const insertAtCursor = (text) => {
    const ta = sqlRef.current
    if (!ta) { setSql((prev) => `${prev}${text}`); return }
    const { selectionStart: a, selectionEnd: b } = ta
    setSql((prev) => `${prev.slice(0, a)}${text}${prev.slice(b)}`)
    requestAnimationFrame(() => {
      ta.focus()
      ta.selectionStart = ta.selectionEnd = a + text.length
    })
  }

  const toggleRef = (entryName) =>
    setRefs((prev) =>
      prev.includes(entryName) ? prev.filter((r) => r !== entryName) : [...prev, entryName],
    )

  const serialized = JSON.stringify({ name, description, tagText, jobType, target, sql, refs, note })
  useEffect(() => { if (loaded && initial === null) setInitial(serialized) }, [loaded, initial, serialized])
  const unsaved = initial !== null && initial !== serialized
  const allowNavigation = useUnsavedChanges(unsaved)

  const save = async () => {
    setSaving(true)
    setError(null)
    const body = {
      name, description, job_type: jobType, sql_text: sql,
      catalog_refs: refs, note: note || undefined,
      target_name: target || null,
      tags: tagText.split(/[\s,]+/).map((t) => t.trim().toLowerCase()).filter(Boolean),
    }
    try {
      if (editing) await api.updateJob(editing, body)
      else await api.createJob(body)
      allowNavigation()
      notify(editing ? 'Changes saved.' : 'Job created.')
      navigate(`/jobs/${encodeURIComponent(name)}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!loaded && error) return <Alert level="danger">{error}</Alert>
  if (!loaded || !entries) return <Spinner />

  return (
    <>
      <PageHeader
        title={editing ? `Edit ${editing}` : cloneOf ? `Copy of ${cloneOf}` : 'New job'}
        back={{ to: editing ? `/jobs/${encodeURIComponent(editing)}` : '/jobs', label: editing ? editing : 'Jobs' }}
        subtitle={unsaved ? 'Unsaved changes' : null}
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

      <div className="editor-grid">
        <div className="space-y-6 min-w-0">
          <div className="form-section grid gap-4 sm:grid-cols-2">
            <Field label="Name" required>
              <input className="input mono" value={name} disabled={!!editing}
                     onChange={(e) => setName(e.target.value)} placeholder="events_to_archive" />
            </Field>
            <Field label="Description">
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} />
            </Field>
            <Field label="Tags" hint="Group jobs by what they do, e.g. buoys, ingest. Separate with commas. Changing tags never restarts or re-versions the job.">
              <input id="job-tags" className="input" value={tagText} placeholder="buoys, ingest"
                     onChange={(e) => setTagText(e.target.value)} />
            </Field>
            {targets.length > 1 && (
              <Field
                label="Runs on"
                hint={running
                  ? 'It is running, so its cluster cannot change here. Use Move to cluster on the job\'s page, which keeps its state.'
                  : 'The cluster that will run this job. To keep its state when changing cluster, use Move to cluster on the job\'s page.'}
              >
                <select className="input" value={target} disabled={running} onChange={(e) => setTarget(e.target.value)}>
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
                          aria-pressed={jobType === t} className={`choice ${jobType === t ? 'choice-selected' : ''}`}>
                    {t === 'streaming' ? 'Streaming' : 'Batch'}
                  </button>
                ))}
              </div>
            </Field>
          </div>


          <div className="form-section">
            <h2 className="font-medium text-slate-900 mb-1">Statement</h2>
            <p className="text-xs text-slate-500 mb-4">
              Use the selected tables and columns to write your query.
            </p>
            {ai?.configured && <details className="mb-4 border border-slate-200 rounded-lg bg-surface">
              <summary className="cursor-pointer px-4 py-3 text-[13px] font-medium">Draft with AI</summary>
              <PromptPanel
                enabled={Boolean(ai?.configured)}
                refs={refs}
                completions={completions}
                jobType={jobType}
                targetName={target}
                jobName={editing || name}
                documentFields={docFields}
                currentSql={sql}
                onDraft={(text) => { setSql(text); setCheck(null) }}
              />
            </details>}
            <SqlEditor
              ref={sqlRef}
              value={sql}
              onChange={setSql}
              rows={28}
              minRows={10}
              title="SQL"
              actions={preview.controls}
              status={<span className="flex flex-wrap gap-x-3">
                <ValidationStatus result={check} checking={checking} dirty={dirty} />
                <span className="text-slate-400">Preview runs with no sink, so it cannot write anything.</span>
              </span>}
              marker={check && !check.ok && check.line
                ? { line: check.line, message: check.error }
                : null}
              completions={completions}
            />
            <ValidationPanel result={check} checking={checking} dirty={dirty} />
            {preview.panel}
          </div>

          {editing && (
            <div className="form-section">
              <Field label="Change note" hint="Included in version history.">
                <input className="input" value={note} onChange={(e) => setNote(e.target.value)}
                       placeholder="Switched the sink to the -flink database" />
              </Field>
            </div>
          )}
        </div>

        <aside>
          {/* Columns come first once tables are chosen: picking tables happens
              once, but the columns are consulted continuously while writing, and
              they were previously below a long list and off the bottom of the
              screen. */}
          <div className="lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] overflow-y-auto border border-slate-200 bg-surface rounded-lg p-4">
            {refs.length > 0 && (
              <div className="mb-3">
                <h3 className="text-sm font-medium text-slate-900 mb-1">
                  Columns available
                </h3>
                <p className="text-xs text-slate-500 mb-2">
                  Select a column to insert it at the cursor.
                </p>
                {refs
                  .map((r) => entries.find((e) => e.name === r))
                  .filter(Boolean)
                  .map((entry) => (
                    <SchemaPanel key={entry.name} entry={entry} onInsert={insertAtCursor} />
                  ))}
              </div>
            )}

            <div className={refs.length > 0 ? 'border-t border-slate-200 pt-3' : ''}>
              <button
                type="button"
                aria-expanded={pickerOpen}
                onClick={() => setPickerOpen((v) => !v)}
                className="w-full flex items-center justify-between gap-2 text-left"
              >
                <span className="text-sm font-medium text-slate-900">
                  Tables
                </span>
                <span className="text-xs text-slate-500 shrink-0">
                  {refs.length > 0 && `${refs.length} selected`}
                  <span className="ml-1 text-slate-400">{pickerOpen ? '\u25B4' : '\u25BE'}</span>
                </span>
              </button>

              {pickerOpen && (
                <>
                  <p className="text-xs text-slate-500 mt-1 mb-3">
                    Select the sources and sinks for this job.
                  </p>
                  <TablePicker
                    entries={entries}
                    selected={refs}
                    onToggle={toggleRef}
                  />
                </>
              )}
            </div>
          </div>
        </aside>
      </div>
    </>
  )
}
