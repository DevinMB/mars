import { useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, Spinner } from './ui'
import { CompletionList, useCompletion } from './Completion'

// Describe the job in words; a model drafts the statement. Two things make this
// worth offering rather than a novelty: the model is told exactly which tables
// and columns exist, and the draft is compiled before anyone sees it.
//
// The draft always lands in the editor for a person to approve. Nothing here can
// submit anything.
export default function PromptPanel({
  enabled, refs, completions, onDraft, jobType, targetName, jobName, documentFields,
}) {
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const taRef = useRef(null)

  const completion = useCompletion({
    value: prompt, onChange: setPrompt, taRef, items: completions, mode: 'mention',
  })

  const draft = async () => {
    setBusy(true); setError(null); setResult(null)
    try {
      const r = await api.draftJob({
        prompt,
        catalog_refs: refs,
        job_type: jobType,
        target_name: targetName || null,
        name: jobName || 'draft',
        document_fields: documentFields,
      })
      setResult(r)
      if (r.sql) onDraft(r.sql)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!enabled) {
    return (
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-1">
          <h2 className="font-medium text-slate-900">Describe it instead</h2>
          <Badge tone="slate">Off</Badge>
        </div>
        <p className="text-xs text-slate-500">
          Say what the job should do in plain words and have a draft written for you.
          An administrator turns this on under AI by choosing a model.
        </p>
      </div>
    )
  }

  return (
    <div className="card p-5">
      <h2 className="font-medium text-slate-900 mb-1">Describe it instead</h2>
      <p className="text-xs text-slate-500 mb-3">
        Say what the job should do. Type <code className="mono">@</code> to refer to a
        table, column or document field. The draft is compiled before it is shown, and
        always lands in the editor for you to check — it is never run.
      </p>

      {refs.length === 0 && (
        <div className="mb-3">
          <Alert level="warning">
            Choose the tables this job uses first. Without them a draft would be
            guessing at names.
          </Alert>
        </div>
      )}

      <div className="relative">
        <textarea
          ref={taRef}
          className="input mono h-24 resize-y"
          value={prompt}
          spellCheck={false}
          placeholder="Take each whisper and write @message and @username into the whispers sink"
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { completion.onKeyDown(e) }}
        />
        {completion.open && (
          <CompletionList
            matches={completion.matches}
            active={completion.active}
            onPick={completion.accept}
          />
        )}
      </div>

      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {result && (
        <div className="mt-3">
          {result.ok ? (
            <Alert level="success">
              Drafted and it compiles
              {result.attempts > 1 && ' (after one correction)'}. It is in the editor
              below — read it before saving.
            </Alert>
          ) : (
            <Alert level="warning" title="Drafted, but it does not compile">
              {result.error || 'The draft could not be checked.'}
              {result.hint && <div className="mt-1">{result.hint}</div>}
              <div className="mt-1 text-xs">
                It is in the editor below; fix it there, or describe the job
                differently and try again.
              </div>
            </Alert>
          )}
          {(result.notes || []).map((n, i) => (
            <p key={i} className="text-xs text-slate-400 mt-1">{n}</p>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3 mt-3">
        <button
          className="btn-primary text-sm"
          onClick={draft}
          disabled={busy || !prompt.trim() || refs.length === 0}
        >
          {busy ? 'Drafting…' : 'Draft the statement'}
        </button>
        {busy && <Spinner label="Asking the model, then compiling the answer" />}
      </div>
    </div>
  )
}
