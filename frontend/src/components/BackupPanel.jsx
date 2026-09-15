import { useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, Spinner } from './ui'

function Group({ label, items, tone }) {
  if (!items?.length) return null
  const tones = {
    good: 'text-emerald-700',
    change: 'text-amber-700',
    quiet: 'text-slate-500',
    bad: 'text-red-700',
  }
  return (
    <div className="mt-2">
      <div className={`text-xs font-medium ${tones[tone]}`}>
        {label} ({items.length})
      </div>
      <ul className="mt-0.5 space-y-0.5">
        {items.slice(0, 40).map((n) => (
          <li key={n} className="mono text-xs text-slate-600">{n}</li>
        ))}
        {items.length > 40 && (
          <li className="text-xs text-slate-400">…and {items.length - 40} more</li>
        )}
      </ul>
    </div>
  )
}

// Definitions in, definitions out. The two things this is for are recovering an
// installation and reviewing changes in version control, and they want the same
// mechanism.
export default function BackupPanel() {
  const [text, setText] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const [replace, setReplace] = useState(false)
  const fileRef = useRef(null)

  const act = async (label, fn) => {
    setBusy(label); setError(null)
    try { await fn() } catch (e) { setError(e.message) } finally { setBusy(null) }
  }

  const download = () => act('export', async () => {
    const yaml = await api.exportDefinitions()
    const stamp = new Date().toISOString().slice(0, 10)
    const url = URL.createObjectURL(new Blob([yaml], { type: 'application/yaml' }))
    const a = document.createElement('a')
    a.href = url
    a.download = `mars-export-${stamp}.yaml`
    a.click()
    URL.revokeObjectURL(url)
  })

  const pick = (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = () => { setText(String(reader.result || '')); setResult(null) }
    reader.readAsText(file)
  }

  const check = () => act('check', async () => {
    setResult(await api.importDefinitions({ yaml_text: text, dry_run: true, replace }))
  })

  const apply = () => act('apply', async () => {
    setResult(await api.importDefinitions({ yaml_text: text, dry_run: false, replace }))
  })

  const changesSomething =
    result && (result.created.length > 0 || result.updated.length > 0)

  return (
    <div className="card p-5 mb-4">
      <h2 className="font-medium text-slate-900 mb-1">Backup and restore</h2>
      <p className="text-xs text-slate-500 mb-4">
        Every catalog entry, job, schedule and cluster, as YAML. Safe to commit:
        secret <em>values</em> are never included — the file lists the names it needs
        instead. Run history, accounts and the encryption key are not here either;
        those need a backup of the console's data volume.
      </p>

      {error && (
        <div className="mb-3">
          <Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert>
        </div>
      )}

      <div className="flex items-center gap-3 pb-4 border-b border-slate-200">
        <button className="btn-secondary text-sm" onClick={download} disabled={busy === 'export'}>
          {busy === 'export' ? 'Exporting…' : 'Export definitions'}
        </button>
        <span className="text-xs text-slate-500">Downloads a YAML file.</span>
      </div>

      <div className="pt-4">
        <h3 className="text-sm font-medium text-slate-900 mb-1">Import</h3>
        <p className="text-xs text-slate-500 mb-3">
          Nothing is written until you ask for it. Check first — the result below is
          exactly what applying would do.
        </p>

        <div className="flex items-center gap-3 mb-3">
          <input ref={fileRef} type="file" accept=".yaml,.yml,text/yaml"
                 className="hidden" onChange={pick} />
          <button className="btn-secondary text-sm" onClick={() => fileRef.current?.click()}>
            Choose a file…
          </button>
          {text && <span className="text-xs text-slate-500">{text.length} characters loaded</span>}
        </div>

        <textarea
          className="input mono h-28 resize-y"
          placeholder="…or paste an export here"
          value={text}
          spellCheck={false}
          onChange={(e) => { setText(e.target.value); setResult(null) }}
        />

        <label className="flex items-start gap-2 mt-3 text-sm text-slate-700">
          <input type="checkbox" checked={replace}
                 className="mt-0.5 rounded border-slate-300 text-brand-600 focus:ring-brand-500/30"
                 onChange={(e) => { setReplace(e.target.checked); setResult(null) }} />
          <span>
            Overwrite definitions that already exist
            <span className="block text-xs text-slate-500 mt-0.5">
              Off, an import only adds what is missing and leaves the rest alone. On, it
              replaces matching entries — including statements jobs are currently
              running from. Running jobs keep running the old version until restarted.
            </span>
          </span>
        </label>

        <div className="flex items-center gap-2 mt-3">
          <button className="btn-secondary text-sm" onClick={check}
                  disabled={!text.trim() || busy === 'check'}>
            {busy === 'check' ? 'Checking…' : 'Check what it would change'}
          </button>
          <button
            className={changesSomething ? 'btn-primary text-sm' : 'btn-secondary text-sm'}
            disabled={!result || !result.dry_run || !result.ok || busy === 'apply' || !changesSomething}
            onClick={() => {
              const summary = [
                result.created.length ? `create ${result.created.length}` : null,
                result.updated.length ? `overwrite ${result.updated.length}` : null,
              ].filter(Boolean).join(' and ')
              if (!confirm(`This will ${summary}. Continue?`)) return
              apply()
            }}
          >
            {busy === 'apply' ? 'Applying…' : 'Apply'}
          </button>
          {busy && <Spinner label="Working" />}
        </div>

        {result && (
          <div className="mt-4 border-t border-slate-100 pt-3">
            <div className="flex items-center gap-2 mb-1">
              <h4 className="text-sm font-medium text-slate-900">
                {result.dry_run ? 'What this would do' : 'Applied'}
              </h4>
              {result.dry_run
                ? <Badge tone="slate">nothing written</Badge>
                : <Badge tone="accent">written</Badge>}
            </div>

            {!result.created.length && !result.updated.length && !result.errors.length && (
              <p className="text-xs text-slate-500">
                Nothing to change — this installation already matches the file.
              </p>
            )}

            {result.missing_secrets?.length > 0 && (
              <div className="mt-2">
                <Alert level="warning" title="Secrets this file needs and this install lacks">
                  {result.missing_secrets.join(', ')}
                  <div className="mt-1 text-xs">
                    Add them under Secrets, or the imported jobs will fail when they run.
                  </div>
                </Alert>
              </div>
            )}

            <Group label="Create" items={result.created} tone="good" />
            <Group label="Overwrite" items={result.updated} tone="change" />
            <Group label="Already present, left alone" items={result.skipped} tone="quiet" />
            <Group label="Identical" items={result.unchanged} tone="quiet" />
            <Group label="Refused" items={result.errors} tone="bad" />
          </div>
        )}
      </div>
    </div>
  )
}
