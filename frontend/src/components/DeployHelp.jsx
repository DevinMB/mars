import { useState } from 'react'

// Where the project lives. Change this in a fork; it is the only place the
// repository is named.
const REPO = 'https://github.com/DevinMB/mars'
const REMOTE_DIR = `${REPO}/tree/main/remote-target`

function Copyable({ children }) {
  const [copied, setCopied] = useState(false)
  const text = String(children).trim()
  return (
    <div className="relative group">
      <pre className="mono text-[11.5px] bg-code-bg text-code-fg rounded-md p-3 pr-16
                      overflow-x-auto leading-relaxed">{text}</pre>
      <button
        type="button"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          } catch {
            // Clipboard is unavailable outside a secure context; the text is
            // selectable either way, so say nothing rather than throw.
            setCopied(false)
          }
        }}
        className="absolute top-2 right-2 text-[11px] px-1.5 py-0.5 rounded-sm
                   bg-slate-700/70 text-slate-200 hover:bg-slate-600 transition-colors"
      >
        {copied ? 'copied' : 'copy'}
      </button>
    </div>
  )
}

/**
 * Explains where the two URLs on this form come from.
 *
 * The form asks for a REST url and a gateway url, which is only obvious if you
 * already have a cluster to point at. Someone adding their first target does not,
 * and the useful answer is three commands rather than a paragraph.
 *
 * Opens by default while there is only one target, because that is the case where
 * the reader has never done this before.
 */
export default function DeployHelp({ defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className="rounded-md border border-slate-200 bg-slate-50/60 mb-4">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 text-left"
      >
        <span className="text-[13px] font-medium text-slate-700">
          Don’t have a cluster to point at yet?
        </span>
        <span className="text-[11px] text-slate-500">{open ? 'hide' : 'show me how'}</span>
      </button>

      {open && (
        <div className="px-3 pb-3 space-y-3 text-[12.5px] text-slate-600">
          <p>
            A target is a Flink cluster on a machine of your choosing. Run one there,
            then put its two addresses in the form above.
          </p>

          <div>
            <div className="eyebrow mb-1">1. Put the image on that machine</div>
            <Copyable>{`docker save mars/flink:0.1.0 | ssh newhost docker load`}</Copyable>
            <p className="hint">Or push it to a registry both machines can reach.</p>
          </div>

          <div>
            <div className="eyebrow mb-1">2. Copy the cluster definition and start it</div>
            <Copyable>{`scp -r remote-target newhost:~/mars-target
ssh newhost 'cd mars-target && cp .env.example .env && docker compose up -d'`}</Copyable>
          </div>

          <div>
            <div className="eyebrow mb-1">3. Check it from here, not from there</div>
            <Copyable>{`curl -s http://newhost:8081/overview
curl -s http://newhost:8083/v1/info`}</Copyable>
            <p className="hint">
              Then fill the form with <code className="mono">http://newhost:8081</code> and{' '}
              <code className="mono">http://newhost:8083</code>, and press Test connection.
            </p>
          </div>

          <div className="pt-1 border-t border-slate-200 space-y-1.5">
            <p>
              <span className="font-medium text-slate-700">Only two ports need opening</span>,
              and only to whatever runs this console: 8081 and 8083. The cluster’s internal
              traffic stays on that machine. Both ports are unauthenticated, so keep them on
              a trusted network.
            </p>
            <p>
              <span className="font-medium text-slate-700">The new machine needs its own
              access</span> to whatever its jobs read and write — Kafka, a database, an API.
              A target is where the work happens, so connectivity is judged from there.
            </p>
            <p className="text-slate-500">
              Adding workers to an existing cluster gives more capacity but not placement:
              Flink schedules tasks into any free slot and cannot pin a job to a machine
              inside one cluster. Choosing where a job runs means choosing the cluster.
            </p>
            <a
              href={REMOTE_DIR}
              target="_blank"
              rel="noreferrer"
              className="inline-block link text-[12px]"
            >
              remote-target/ on GitHub, with the full README →
            </a>
          </div>
        </div>
      )}
    </div>
  )
}
