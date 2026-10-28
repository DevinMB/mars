import { Alert } from './ui'

// The one-line verdict for the editor's status line. Details, when there is
// something to read, are in the panel below.
export function ValidationStatus({ result, checking, dirty }) {
  if (checking && !result) return <span role="status">Checking…</span>
  if (!result) return <span>Checked as you type</span>
  const stale = dirty || checking
  if (result.ok) {
    return (
      <span role="status" className={`inline-flex items-center gap-1.5 ${stale ? 'opacity-60' : 'text-emerald-700'}`}>
        <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        {stale ? 'Rechecking…' : 'Compiles'}
        {!stale && result.warnings?.length > 0 && <span className="text-amber-700">· {result.warnings.length} to check below</span>}
      </span>
    )
  }
  return (
    <span role="status" className={`inline-flex items-center gap-1.5 ${stale ? 'opacity-60' : 'text-red-700'}`}>
      <span aria-hidden="true" className="w-1.5 h-1.5 rounded-full bg-red-500" />
      {stale ? 'Rechecking…' : `Will not compile${result.line ? `: line ${result.line}` : ''}`}
    </span>
  )
}

// Shown under the editor while a statement is being written. The goal is that a
// mistake is visible before the job is saved, not after it has been deployed.
// A clean result says so in the editor's status line and needs no panel.
export default function ValidationPanel({ result, checking, dirty }) {
  if (!result) return null
  if (result.ok && !(result.warnings || []).length) return null

  // The result belongs to text that has since changed; saying "valid" about SQL
  // the user has already edited would be a lie with a short shelf life.
  const stale = dirty || checking

  return (
    <div className={`mt-3 space-y-2 ${stale ? 'opacity-50' : ''}`}>
      {result.ok ? null : (
        <Alert
          level="danger"
          title={
            result.line
              ? `Line ${result.line}${result.column ? `, column ${result.column}` : ''}`
              : 'This statement will not compile'
          }
        >
          <div>{result.error}</div>
          {result.hint && <div className="mt-1 text-red-800/90">{result.hint}</div>}

          {/* Flink's own words stay reachable: a rewrite is a guess about intent,
              and the person debugging may need the original to search for. */}
          {result.original_error && result.original_error !== result.error && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs text-red-800/70 hover:text-red-900">
                What Flink said
              </summary>
              <div className="mono text-xs mt-1 text-red-900/80 wrap-break-word">
                {result.original_error}
              </div>
            </details>
          )}
        </Alert>
      )}

      {(result.warnings || []).map((w, i) => (
        <Alert key={i} level={w.level === 'danger' ? 'danger' : 'warning'}
               title={w.level === 'danger' ? 'This will cause a problem' : 'Worth checking'}>
          {w.message}
        </Alert>
      ))}
    </div>
  )
}
