import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Alert, PageHeader, Spinner } from '../components/ui'

function Stat({ label, value, tone = 'slate' }) {
  const tones = { slate: 'text-slate-900', good: 'text-emerald-600', bad: 'text-red-600' }
  return (
    <div className="card p-5">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`text-2xl font-semibold mt-1 ${tones[tone]}`}>{value}</div>
    </div>
  )
}

export default function Cluster() {
  const [info, setInfo] = useState(null)
  const [connectors, setConnectors] = useState([])

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [c, k] = await Promise.all([api.cluster(), api.connectors()])
        if (alive) { setInfo(c); setConnectors(k) }
      } catch {
        if (alive) setInfo({ reachable: false })
      }
    }
    load()
    const t = setInterval(load, 10000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (!info) return <Spinner label="Reading cluster" />

  return (
    <>
      <PageHeader title="Cluster" subtitle={info.reachable ? `Apache Flink ${info.flink_version}` : null} />

      {!info.reachable ? (
        <Alert level="danger" title="Flink is not reachable">
          The console is running but cannot reach the Flink REST API. Jobs cannot be
          started or inspected until it comes back.
        </Alert>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 mb-8">
          <Stat label="Task managers" value={info.taskmanagers} />
          <Stat label="Slots free" value={`${info.slots_available} / ${info.slots_total}`}
                tone={info.slots_available === 0 ? 'bad' : 'slate'} />
          <Stat label="Jobs running" value={info.jobs_running} />
          <Stat label="Connectors" value={connectors.length} />
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-200">
          <h2 className="font-medium text-slate-900">Installed connectors</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Each contributes its own form. Drop a connector JAR containing a manifest into
            the Flink library directory and it appears here.
          </p>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 border-b border-slate-200">
            <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-4 py-2.5 font-semibold">Connector</th>
              <th className="px-4 py-2.5 font-semibold">Use</th>
              <th className="px-4 py-2.5 font-semibold">Options</th>
              <th className="px-4 py-2.5 font-semibold">Provided by</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {connectors.map((c) => (
              <tr key={c.connector}>
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900">{c.displayName}</div>
                  {c.description && <div className="text-xs text-slate-500 max-w-lg">{c.description}</div>}
                </td>
                <td className="px-4 py-3 text-slate-600">{c.kinds.join(', ')}</td>
                <td className="px-4 py-3 text-slate-600">{c.options.length}</td>
                <td className="px-4 py-3">
                  <code className="mono text-xs text-slate-500">{c.source}</code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
