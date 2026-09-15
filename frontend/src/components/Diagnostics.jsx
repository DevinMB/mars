import { useState } from 'react'
import { bytes, count, millis, percent, rate } from '../lib/format'
import { Alert, Badge, CodeBlock, Spinner } from './ui'

// Flink names operators after the plan that produced them, so a vertex arrives
// as "Source: whispers_raw[12] -> Calc[13] -> Sink: whispers_sink[14]". The
// bracketed ids are noise to everyone except someone reading a Flink plan.
function operatorName(name) {
  return name.replace(/\[\d+\]/g, '').trim()
}

function Stat({ label, value, tone = 'slate', hint }) {
  const tones = {
    slate: 'text-slate-900',
    danger: 'text-red-700',
    warning: 'text-amber-700',
    good: 'text-emerald-700',
  }
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className={`text-sm font-medium ${tones[tone]}`}>{value}</div>
      {hint && <div className="text-xs text-slate-400 mt-0.5">{hint}</div>}
    </div>
  )
}

// A busy operator is doing work; a backpressured one is being held up by whatever
// is downstream of it. The first backpressured operator in a pipeline is the one
// to look at, and the bar makes it findable at a glance.
function Bar({ ratio, tone }) {
  if (ratio === null || ratio === undefined) return <span className="text-slate-400 text-xs">—</span>
  const colors = { busy: 'bg-emerald-500', pressure: 'bg-amber-500', bad: 'bg-red-500' }
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 rounded-full bg-slate-100 overflow-hidden">
        <div className={`h-full rounded-full ${colors[tone]}`}
             style={{ width: `${Math.min(100, Math.max(0, ratio * 100))}%` }} />
      </div>
      <span className="text-xs text-slate-600 tabular-nums w-9">{percent(ratio)}</span>
    </div>
  )
}

/** The one-line answer, stated before any of the numbers. */
function Verdict({ d }) {
  const cp = d.checkpoints
  const stuck = (d.vertices || []).filter((v) => v.backpressure_level === 'high')

  if (d.state === 'FAILED') {
    return <Alert level="danger" title="This job is not running">
      It failed and is no longer on the cluster. The trace below is why.
    </Alert>
  }
  if (d.restarts > 0 && d.state !== 'RUNNING') {
    return <Alert level="warning" title={`Restarted ${d.restarts} times`}>
      The job keeps failing and being restarted, so it is not making steady progress.
    </Alert>
  }
  if (d.state === 'RUNNING' && cp && cp.completed === 0 && cp.latest_completed_age_ms === null) {
    return <Alert level="warning" title="No checkpoint has completed yet">
      Until one does, a failure means reprocessing from the last committed offset.
      A job that has been running for a while and still shows none is stuck.
    </Alert>
  }
  if (cp?.stalled) {
    return <Alert level="danger" title="Checkpoints are not completing">
      The last one finished {millis(cp.latest_completed_age_ms)} ago but this job
      checkpoints every {millis(cp.interval_ms)}. State is not being saved, and the
      job cannot recover cleanly from a failure until it is.
    </Alert>
  }
  if (stuck.length > 0) {
    return <Alert level="warning" title={`Backpressure at ${operatorName(stuck[0].name)}`}>
      This operator is being held up by whatever it writes to. Throughput for the
      whole job is limited by it.
    </Alert>
  }
  if (cp?.failed > 0) {
    return <Alert level="warning" title={`${cp.failed} checkpoints have failed`}>
      Checkpoints are completing now, but some have failed since the job started.
    </Alert>
  }
  if (d.state === 'RUNNING') {
    return <Alert level="success" title="Healthy">
      Checkpoints are completing, and no operator is backpressured.
    </Alert>
  }
  return null
}

