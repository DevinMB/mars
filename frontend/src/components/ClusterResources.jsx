import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { bytes, millis, percent } from '../lib/format'
import { Spinner } from './ui'

function Bar({ label, used, total, hint }) {
  if (used == null || !total) {
    return (
      <div>
        <div className="flex justify-between text-[12px]"><span className="text-slate-600">{label}</span><span className="text-slate-400">—</span></div>
      </div>
    )
  }
  const ratio = Math.min(1, used / total)
  const tone = ratio >= 0.9 ? 'bg-red-500' : ratio >= 0.75 ? 'bg-amber-500' : 'bg-emerald-500'
  return (
    <div title={hint}>
      <div className="flex justify-between gap-2 text-[12px]">
        <span className="text-slate-600">{label}</span>
        <span className="text-slate-800 tabular-nums">{bytes(used)} / {bytes(total)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-100 mt-1 overflow-hidden">
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.max(2, ratio * 100)}%` }} />
      </div>
    </div>
  )
}

/**
 * What a cluster has and which jobs use it: memory, CPU and slots per
 * TaskManager, and each job's slots, state and checkpoint time, heaviest first.
 * Refreshes while open.
 */
export default function ClusterResources({ name }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const load = () => api.clusterResources(name)
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((err) => alive && setError(err.message))
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [name])

  if (error && !data) return <p className="text-[12px] text-red-700 mt-3">{error}</p>
  if (!data) return <div className="mt-3"><Spinner label="Asking the cluster" /></div>

  return (
    <div className="mt-3 pt-3 border-t border-slate-100 space-y-4">
      {data.taskmanagers.map((tm, i) => (
        <div key={tm.id} className="space-y-2">
          <div className="text-[12px] text-slate-500">
            TaskManager{data.taskmanagers.length > 1 ? ` ${i + 1}` : ''}
            {tm.cpu_cores ? ` · ${tm.cpu_cores} cores` : ''}
            {' · '}{tm.slots_total - tm.slots_free} of {tm.slots_total} slots used
            {tm.cpu_load != null && ` · CPU ${percent(tm.cpu_load)}`}
          </div>
          <Bar label="Heap" used={tm.heap_used} total={tm.heap_max}
               hint="Java heap: operators, and state kept in memory by the hashmap backend." />
          <Bar label="Managed memory" used={tm.managed_used} total={tm.managed_total}
               hint="Flink's off-heap memory, used by RocksDB state and batch sorting. Unused with the hashmap backend." />
        </div>
      ))}
      <Bar label="JobManager heap" used={data.jobmanager.heap_used} total={data.jobmanager.heap_max}
           hint="The coordinator: scheduling, checkpoint coordination, the web UI." />

      {data.jobs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-slate-500">
                <th className="font-normal py-1 pr-3">Job</th>
                <th className="font-normal py-1 pr-3 text-right">Slots</th>
                <th className="font-normal py-1 pr-3 text-right">State</th>
                <th className="font-normal py-1 pr-3 text-right">Checkpoint</th>
                <th className="font-normal py-1">Busiest operator</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {data.jobs.map((j) => (
                <tr key={j.job}>
                  <td className="py-1 pr-3"><Link className="link mono" to={`/jobs/${encodeURIComponent(j.job)}`}>{j.job}</Link></td>
                  <td className="py-1 pr-3 text-right tabular-nums">{j.slots ?? '—'}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{j.state_bytes != null ? bytes(j.state_bytes) : '—'}</td>
                  <td className="py-1 pr-3 text-right tabular-nums">{j.checkpoint_ms != null ? millis(j.checkpoint_ms) : '—'}</td>
                  <td className="py-1 text-slate-600">
                    {j.busy_ratio != null
                      ? <span title={j.busiest}>{percent(j.busy_ratio)} busy</span>
                      : (j.available ? '—' : 'not answering')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="text-[11px] text-slate-400 mt-1.5">
            Heaviest first. A job holds as many slots as its widest operator; its busiest operator sets its pace.
          </p>
        </div>
      )}
    </div>
  )
}
