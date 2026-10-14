import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { ComponentUpdate, componentsBehind, short } from '../components/UpdateDetails'
import { Alert, PageHeader, Spinner } from '../components/ui'

function Row({ label, children }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 py-2 border-b border-slate-100 last:border-0 text-[13px]">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-800 min-w-0 [overflow-wrap:anywhere]">{children}</dd>
    </div>
  )
}

// ghcr.io/x/mars-flink@sha256:abcdef0123456789... -> ghcr.io/x/mars-flink@sha256:abcdef012345
const shortImage = (image) => image.replace(/@sha256:([0-9a-f]{12})[0-9a-f]+$/, '@sha256:$1…')

const unknown = <span className="text-slate-400">not recorded</span>

export default function Version() {
  const [v, setV] = useState(null)
  const [error, setError] = useState(null)
  const [checking, setChecking] = useState(false)

  useEffect(() => { api.version().then(setV).catch((e) => setError(e.message)) }, [])

  if (error && !v) return <Alert level="danger" title="Could not load version">{error}</Alert>
  if (!v) return <Spinner label="Reading version" />

  const check = v.update_check
  const behind = componentsBehind(v)

  return (
    <>
      <PageHeader title="Version & updates" subtitle="What this installation runs, and whether a newer release exists." />
      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="card p-5 mb-5">
        <h2 className="eyebrow-accent mb-2">Running</h2>
        <dl>
          <Row label="Console">
            {v.console.revision ? <span className="mono">{short(v.console.revision)}</span> : unknown}
            {v.console.built_at && <span className="text-slate-500"> · built {relativeTime(v.console.built_at)}</span>}
          </Row>
          <Row label="Flink">
            {v.flink.revision ? <span className="mono">{short(v.flink.revision)}</span>
              : v.flink.image ? <span className="mono text-[12px]" title={v.flink.image}>{shortImage(v.flink.image)}</span> : unknown}
          </Row>
        </dl>
      </div>

      <div className="card p-5 mb-5">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-2">
          <h2 className="eyebrow-accent">Update checks</h2>
          {check.enabled && (
            <button className="btn-secondary" disabled={checking} onClick={async () => {
              setChecking(true); setError(null)
              try { setV(await api.checkForUpdates()) } catch (e) { setError(e.message) } finally { setChecking(false) }
            }}>{checking ? 'Checking…' : 'Check now'}</button>
          )}
        </div>
        {check.enabled ? (
          <dl>
            <Row label="Following">{check.channel === 'main' ? 'Every change merged to main' : 'Tagged releases'}</Row>
            <Row label="Last checked">{check.checked_at ? relativeTime(check.checked_at) : 'not yet'}</Row>
            <Row label="Newest">
              {v.latest ? <a className="link" href={v.latest.url} target="_blank" rel="noreferrer">{v.latest.label}</a> : '—'}
            </Row>
            {check.error && <Row label="Problem"><span className="text-red-700">{check.error}</span></Row>}
          </dl>
        ) : (
          <div className="text-[13px] text-slate-600 space-y-2">
            <p>Off. Checking asks GitHub once a day what the newest release is, which is an outbound request from your network, so it is opt-in.</p>
            <p>To turn it on, set <code className="mono">MARS_UPDATE_CHECK=true</code> for the console. For a private repository, store a read-only GitHub token as a secret and name it in <code className="mono">MARS_UPDATE_TOKEN_SECRET</code>.</p>
          </div>
        )}
      </div>

      {check.enabled && v.latest && (
        behind.length > 0 ? (
          <div className="card p-5 grid gap-8 md:grid-cols-2">
            {behind.map((c) => <ComponentUpdate key={c} name={c} data={v[c]} latest={v.latest} />)}
          </div>
        ) : (
          <Alert level="success">Up to date with {v.latest.label}.</Alert>
        )
      )}
    </>
  )
}
