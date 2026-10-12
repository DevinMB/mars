import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { copyText, selectContents } from '../lib/clipboard'

const LABELS = { console: 'Console', flink: 'Flink' }
const SHOWN = 8

export const short = (rev) => (rev ? rev.slice(0, 7) : null)

// Which parts of the installation have a newer release.
export function componentsBehind(version) {
  return ['console', 'flink'].filter((c) => version?.[c]?.update_available)
}

function CopyLine({ text }) {
  const [status, setStatus] = useState('')
  const ref = useRef(null)
  return (
    <div className="flex items-start gap-2">
      <code ref={ref} className="mono flex-1 min-w-0 bg-code-bg text-code-fg rounded-md px-2.5 py-1.5 text-[11.5px] break-all">
        {text}
      </code>
      <button type="button" className="shrink-0 text-[11px] px-2 py-1 rounded-md border border-slate-300 bg-surface text-slate-700 hover:bg-slate-50" onClick={async () => {
        const ok = await copyText(text)
        if (!ok) selectContents(ref.current)
        setStatus(ok ? 'copied' : 'manual')
        setTimeout(() => setStatus(''), ok ? 1500 : 4000)
      }}>
        {status === 'copied' ? 'Copied' : status === 'manual' ? 'Press Ctrl+C' : 'Copy'}
      </button>
    </div>
  )
}

/**
 * What changed and how to update one part of the installation.
 *
 * The console never updates itself: replacing containers needs control of the
 * host, which it deliberately does not have. So this says what to run, and says
 * plainly when that stops jobs.
 */
export function ComponentUpdate({ name, data, latest }) {
  const how = data.how_to_update
  const commits = data.commits || []
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h3 className="text-[14px] font-medium text-slate-900">{LABELS[name]}</h3>
        <span className="text-[12px] text-slate-500 tabular-nums">
          {short(data.revision)} → {latest?.label}, {data.behind_by} change{data.behind_by === 1 ? '' : 's'} behind
        </span>
      </div>
      <p className={`text-[12px] rounded-md px-3 py-2 ${how?.needs_window
        ? 'bg-amber-50 text-amber-900 border border-amber-200'
        : 'bg-slate-50 text-slate-600 border border-slate-200'}`}>
        {how?.needs_window
          ? <>Needs a short maintenance window: every job on this cluster stops while Flink is replaced, then resumes from its saved state.
            {' '}With a second cluster and job moves set up, <Link className="link" to="/cluster">upgrade one cluster at a time</Link> instead, so each job pauses only for its own move.</>
          : 'Jobs keep running. Only the console restarts, for a few seconds.'}
      </p>
      {commits.length > 0 && (
        <div>
          <div className="text-[12px] text-slate-500 mb-1">What changed</div>
          <ul className="text-[12.5px] text-slate-700 space-y-0.5 list-disc ml-4">
            {commits.slice(0, SHOWN).map((c) => <li key={c.sha}>{c.title}</li>)}
          </ul>
          {commits.length > SHOWN && (
            <div className="text-[12px] text-slate-500 mt-1 ml-4">and {commits.length - SHOWN} more</div>
          )}
        </div>
      )}
      {how && (
        <div>
          <div className="text-[12px] text-slate-500 mb-1.5">How to update</div>
          {how.command
            ? <CopyLine text={how.command} />
            : <ol className="space-y-1.5 text-[12.5px] text-slate-700 list-decimal ml-4">
                {how.steps.map((s) => <li key={s}>{s}</li>)}
              </ol>}
        </div>
      )}
    </div>
  )
}
