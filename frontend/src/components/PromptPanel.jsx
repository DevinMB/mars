import { useRef, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, Spinner } from './ui'
import { CompletionList, useCompletion } from './Completion'
import SqlDiff from './SqlDiff'

// Describe the job in words; a model drafts the statement. Two things make this
// worth offering rather than a novelty: the model is told exactly which tables
// and columns exist, and the draft is compiled before anyone sees it.
//
// The draft always lands in the editor for a person to approve. Nothing here can
// submit anything.
export default function PromptPanel({
  enabled, refs, completions, onDraft, jobType, targetName, jobName, documentFields,
  currentSql = '',
}) {
  const [focused, setFocused] = useState(false)
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
        // With a statement already written, ask for a change to it rather than a
        // replacement, so a small request stays a small change.
        current_sql: currentSql,
      })
      // Nothing is applied here. The proposal is shown as a diff and waits for a
      // decision: a draft that silently replaced the editor would destroy work
      // that was never offered up for changing.
      setResult(r)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!enabled) return null

  return (
    <div className="px-4 pb-4">
      <p className="text-xs text-slate-500 mb-3">
        Describe a query or a change. Use <code className="mono">@</code> for tables and columns.
        Review the proposed SQL before applying it. This does not run the job.
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
          aria-label="Describe the SQL to draft"
          onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
          className="input mono h-24 resize-y"
          value={prompt}
          spellCheck={false}
          placeholder={currentSql
            ? 'also write @doc.username'
            : 'Take each whisper and write @doc.message and @doc.username into the whispers sink'}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => { completion.onKeyDown(e) }}
        />
        {focused && completion.open && (
          <CompletionList
            matches={completion.matches}
            active={completion.active}
            onPick={completion.accept}
          />
        )}
      </div>

      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {result && (
        <div className="mt-3 space-y-2">
          {result.ok ? (
            <Alert level="success">
              {result.amended ? 'Changed' : 'Drafted'} and it compiles
              {result.attempts > 1 && ' (after one correction)'}. Nothing has been
              applied yet.
            </Alert>
          ) : (
            <Alert level="warning" title="This does not compile">
              {result.error || 'The draft could not be checked.'}
              {result.hint && <div className="mt-1">{result.hint}</div>}
              <div className="mt-1 text-xs">
                You can still apply it and fix it in the editor, or describe the
                change differently and try again.
              </div>
            </Alert>
          )}

          {(result.notes || []).map((n, i) => (
            <p key={i} className="text-xs text-slate-400">{n}</p>
          ))}

          {result.sql && (
            <>
              <SqlDiff before={currentSql} after={result.sql} />
              <div className="flex items-center gap-2">
                <button
                  className="btn-primary text-sm"
                  onClick={() => { onDraft(result.sql); setResult(null); setPrompt('') }}
                >
                  {currentSql ? 'Apply this change' : 'Use this statement'}
                </button>
                <button className="btn-secondary text-sm" onClick={() => setResult(null)}>
                  Discard
                </button>
              </div>
            </>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 mt-3">
        <button
          className="btn-primary text-sm"
          onClick={draft}
          disabled={busy || !prompt.trim() || refs.length === 0}
        >
          {busy ? 'Drafting…' : 'Draft SQL'}
        </button>
        {busy && <Spinner label="Asking the model, then compiling the answer" />}
      </div>
    </div>
  )
}
