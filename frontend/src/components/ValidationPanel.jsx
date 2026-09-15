import { Alert, Spinner } from './ui'

// Shown under the editor while a statement is being written. The goal is that a
// mistake is visible before the job is saved, not after it has been deployed.
export default function ValidationPanel({ result, checking, dirty }) {
  if (checking && !result) {
    return <div className="mt-3"><Spinner label="Checking" /></div>
  }
  if (!result) return null

  // The result belongs to text that has since changed; saying "valid" about SQL
  // the user has already edited would be a lie with a short shelf life.
  const stale = dirty || checking

  return (
    <div className={`mt-3 space-y-2 ${stale ? 'opacity-50' : ''}`}>
      {result.ok ? (
        <Alert level="success">
          This statement compiles.
          {stale && ' Rechecking…'}
        </Alert>
      ) : (
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
              <div className="mono text-xs mt-1 text-red-900/80 break-words">
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
