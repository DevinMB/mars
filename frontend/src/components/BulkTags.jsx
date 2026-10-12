import { useState } from 'react'
import { api } from '../lib/api'
import { Alert } from './ui'

const split = (text) => text.split(/[\s,]+/).map((t) => t.trim().toLowerCase()).filter(Boolean)

/** Adds or removes tags on the selected jobs, right away (tags change nothing that runs). */
export default function BulkTags({ jobs, onClose, onDone }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const existing = [...new Set(jobs.flatMap((j) => j.tags || []))].sort()

  const apply = async (mode, list = split(text)) => {
    if (!list.length) return
    setBusy(true); setError(null)
    try {
      await api.tagJobs(jobs.map((j) => j.name), mode === 'add' ? list : [], mode === 'remove' ? list : [])
      setText(''); onDone()
    } catch (err) { setError(err.message) } finally { setBusy(false) }
  }

  return (
    <div className="card p-4 mb-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-[14px] font-medium text-slate-900">Tags on {jobs.length} job{jobs.length === 1 ? '' : 's'}</h2>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" onClick={onClose}>Close</button>
      </div>
      <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); apply('add') }}>
        <input id="bulk-tags" className="input w-64" aria-label="Tags" placeholder="e.g. buoys, phase1"
               value={text} onChange={(e) => setText(e.target.value)} />
        <button className="btn-primary" disabled={busy || !split(text).length}>Add</button>
        <button type="button" className="btn-secondary" disabled={busy || !split(text).length} onClick={() => apply('remove')}>Remove</button>
      </form>
      <p className="text-[12px] text-slate-500 mt-1.5">
        Lowercase words, digits, '-' or '_'; separate several with commas. Tags only organise jobs: nothing restarts.
      </p>
      {existing.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[12px] text-slate-500">
          On these jobs:
          {existing.map((t) => (
            <button key={t} type="button" disabled={busy} title={`Remove ${t} from the selected jobs`}
                    className="text-[11px] rounded-sm px-1.5 bg-slate-100 text-slate-600 hover:bg-red-50 hover:text-red-700"
                    onClick={() => apply('remove', [t])}>{t} ×</button>
          ))}
        </div>
      )}
      {error && <div className="mt-3"><Alert level="danger">{error}</Alert></div>}
    </div>
  )
}