export default function Diagnostics({ data, loading, onRefresh }) {
  // On a healthy job the trace is history and stays folded away. On a broken one
  // it is the answer, and making someone click for it is making them guess.
  const unhealthy = data && (data.state !== 'RUNNING' || data.restarts > 0)
  const [trace, setTrace] = useState(null)
  const showTrace = trace === null ? Boolean(unhealthy) : trace

  if (loading && !data) return <Spinner label="Asking the cluster" />
  if (!data) return null

  if (!data.available) {
    return (
      <div className="space-y-3">
        <Alert level="info" title="No live diagnostics">
          {data.reason || 'The cluster has nothing to report for this job.'}
        </Alert>
        {data.exception && (
          <CodeBlock className="text-xs whitespace-pre-wrap">{data.exception}</CodeBlock>
        )}
      </div>
    )
  }

  const cp = data.checkpoints
  const vertices = data.vertices || []

  return (
    <div className="space-y-4">
      <Verdict d={data} />

      {cp && (
        <div>
          <div className="flex items-baseline justify-between mb-2">
            <h4 className="text-sm font-medium text-slate-900">Checkpoints</h4>
            <span className="text-xs text-slate-500">every {millis(cp.interval_ms)}</span>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 rounded-md border border-slate-200 p-3">
            <Stat
              label="Last completed"
              value={cp.latest_completed_age_ms === null ? 'never' : `${millis(cp.latest_completed_age_ms)} ago`}
              tone={cp.stalled ? 'danger' : 'good'}
            />
            <Stat label="Completed" value={count(cp.completed)}
                  hint={cp.restored > 0 ? `restored ${cp.restored}×` : undefined} />
            <Stat label="Failed" value={count(cp.failed)}
                  tone={cp.failed > 0 ? 'warning' : 'slate'} />
            <Stat label="State size" value={bytes(cp.latest_completed_size_bytes)}
                  hint={cp.latest_completed_duration_ms !== null
                    ? `took ${millis(cp.latest_completed_duration_ms)}` : undefined} />
          </div>
        </div>
      )}

      <div>
        <h4 className="text-sm font-medium text-slate-900 mb-2">Operators</h4>
        {vertices.length === 0 ? (
          <p className="text-xs text-slate-500">The cluster reports no operators for this job.</p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-slate-200">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500 border-b border-slate-200">
                  <th className="px-3 py-2 font-medium">Operator</th>
                  <th className="px-3 py-2 font-medium">In</th>
                  <th className="px-3 py-2 font-medium">Out</th>
                  <th className="px-3 py-2 font-medium">Busy</th>
                  <th className="px-3 py-2 font-medium">Backpressure</th>
                  <th className="px-3 py-2 font-medium">Lag</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {vertices.map((v) => (
                  <tr key={v.id} className={v.backpressure_level === 'high' ? 'bg-amber-50/50' : ''}>
                    <td className="px-3 py-2">
                      <div className="text-slate-800 max-w-xs truncate" title={v.name}>
                        {operatorName(v.name)}
                      </div>
                      <div className="text-xs text-slate-500">
                        {v.status.toLowerCase()}
                        {v.parallelism > 1 && <> · parallelism {v.parallelism}</>}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-slate-700 tabular-nums">
                      {count(v.records_in)}
                      <div className="text-xs text-slate-500">{rate(v.records_in_rate)}</div>
                    </td>
                    <td className="px-3 py-2 text-slate-700 tabular-nums">
                      {count(v.records_out)}
                      <div className="text-xs text-slate-500">{rate(v.records_out_rate)}</div>
                    </td>
                    <td className="px-3 py-2"><Bar ratio={v.busy_ratio} tone="busy" /></td>
                    <td className="px-3 py-2">
                      <Bar ratio={v.backpressured_ratio}
                           tone={v.backpressure_level === 'high' ? 'bad' : 'pressure'} />
                    </td>
                    <td className="px-3 py-2 text-slate-700 tabular-nums">
                      {v.kafka_lag_max === null || v.kafka_lag_max === undefined
                        ? <span className="text-slate-400">—</span>
                        : count(v.kafka_lag_max)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-xs text-slate-400 mt-2">
          Busy is time spent doing work; backpressure is time spent waiting on the next
          operator. Lag is how far behind the source is, and only sources report it.
        </p>
      </div>

      {data.exception && (
        <div>
          <button onClick={() => setTrace(!showTrace)}
                  className="text-sm link flex items-center gap-1">
            {showTrace ? 'Hide' : 'Show'} the last exception
          </button>
          {showTrace && (
            <div className="mt-2 space-y-2">
              <CodeBlock className="text-xs whitespace-pre-wrap max-h-96 overflow-y-auto">
                {data.exception}
              </CodeBlock>
              <p className="text-xs text-slate-400">
                Any value matching a stored secret has been replaced with its reference.
              </p>
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-4 pt-1">
        <button className="btn-secondary text-sm" onClick={onRefresh} disabled={loading}>
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
        {data.flink_ui_url && (
          <a href={data.flink_ui_url} target="_blank" rel="noreferrer" className="text-sm link">
            Open in the Flink UI
          </a>
        )}
        {data.target && <span className="text-xs text-slate-400 ml-auto">on {data.target}</span>}
      </div>
    </div>
  )
}
