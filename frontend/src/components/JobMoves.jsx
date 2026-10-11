import { useState } from 'react'
import { api } from '../lib/api'
import { relativeTime } from '../lib/format'
import { Copyable, Step } from './AddClusterGuide'
import { Alert } from './ui'

const DOCS = 'https://github.com/DevinMB/mars/blob/main/docs/deployment.md#job-moves-between-clusters'

// "Job moves" is optional: a job stopping on one cluster and resuming on another
// with its state. It needs both clusters to keep savepoints in one shared place,
// which MARS cannot set up itself (the console has no access to Docker), so it
// guides, then checks. The state comes from that check, not from a stored switch.

const LOOK = {
  off: { dot: 'bg-slate-300', text: 'Not set up' },
  ready: { dot: 'bg-emerald-500', text: 'Ready' },
  broken: { dot: 'bg-red-500', text: 'Not working' },
}

/** The one line on a cluster's card. */
export function JobMovesLine({ moves, canManage, onOpen }) {
  if (!moves) return null
  const look = LOOK[moves.state] || LOOK.off
  return (
    <div className="mt-3 pt-3 border-t border-slate-100 text-[12px]">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className={`w-2 h-2 rounded-full ${look.dot}`} />
        <span className="text-slate-500">Job moves:</span>
        <span className={moves.state === 'broken' ? 'text-red-700' : 'text-slate-800'}>{look.text}</span>
        {moves.state === 'ready' && moves.checked_at && (
          <span className="text-slate-400">checked {relativeTime(moves.checked_at)}</span>
        )}
        {canManage && (
          <span className="ml-auto flex gap-3">
            {moves.state === 'off' && <button type="button" className="link" onClick={() => onOpen('setup')}>Set up</button>}
            {moves.state === 'broken' && <button type="button" className="link" onClick={() => onOpen('setup')}>Details</button>}
            {moves.state === 'ready' && <button type="button" className="link" onClick={() => onOpen('check')}>Check</button>}
            {moves.state !== 'off' && (
              <button type="button" className="text-slate-400 hover:text-red-600" onClick={() => onOpen('off')}>Turn off</button>
            )}
          </span>
        )}
      </div>
      {moves.state === 'broken' && <p className="text-red-700 mt-1">{moves.summary}</p>}
    </div>
  )
}

function CheckStep({ pair, onDone }) {
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const run = async () => {
    setRunning(true); setError(null)
    try {
      const r = await api.checkSavepointStorage(...pair)
      setResult(r)
      if (r.shared) onDone()
    } catch (err) { setError(err.message) } finally { setRunning(false) }
  }
  return (
    <div className="space-y-2">
      <button type="button" className="btn-primary" disabled={running} onClick={run}>
        {running ? 'Checking…' : 'Check'}
      </button>
      <p className="text-[12px] text-slate-500">
        {running
          ? 'A small job writes on each cluster and reads on the other. About half a minute.'
          : 'Proves both clusters see the same files. Needs one free slot on each for a few seconds.'}
      </p>
      {error && <Alert level="danger">{error}</Alert>}
      {result && (
        <Alert level={result.shared ? 'success' : 'warning'}>{result.summary}</Alert>
      )}
    </div>
  )
}

