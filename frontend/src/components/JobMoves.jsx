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
        <Alert level={result.shared ? 'success' : 'warning'} title={result.shared ? 'Ready' : 'Not shared yet'}>
          {result.summary}
        </Alert>
      )}
    </div>
  )
}

// Where a cluster runs, in the words someone setting it up would use.
const SHARED_DIR = 'file:///flink-savepoints'
function hostOf(target) {
  try { return new URL(target.flink_rest_url).hostname } catch { return '' }
}
function placeOf(target) {
  const host = hostOf(target)
  if (target.is_default || host === 'jobmanager') return { label: 'the MARS machine', file: 'mars' }
  if (host === 'jobmanager-b') return { label: 'the MARS machine (its second cluster)', file: 'second' }
  return { label: `the machine at ${host}`, file: 'other', host }
}

function ShareChooser({ hosts, onChosen }) {
  const [server, setServer] = useState('')
  const [shares, setShares] = useState(null)
  const [manual, setManual] = useState(false)
  const [path, setPath] = useState('')
  const [chosen, setChosen] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const find = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null); setShares(null); setChosen('')
    try {
      const found = await api.nfsExports(server.trim())
      // Shares that already allow the cluster machines first.
      const allows = (s) => hosts.filter((h) => s.clients.length === 0 || s.clients.includes(h)).length
      setShares([...found].sort((a, b) => allows(b) - allows(a) || a.name.localeCompare(b.name)))
      if (!found.length) setManual(true)
    } catch (err) { setError(err.message); setManual(true) } finally { setBusy(false) }
  }
  const choose = async (exportPath) => {
    setChosen(exportPath); setError(null)
    try { onChosen(await api.savepointStorageSetup(server.trim(), exportPath)) }
    catch (err) { setError(err.message); onChosen(null) }
  }

  return (
    <div className="space-y-2">
      <form className="flex flex-wrap gap-2 items-center" onSubmit={find}>
        <input className="input w-56" aria-label="NFS server" placeholder="NAS address, e.g. 192.168.1.10"
               value={server} onChange={(e) => setServer(e.target.value)} />
        <button className="btn-secondary" disabled={!server.trim() || busy}>{busy ? 'Looking…' : 'Find shared folders'}</button>
      </form>
      {error && <p className="text-[12px] text-red-700">{error}</p>}
      {shares && shares.length > 0 && (
        <fieldset className="space-y-1.5">
          <legend className="text-[12px] text-slate-500 mb-1">Folders {server.trim()} shares. Pick the one you created:</legend>
          {shares.map((s) => {
            const missing = hosts.filter((h) => s.clients.length && !s.clients.includes(h))
            return (
              <label key={s.path} className={`flex items-start gap-2 rounded-md border px-3 py-2 cursor-pointer ${
                chosen === s.path ? 'border-accent-400 bg-accent-50' : 'border-slate-200 hover:border-slate-300'}`}>
                <input type="radio" name="share" className="mt-1" checked={chosen === s.path} onChange={() => choose(s.path)} />
                <span className="min-w-0">
                  <span className="block text-[13px] text-slate-900">{s.name}</span>
                  <span className="block text-[11px] text-slate-500">
                    {s.clients.length ? `Allows ${s.clients.join(', ')}` : 'Allows any machine'}
                    {missing.length > 0 && <span className="text-amber-700"> · not {missing.join(', ')}</span>}
                  </span>
                </span>
              </label>
            )
          })}
        </fieldset>
      )}
      {(manual || shares) && (
        <div className="text-[12px]">
          {!manual ? (
            <button type="button" className="link" onClick={() => setManual(true)}>Enter the folder's path instead</button>
          ) : (
            <form className="flex flex-wrap gap-2 items-center" onSubmit={(e) => { e.preventDefault(); choose(path.trim()) }}>
              <input className="input flex-1 min-w-56" aria-label="Export path" placeholder="Export path, e.g. /volume1/flink-savepoints"
                     value={path} onChange={(e) => setPath(e.target.value)} />
              <button className="btn-secondary" disabled={!path.trim()}>Use this path</button>
            </form>
          )}
        </div>
      )}
    </div>
  )
}

