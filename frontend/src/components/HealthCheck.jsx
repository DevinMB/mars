import { useState } from 'react'
import { api } from '../lib/api'
import { Alert } from './ui'

// Asks the target whether it is there, while the form is still open.
//
// A wrong address or a missing database does not fail on Save. It fails minutes
// later on a TaskManager, as a restart loop with a Java stack trace -- and
// everything needed to catch it was known the moment it was typed.
export default function HealthCheck({ connector, options }) {
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  const run = async () => {
    setBusy(true)
    try { setResult(await api.checkHealth(connector, options)) }
    catch (e) { setResult({ ok: false, detail: e.message }) }
    finally { setBusy(false) }
  }

  const level = result?.ok === true ? 'success' : result?.ok === false ? 'warning' : 'info'

  return (
    <div className="mt-4 border-t border-slate-200 pt-4">
      <div className="flex items-center gap-3">
        <button type="button" className="btn-secondary text-sm" onClick={run} disabled={busy}>
          {busy ? 'Checking…' : 'Test connection'}
        </button>
        <span className="text-xs text-slate-500">
          Checks from the MARS container, which is usually — but not always — the same
          network the job will run on.
        </span>
      </div>

      {result && (
        <div className="mt-3">
          <Alert level={level}>
            {result.detail}
            {result.hint && <div className="mt-1 text-xs">{result.hint}</div>}
          </Alert>
        </div>
      )}
    </div>
  )
}
