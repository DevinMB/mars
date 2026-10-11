import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { Copyable, Step } from './AddClusterGuide'
import { Alert } from './ui'

const DOCS = 'https://github.com/DevinMB/mars/blob/main/docs/deployment.md#shared-savepoint-storage'

function PairStatus({ pair, check, canManage, running, onCheck }) {
  const [a, b] = pair
  const tone = running ? 'bg-slate-300 animate-pulse'
    : !check ? 'bg-slate-300' : check.shared ? 'bg-emerald-500' : 'bg-amber-500'
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5 first:pt-0 last:pb-0">
      <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${tone}`} />
      <div className="min-w-0 flex-1">
        <div className="text-[13px] text-slate-900">
          <span className="mono">{a}</span> and <span className="mono">{b}</span>
        </div>
        <div className="text-[12px] text-slate-600 mt-0.5">
          {running
            ? 'Checking: a small job writes on each cluster and reads on the other. About half a minute.'
            : check
              ? <>{check.summary} <span className="text-slate-400">Checked {relativeTime(check.checked_at)}.</span></>
              : 'Not checked yet. Until it is, moving a job between them is not safe.'}
        </div>
      </div>
      {canManage && (
        <button type="button" className="btn-secondary text-[12px] py-1!" disabled={running} onClick={onCheck}>
          {running ? 'Checking…' : check ? 'Check again' : 'Check'}
        </button>
      )}
    </li>
  )
}

function SetupSteps({ setError }) {
  const [server, setServer] = useState('')
  const [exportPath, setExportPath] = useState('')
  const [files, setFiles] = useState(null)
  const [machine, setMachine] = useState('mars')
  const [withSecond, setWithSecond] = useState(false)
  const [busy, setBusy] = useState(false)

  const generate = async (e) => {
    e.preventDefault()
    setBusy(true)
    try { setFiles(await api.savepointStorageSetup(server.trim(), exportPath.trim())); setError(null) }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const file = !files ? null
    : machine === 'other' ? files.other_machine
      : withSecond ? files.this_machine_with_second : files.this_machine

  return (
    <ol className="space-y-4 mt-4">
      <Step n={1} title="Create a shared folder every cluster's machine can reach">
        <p className="text-[12px] text-slate-600">
          An NFS share on a NAS or file server, allowing each machine that runs a cluster
          (by its IP address). A few gigabytes is plenty: MARS keeps only the newest
          savepoints of each job. Using S3 or MinIO instead? See the{' '}
          <a className="link" href={DOCS} target="_blank" rel="noreferrer">deployment guide</a>.
        </p>
      </Step>
      <Step n={2} title="Enter where it is">
        <form className="flex flex-wrap gap-2 items-center" onSubmit={generate}>
          <input className="input w-48" aria-label="NFS server" placeholder="NFS server, e.g. 192.168.1.10"
                 value={server} onChange={(e) => setServer(e.target.value)} />
          <input className="input flex-1 min-w-56" aria-label="Export path" placeholder="Export path, e.g. /volume1/flink-savepoints"
                 value={exportPath} onChange={(e) => setExportPath(e.target.value)} />
          <button className="btn-secondary" disabled={!server.trim() || !exportPath.trim() || busy}>
            {busy ? 'Generating…' : 'Generate'}
          </button>
        </form>
        <p className="text-[11px] text-slate-500">
          Not sure of the export path? On any of the machines,{' '}
          <code className="mono">showmount -e &lt;NFS server&gt;</code> lists it.
        </p>
      </Step>
      {files && (
        <>
          <Step n={3} title="Stop the jobs on each cluster you are changing, with their state saved">
            <p className="text-[12px] text-slate-600">
              Applying the file restarts that cluster. Savepoints taken before the change stay
              where they are and still work for resuming on the same cluster.
            </p>
          </Step>
          <Step n={4} title="On each machine, save this as docker-compose.override.yml next to docker-compose.yml">
            <div className="flex flex-wrap gap-2 text-[12px]">
              {[['mars', 'The MARS machine'], ['other', 'Another machine']].map(([key, label]) => (
                <button key={key} type="button" aria-pressed={machine === key} onClick={() => setMachine(key)}
                        className={`px-2.5 py-1 rounded-md border ${machine === key
                          ? 'border-accent-400 bg-accent-50 text-slate-900' : 'border-slate-200 text-slate-600'}`}>
                  {label}
                </button>
              ))}
              {machine === 'mars' && (
                <label className="flex items-center gap-1.5 text-slate-600 ml-1">
                  <input type="checkbox" checked={withSecond} onChange={(e) => setWithSecond(e.target.checked)} />
                  It also runs the second cluster (the second-target profile)
                </label>
              )}
            </div>
            <Copyable tall>{file}</Copyable>
          </Step>
          <Step n={5} title="Apply it, then resume the jobs">
            <Copyable>{file.match(/docker compose up -d .*/)?.[0] || 'docker compose up -d'}</Copyable>
            <p className="text-[12px] text-slate-600">
              Then press <b>Check</b> above. When it passes, jobs can move between the clusters.
            </p>
          </Step>
        </>
      )}
    </ol>
  )
}

/**
 * Where each cluster keeps savepoints, and whether two clusters provably share it.
 * Moving a job is a savepoint on one cluster and a resume on the other, so this is
 * what makes moving jobs, and upgrading one cluster at a time, possible.
 */
export default function SavepointStorage({ canManage, refreshKey }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(null)
  const [open, setOpen] = useState(false)

  const load = () => api.savepointStorage().then((d) => { setData(d); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [refreshKey])

  if (!data) return error ? <Alert level="danger" title="Could not read savepoint storage">{error}</Alert> : null

  const def = data.clusters.find((c) => c.is_default)
  const pairs = def ? data.clusters.filter((c) => !c.is_default).map((c) => [def.name, c.name]) : []
  const checkOf = (pair) => data.checks.find((c) => c.clusters.length === 2 && pair.every((n) => c.clusters.includes(n)))
  const allShared = pairs.length > 0 && pairs.every((p) => checkOf(p)?.shared)

  const check = async (pair) => {
    setRunning(pair.join('|'))
    try { await api.checkSavepointStorage(...pair); await load() } catch (err) { setError(err.message) }
    finally { setRunning(null) }
  }

  return (
    <div className="card p-5 mb-8">
      <p className="text-[13px] text-slate-600 max-w-3xl">
        A job moves to another cluster by stopping with a savepoint on one and resuming
        from it on the other, so both clusters must keep savepoints in the same, shared
        place. The same folder name on two machines is not enough; <b>Check</b> proves it.
      </p>
      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <dl className="mt-4 grid gap-x-6 gap-y-2 sm:grid-cols-[auto_1fr] text-[12px]">
        {data.clusters.map((c) => (
          <div key={c.name} className="contents">
            <dt className="mono text-slate-800">{c.name}</dt>
            <dd className={`min-w-0 break-all ${c.error ? 'text-red-700' : 'mono text-slate-600'}`}>
              {c.error || c.savepoint_dir}
            </dd>
          </div>
        ))}
      </dl>

      {pairs.length > 0 ? (
        <ul className="mt-4 pt-4 border-t border-slate-200 divide-y divide-slate-100">
          {pairs.map((pair) => (
            <PairStatus key={pair.join('|')} pair={pair} check={checkOf(pair)} canManage={canManage}
                        running={running === pair.join('|')} onCheck={() => check(pair)} />
          ))}
        </ul>
      ) : (
        <p className="mt-4 text-[12px] text-slate-500">Add a second cluster to move jobs between them.</p>
      )}

      {canManage && pairs.length > 0 && !allShared && (
        <div className="mt-4 pt-4 border-t border-slate-200">
          <button type="button" className="link text-[13px]" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Hide' : 'How to share savepoint storage'}
          </button>
          {open && <SetupSteps setError={setError} />}
        </div>
      )}
    </div>
  )
}