function SetupGuide({ moves, locations, sameMachine, onDone }) {
  const [server, setServer] = useState('')
  const [exportPath, setExportPath] = useState('')
  const [files, setFiles] = useState(null)
  const [machine, setMachine] = useState('mars')
  const [withSecond, setWithSecond] = useState(sameMachine)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const pair = [moves.default, moves.cluster]

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
    <>
      <p className="text-[13px] text-slate-600 max-w-3xl">
        Optional. Lets a job stop on one cluster and resume on the other where it left
        off, which is also how a cluster can be upgraded without stopping everything.
        Both clusters keep savepoints in one shared folder; checkpoints stay on each
        cluster's own disk. <a className="link" href={DOCS} target="_blank" rel="noreferrer">More</a>
      </p>
      {moves.state === 'broken' && <div className="mt-3"><Alert level="danger">{moves.summary}</Alert></div>}
      <dl className="mt-3 grid gap-x-6 gap-y-1 sm:grid-cols-[auto_1fr] text-[12px]">
        {pair.map((name) => {
          const loc = locations.find((l) => l.name === name)
          return (
            <div key={name} className="contents">
              <dt className="mono text-slate-800">{name} saves to</dt>
              <dd className={`min-w-0 break-all ${loc?.error ? 'text-red-700' : 'mono text-slate-600'}`}>
                {loc?.error || loc?.savepoint_dir || '—'}
              </dd>
            </div>
          )
        })}
      </dl>
      {error && <div className="mt-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
      <ol className="space-y-4 mt-4">
        <Step n={1} title="Create a shared folder both machines can reach">
          <p className="text-[12px] text-slate-600">
            An NFS share on a NAS or file server, allowing each machine that runs one of
            these clusters (by IP address). A few gigabytes is plenty: MARS keeps only the
            newest savepoints of each job. S3 or MinIO instead? See the{' '}
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
            Not sure of the export path? <code className="mono">showmount -e &lt;NFS server&gt;</code> lists it.
          </p>
        </Step>
        {files && (
          <>
            <Step n={3} title="Stop the jobs on each cluster you are changing, with their state saved">
              <p className="text-[12px] text-slate-600">
                Applying the file restarts that cluster. Savepoints taken before stay where they
                are and still work for resuming on the same cluster. A cluster that already
                saves to the shared folder needs nothing.
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
            </Step>
          </>
        )}
        <Step n={files ? 6 : 3} title="Check it">
          <CheckStep pair={pair} onDone={onDone} />
        </Step>
      </ol>
    </>
  )
}

function OffGuide({ moves, jobCount, onDone }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const off = async () => {
    setBusy(true); setError(null)
    try { await api.jobMovesOff(moves.cluster); onDone() }
    catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  return (
    <>
      <p className="text-[13px] text-slate-600 max-w-3xl">
        {moves.default} can keep using the shared folder; this only stops {moves.cluster} from
        using it. Jobs then cannot move between the two with their state.
      </p>
      <ol className="space-y-4 mt-4">
        <Step n={1} title={`Move ${moves.cluster}'s jobs to ${moves.default} first`}>
          <p className="text-[12px] text-slate-600">
            {jobCount
              ? `${jobCount} job${jobCount === 1 ? '' : 's'} run${jobCount === 1 ? 's' : ''} there. For each: stop it with state saved, set Runs on to ${moves.default}, and resume. Their savepoints are on the shared folder, which ${moves.cluster} will no longer reach.`
              : 'None run there, so there is nothing to move.'}
          </p>
        </Step>
        <Step n={2} title={`On ${moves.cluster}'s machine, delete docker-compose.override.yml and restart the cluster`}>
          <Copyable>docker compose up -d jobmanager taskmanager</Copyable>
          <p className="text-[12px] text-slate-500">
            On the MARS machine's second cluster, remove its services from the override file
            instead, and restart jobmanager-b taskmanager-b.
          </p>
        </Step>
        <Step n={3} title="Turn job moves off">
          <button type="button" className="btn-secondary" disabled={busy} onClick={off}>
            {busy ? 'Turning off…' : `Turn off for ${moves.cluster}`}
          </button>
          {error && <Alert level="danger">{error}</Alert>}
        </Step>
      </ol>
    </>
  )
}

/** The guide for one cluster, opened from its card. */
export function JobMovesGuide({ mode, moves, locations, target, onClose, onChanged }) {
  const titles = {
    setup: `Set up job moves between ${moves.default} and ${moves.cluster}`,
    check: `Check job moves between ${moves.default} and ${moves.cluster}`,
    off: `Turn off job moves for ${moves.cluster}`,
  }
  const done = () => { onChanged(); onClose() }
  return (
    <div className="card p-5 mb-8">
      <div className="flex items-start justify-between gap-3 mb-3">
        <h3 className="text-[15px] font-medium text-slate-900">{titles[mode]}</h3>
        <button type="button" className="text-[12px] text-slate-500 hover:text-slate-800" onClick={onClose}>Close</button>
      </div>
      {mode === 'off' && <OffGuide moves={moves} jobCount={target?.job_count || 0} onDone={done} />}
      {mode === 'check' && <CheckStep pair={[moves.default, moves.cluster]} onDone={onChanged} />}
      {mode === 'setup' && (
        <SetupGuide moves={moves} locations={locations} onDone={done}
                    sameMachine={/jobmanager-b/.test(target?.flink_rest_url || '')} />
      )}
    </div>
  )
}
