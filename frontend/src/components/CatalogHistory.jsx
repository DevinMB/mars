import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, Badge, Spinner } from './ui'
import { relativeTime } from '../lib/format'

// What this source or sink used to be, and who changed it.
//
// Worth having here more than on a job: one entry feeds many jobs, so this is
// the edit with the widest blast radius and it had no record at all.
export default function CatalogHistory({ name, usedBy = [] }) {
  const [versions, setVersions] = useState(null)
  const [open, setOpen] = useState(null)

  useEffect(() => {
    if (!name) return
    api.catalogVersions(name).then(setVersions).catch(() => setVersions([]))
  }, [name])

  if (!name) return null

  return (
    <div className="card p-6">
      <h2 className="font-medium text-slate-900 mb-1">History</h2>
      <p className="text-xs text-slate-500 mb-3">
        Only a change to the definition makes a version; rewording the description
        does not.
      </p>

      {usedBy.length > 0 && (
        <div className="mb-3">
          <Alert level="warning" title={`${usedBy.length} job${usedBy.length === 1 ? '' : 's'} use this`}>
            {usedBy.join(', ')}
            <div className="mt-1 text-xs">
              Saving a change here changes what they do. Running jobs keep the old
              definition until they are restarted.
            </div>
          </Alert>
        </div>
      )}

      {versions === null ? (
        <Spinner />
      ) : versions.length === 0 ? (
        <p className="text-xs text-slate-500">No history recorded yet.</p>
      ) : (
        <div className="divide-y divide-slate-100">
          {versions.map((v) => (
            <div key={v.version} className="py-2">
              <button
                type="button"
                className="w-full text-left flex items-start gap-3"
                onClick={() => setOpen(open === v.version ? null : v.version)}
              >
                <Badge tone="blue">v{v.version}</Badge>
                <span className="min-w-0 flex-1">
                  <span className="block text-sm text-slate-800">
                    {v.note || 'No note'}
                  </span>
                  <span className="block text-xs text-slate-500">
                    {relativeTime(v.created_at)}
                    {v.created_by ? ` by ${v.created_by}` : ''}
                  </span>
                </span>
                <span className="text-xs text-slate-400 shrink-0">
                  {open === v.version ? 'hide' : 'show'}
                </span>
              </button>
              {open === v.version && (
                <pre className="mono text-xs bg-code-bg text-code-fg rounded-md p-3
                                mt-2 overflow-x-auto">{v.sql_text}</pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
