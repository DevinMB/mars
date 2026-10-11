import { useEffect, useRef, useState } from 'react'
import { copyText, selectContents } from '../lib/clipboard'

// Where the project lives. Change this in a fork; it is the only place the
// repository is named.
const REPO = 'https://github.com/DevinMB/mars'
const REMOTE_README = `${REPO}/tree/main/remote-target#readme`

function Copyable({ children, tall = false }) {
  // '', 'copied', or 'manual' when the browser refused and the text is selected.
  const [status, setStatus] = useState('')
  const pre = useRef(null)
  const text = String(children).trim()
  return (
    <div className="relative">
      <pre ref={pre} className={`mono text-[11.5px] bg-code-bg text-code-fg rounded-md p-3 pr-16
                       overflow-auto leading-relaxed ${tall ? 'max-h-72' : ''}`}>{text}</pre>
      <button
        type="button"
        onClick={async () => {
          const ok = await copyText(text)
          if (!ok) selectContents(pre.current)
          setStatus(ok ? 'copied' : 'manual')
          setTimeout(() => setStatus(''), ok ? 1500 : 4000)
        }}
        className="absolute top-2 right-2 text-[11px] px-1.5 py-0.5 rounded-sm
                   bg-slate-700/70 text-slate-200 hover:bg-slate-600 transition-colors"
      >
        {status === 'copied' ? 'copied' : status === 'manual' ? 'press Ctrl+C' : 'copy'}
      </button>
    </div>
  )
}

function Step({ n, title, children }) {
  return (
    <li className="grid grid-cols-[1.5rem_1fr] gap-2">
      <span className="mt-0.5 w-5 h-5 rounded-full bg-accent-50 text-accent-700 text-[11px]
                       font-semibold flex items-center justify-center tabular-nums">{n}</span>
      <div className="min-w-0 space-y-2">
        <div className="text-[13px] font-medium text-slate-800">{title}</div>
        {children}
      </div>
    </li>
  )
}

function Choice({ selected, onClick, title, detail }) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`text-left rounded-lg border p-3 transition-colors ${
        selected
          ? 'border-accent-400 bg-accent-50'
          : 'border-slate-200 bg-surface hover:border-slate-300'
      }`}
    >
      <div className="flex items-center gap-2">
        <span className={`w-3.5 h-3.5 rounded-full border-2 ${
          selected ? 'border-accent-600 bg-accent-600' : 'border-slate-300'}`} />
        <span className="text-[13px] font-medium text-slate-900">{title}</span>
      </div>
      <p className="text-[12px] text-slate-500 mt-1 ml-5.5">{detail}</p>
    </button>
  )
}

const ADDRESS = /^[A-Za-z0-9.-]+$/

/**
 * The first half of adding a cluster: getting one running.
 *
 * The form below only asks for two addresses, which is easy if a cluster already
 * exists and baffling if it does not. So this starts from the question people
 * can answer, where it will run, and ends by filling the form in.
 *
 * Both paths run the exact Flink image the default cluster runs, so the clusters
 * agree on connectors.
 */