function ClusterTodo({ target, location, files }) {
  const place = placeOf(target)
  if (location?.savepoint_dir === SHARED_DIR) {
    return (
      <div className="rounded-md border border-slate-200 px-3 py-2 text-[13px]">
        <span className="text-emerald-600">✓</span> <span className="mono">{target.name}</span>
        <span className="text-slate-600"> already saves to a shared folder. Nothing to do here.</span>
      </div>
    )
  }
  const file = files && (place.file === 'other' ? files.other_machine
    : place.file === 'second' ? files.this_machine_with_second : files.this_machine)
  const jobs = target.job_count || 0
  return (
    <div className="rounded-md border border-slate-200 px-3 py-3 space-y-2">
      <div className="text-[13px]">
        <span className="mono text-slate-900">{target.name}</span>
        <span className="text-slate-600"> runs on {place.label} and saves to its own disk.</span>
      </div>
      {!file ? (
        <p className="text-[12px] text-slate-500">Choose the shared folder above to see what to do here.</p>
      ) : (
        <ol className="list-decimal pl-5 space-y-2 text-[12px] text-slate-700">
          {jobs > 0 && <li>Stop its {jobs} job{jobs === 1 ? '' : 's'} with their state saved.</li>}
          <li>
            On {place.label}, in the folder with its <code className="mono">docker-compose.yml</code>,
            save this as <code className="mono">docker-compose.override.yml</code>:
            {place.file === 'second' && ' (it also covers the main cluster on that machine; if that machine already has this file, replace it).'}
            <div className="mt-1.5"><Copyable tall>{file}</Copyable></div>
          </li>
          <li>
            Restart the cluster with it:
            <div className="mt-1.5"><Copyable>{file.match(/docker compose up -d .*/)?.[0] || 'docker compose up -d'}</Copyable></div>
            {place.file === 'other' && (
              <span className="text-slate-500">Put <code className="mono">TARGET_BIND_ADDRESS=…</code> in front if you start it that way.</span>
            )}
          </li>
          {jobs > 0 && <li>Resume the jobs.</li>}
        </ol>
      )}
    </div>
  )
}

function SetupGuide({ moves, locations, targets, onDone }) {
  const [files, setFiles] = useState(null)
  const pair = [moves.default, moves.cluster]
  const pairTargets = pair.map((n) => targets.find((t) => t.name === n)).filter(Boolean)
  // Addresses the share must allow; the MARS machine's own is not known here.
  const hosts = pairTargets.map(placeOf).filter((p) => p.host).map((p) => p.host)
  const todo = pairTargets.filter((t) => locations.find((l) => l.name === t.name)?.savepoint_dir !== SHARED_DIR)

  return (
    <>
      <p className="text-[13px] text-slate-600 max-w-3xl">
        Optional. Lets a job stop on one cluster and carry on from the same place on the
        other, which is also how a cluster can be upgraded without stopping everything.
        For that, both clusters keep their savepoints in one shared folder on your network.{' '}
        <a className="link" href={DOCS} target="_blank" rel="noreferrer">More</a>
      </p>
      {moves.state === 'broken' && <div className="mt-3"><Alert level="danger">{moves.summary}</Alert></div>}
      <ol className="space-y-5 mt-4">
        <Step n={1} title="Create a shared folder on your NAS or file server">
          <p className="text-[12px] text-slate-600">
            Share it over NFS and allow {hosts.length ? <>the MARS machine and {hosts.join(', ')}</> : 'the machines these clusters run on'}.
            A few gigabytes is plenty. Using S3 or MinIO instead? See the{' '}
            <a className="link" href={DOCS} target="_blank" rel="noreferrer">deployment guide</a>.
          </p>
        </Step>
        <Step n={2} title="Choose it">
          <ShareChooser hosts={hosts} onChosen={setFiles} />
        </Step>
        <Step n={3} title={todo.length ? 'Point each cluster at it' : 'Point each cluster at it (done)'}>
          <div className="space-y-2">
            {pairTargets.map((t) => (
              <ClusterTodo key={t.name} target={t} location={locations.find((l) => l.name === t.name)} files={files} />
            ))}
          </div>
        </Step>
        <Step n={4} title="Check that both clusters see the same folder">
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
export function JobMovesGuide({ mode, moves, locations, targets, onClose, onChanged }) {
  const target = targets.find((t) => t.name === moves.cluster)
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
        <SetupGuide moves={moves} locations={locations} targets={targets} onDone={done} />
      )}
    </div>
  )
}