export default function AddClusterGuide({ setup, onUse, onSlots }) {
  const [where, setWhereState] = useState(null)
  // Switching places clears the form: values filled in for the other choice
  // would otherwise add the wrong cluster without anyone noticing.
  const setWhere = (next) => {
    if (where && next !== where) onUse({})
    setWhereState(next)
  }
  const [address, setAddress] = useState('')
  const [jobs, setJobs] = useState('8')
  const slots = Number(jobs)
  const slotsOk = Number.isInteger(slots) && slots >= 1 && slots <= 64
  // The compose file carries the slot count, so ask for it again once typing pauses.
  useEffect(() => {
    if (!slotsOk) return
    const t = setTimeout(() => onSlots?.(slots), 300)
    return () => clearTimeout(t)
  }, [slots, slotsOk]) // eslint-disable-line react-hooks/exhaustive-deps
  const host = address.trim()
  const hostOk = ADDRESS.test(host)
  const shown = hostOk ? host : '<address>'

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/60 p-4 mb-5">
      <h3 className="text-[14px] font-medium text-slate-900">Where will the new cluster run?</h3>
      <div className="grid gap-2 sm:grid-cols-2 mt-3">
        <Choice
          selected={where === 'here'}
          onClick={() => setWhere('here')}
          title="On this machine"
          detail="Next to MARS. One command; nothing to copy."
        />
        <Choice
          selected={where === 'other'}
          onClick={() => setWhere('other')}
          title="On another machine"
          detail="Separate hardware. Copy one file, run one command."
        />
      </div>

      {where && (
        <p className="text-[12px] text-slate-500 mt-3">
          It runs the same Flink image as your default cluster, so both have the same
          connectors: <code className="mono text-[11px] break-all">{setup.flink_image}</code>
        </p>
      )}

      {where === 'here' && (
        <ol className="space-y-4 mt-4">
          {setup.same_machine_registered && (
            <li className="text-[12px] text-amber-800 bg-amber-50 border border-amber-200 rounded-md px-3 py-2">
              A cluster at <code className="mono">{setup.same_machine_rest_url}</code> is
              already added. This machine has room for one more cluster this way.
            </li>
          )}
          <Step n={1} title="On the MARS machine, start the second cluster">
            <p className="text-[12px] text-slate-600">
              Run this in the folder that holds MARS's <code className="mono">docker-compose.yml</code>.
              It starts <code className="mono">{setup.same_machine_name}</code>, a Flink cluster
              with 4 task slots on MARS's internal network. No ports are opened.
            </p>
            <Copyable>{setup.same_machine_command}</Copyable>
            <p className="text-[12px] text-slate-500">It takes about a minute to start.</p>
          </Step>
          <Step n={2} title="Fill in the form and test the connection">
            <button
              type="button"
              className="btn-primary"
              onClick={() => onUse({
                name: setup.same_machine_name,
                description: 'Second cluster on the MARS machine',
                flink_rest_url: setup.same_machine_rest_url,
                gateway_url: setup.same_machine_gateway_url,
                ui_url: '',
              })}
            >
              Use these settings
            </button>
          </Step>
        </ol>
      )}

      {where === 'other' && (
        <ol className="space-y-4 mt-4">
          <Step n={1} title="Check the new machine">
            <ul className="text-[12px] text-slate-600 list-disc ml-4 space-y-1">
              <li>Docker with Compose 2.23 or newer.</li>
              <li>
                Ports 8081 and 8083 reachable from this MARS machine. Neither is
                authenticated, so keep them on a trusted network.
              </li>
              <li>
                Its own network access to whatever its jobs read and write: Kafka,
                databases, APIs.
              </li>
            </ul>
          </Step>
          <Step n={2} title="Enter the new machine's IP address">
            <p className="text-[12px] text-slate-600">
              The new machine's own address, not this MARS machine's. Run{' '}
              <code className="mono">hostname -I</code> on the new machine to see it.
            </p>
            <input
              className="input mono max-w-xs"
              value={address}
              placeholder="192.168.1.60"
              aria-label="Address of the new machine"
              onChange={(e) => setAddress(e.target.value)}
            />
            {host && !hostOk && (
              <p className="text-[12px] text-red-700">A hostname or IP address, without http:// or a port.</p>
            )}
          </Step>
          <Step n={3} title="How many jobs will it run?">
            <input
              className="input max-w-[8rem] tabular-nums"
              type="number"
              min="1"
              max="64"
              value={jobs}
              aria-label="Jobs this cluster will run"
              onChange={(e) => setJobs(e.target.value)}
            />
            <p className="text-[12px] text-slate-500">
              {slotsOk
                ? `${slots} task slot${slots === 1 ? '' : 's'}: one per job.`
                : 'A number from 1 to 64.'}
              {slotsOk && slots > 16 &&
                ' Light jobs use about 150 MB each; above 16, raise the TaskManager memory in the file to match.'}
            </p>
          </Step>
          <Step n={4} title="On the new machine, save this as docker-compose.yml in an empty folder">
            <Copyable tall>{setup.other_machine_compose}</Copyable>
          </Step>
          {setup.registry && (
            <Step n={5} title={`Let it pull the image from ${setup.registry}`}>
              <p className="text-[12px] text-slate-600">
                Needed when the image is private. Log in with a token that can read packages.
              </p>
              <Copyable>{`docker login ${setup.registry}`}</Copyable>
            </Step>
          )}
          <Step n={setup.registry ? 6 : 5} title="Start it">
            <Copyable>{`TARGET_BIND_ADDRESS=${shown} docker compose up -d`}</Copyable>
          </Step>
          <Step n={setup.registry ? 7 : 6} title="Fill in the form and test the connection">
            <div className="flex items-center gap-3 flex-wrap">
              <button
                type="button"
                className="btn-primary"
                disabled={!hostOk}
                onClick={() => onUse({
                  name: '',
                  description: '',
                  flink_rest_url: `http://${host}:8081`,
                  gateway_url: `http://${host}:8083`,
                  ui_url: `http://${host}:8081`,
                })}
              >
                Use these settings
              </button>
              <a className="link text-[12px]" href={REMOTE_README} target="_blank" rel="noreferrer">
                Full guide: remote-target on GitHub
              </a>
            </div>
          </Step>
        </ol>
      )}
    </div>
  )
}
