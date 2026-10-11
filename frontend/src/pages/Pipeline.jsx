import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { layoutGraph } from '../lib/layout'
import { filterGraph } from '../lib/pipelineFilter'
import PanZoom from '../components/PanZoom'
import { Alert, EmptyState, PageHeader, Spinner } from '../components/ui'

const SIZE = { job: { w: 180, h: 40 }, resource: { w: 170, h: 40 }, external: { w: 150, h: 36 } }
const PAD = 24

const clip = (text, n) => (text.length > n ? `${text.slice(0, n - 1)}…` : text)

const STATE_DOT = {
  running: 'fill-emerald-500',
  restarting: 'fill-amber-500',
  failed: 'fill-red-500',
}

function Edge({ a, b, active }) {
  const x1 = a.x + a.w, y1 = a.y + a.h / 2
  const x2 = b.x, y2 = b.y + b.h / 2
  const dx = Math.max(30, (x2 - x1) / 2)
  return (
    <path d={`M${x1} ${y1} C${x1 + dx} ${y1} ${x2 - dx} ${y2} ${x2 - 6} ${y2}`}
          className={`fill-none ${active ? 'stroke-accent-500' : 'stroke-slate-300'}`}
          strokeWidth={active ? 2 : 1.4} markerEnd={`url(#${active ? 'arrow-on' : 'arrow'})`} />
  )
}

function Node({ node, p, selected, onSelect }) {
  const common = {
    role: 'button', tabIndex: 0, 'aria-label': `${node.type === 'resource' ? node.kind : node.type} ${node.label}`,
    className: 'cursor-pointer focus:outline-hidden',
    onClick: () => onSelect(node),
    onKeyDown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(node) } },
  }
  const ring = selected ? 'stroke-accent-600' : ''
  if (node.type === 'job') {
    return (
      <g {...common} transform={`translate(${p.x} ${p.y})`}>
        <title>{node.label}{node.state ? ` (${node.state})` : ''}</title>
        <rect width={p.w} height={p.h} rx="6" className={`fill-surface ${ring || 'stroke-slate-600'}`} strokeWidth={selected ? 2.2 : 1.4} />
        <circle cx="14" cy={p.h / 2} r="4" className={STATE_DOT[node.state] || 'fill-slate-300'} />
        <text x="26" y={p.h / 2 + 4} className="fill-slate-900 text-[12.5px]">{clip(node.label, 22)}</text>
      </g>
    )
  }
  if (node.type === 'resource') {
    return (
      <g {...common} transform={`translate(${p.x} ${p.y})`}>
        <title>{node.kind}: {node.label}</title>
        <rect width={p.w} height={p.h} rx={p.h / 2} className={`fill-accent-50 ${ring || 'stroke-accent-400'}`} strokeWidth={selected ? 2.2 : 1.4} />
        <text x={p.w / 2} y={p.h / 2 - 2} textAnchor="middle" className="fill-slate-900 text-[12px] font-mono">{clip(node.label, 22)}</text>
        <text x={p.w / 2} y={p.h / 2 + 11} textAnchor="middle" className="fill-slate-500 text-[10px]">
          {node.kind}{node.entries.length > 1 ? ` · ${node.entries.length} entries` : ''}
        </text>
      </g>
    )
  }
  return (
    <g {...common} transform={`translate(${p.x} ${p.y})`}>
      <title>{node.label} {node.direction} this{node.note ? `: ${node.note}` : ''}</title>
      <rect width={p.w} height={p.h} rx="8" className={`fill-none ${ring || 'stroke-slate-400'}`} strokeDasharray="4 3" strokeWidth={selected ? 2 : 1.2} />
      <text x={p.w / 2} y={p.h / 2 + 4} textAnchor="middle" className="fill-slate-700 text-[12px]">{clip(node.label, 20)}</text>
    </g>
  )
}

function ResourcePanel({ node, graph, canWrite, onChanged }) {
  const [name, setName] = useState('')
  const [direction, setDirection] = useState('produces')
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const byId = new Map(graph.nodes.map((n) => [n.id, n]))
  const writers = graph.edges.filter((e) => e.to === node.id).map((e) => byId.get(e.from))
  const readers = graph.edges.filter((e) => e.from === node.id).map((e) => byId.get(e.to))
  const list = (nodes, type) => nodes.filter((n) => n?.type === type)

  const add = async () => {
    setSaving(true); setError(null)
    try {
      await api.addExternal({ resource_key: node.key, name, direction, note: note || null })
      setName(''); setNote(''); onChanged()
    } catch (e) { setError(e.message) } finally { setSaving(false) }
  }

  const Names = ({ nodes }) => nodes.length
    ? nodes.map((n, i) => <span key={n.id}>{i > 0 && ', '}
        <Link className="link" to={`/jobs/${encodeURIComponent(n.label)}`}>{n.label}</Link></span>)
    : <span className="text-slate-400">—</span>

  const Outside = ({ nodes }) => nodes.length ? (
    <ul className="space-y-1">{nodes.map((n) => <li key={n.id} className="flex items-center gap-2 text-[13px]">
      <span className="text-slate-800">{n.label}</span>
      {n.note && <span className="text-slate-500 text-[12px]">{n.note}</span>}
      {canWrite && <button className="ml-auto text-[12px] text-slate-500 hover:text-red-700" onClick={async () => {
        try { await api.removeExternal(n.endpoint_id); onChanged() } catch (e) { setError(e.message) }
      }}>Remove</button>}
    </li>)}</ul>
  ) : <span className="text-slate-400 text-[13px]">None declared</span>

  return (
    <div className="card p-5 mt-5">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{node.kind}</div>
      <h2 className="mono text-[15px] font-medium text-slate-900 mb-4 break-all">{node.label}</h2>
      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
      <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 text-[13px]">
        <div><dt className="text-slate-500 mb-0.5">Written by</dt><dd><Names nodes={list(writers, 'job')} /></dd></div>
        <div><dt className="text-slate-500 mb-0.5">Read by</dt><dd><Names nodes={list(readers, 'job')} /></dd></div>
        <div><dt className="text-slate-500 mb-0.5">Outside Flink, writing it</dt><dd><Outside nodes={list(writers, 'external')} /></dd></div>
        <div><dt className="text-slate-500 mb-0.5">Outside Flink, reading it</dt><dd><Outside nodes={list(readers, 'external')} /></dd></div>
        <div className="sm:col-span-2"><dt className="text-slate-500 mb-0.5">Catalog entries</dt><dd>
          {node.entries.map((n, i) => <span key={n}>{i > 0 && ', '}
            <Link className="link mono" to={`/catalog/${encodeURIComponent(n)}/edit`}>{n}</Link></span>)}
        </dd></div>
      </dl>
      {canWrite && (
        <div className="mt-5 pt-4 border-t border-slate-200">
          <div className="text-[13px] font-medium text-slate-800 mb-1">Add something outside Flink</div>
          <p className="text-[12px] text-slate-500 mb-3">A service or device that writes or reads this, which MARS cannot see in any job's SQL.</p>
          <div className="flex flex-wrap gap-2 items-center">
            <input className="input w-48" aria-label="Name" placeholder="e.g. whisper-collector" value={name} onChange={(e) => setName(e.target.value)} />
            <select className="input w-auto" aria-label="Direction" value={direction} onChange={(e) => setDirection(e.target.value)}>
              <option value="produces">writes it</option><option value="consumes">reads it</option>
            </select>
            <input className="input flex-1 min-w-40" aria-label="Note" placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn-secondary" disabled={!name.trim() || saving} onClick={add}>{saving ? 'Adding…' : 'Add'}</button>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * How data moves: jobs, the topics and tables between them, and what feeds or
 * reads them from outside Flink. Drawn from each job's reads and writes, so it
 * is right for any installation without configuration.
 */
export default function Pipeline() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const canWrite = ['admin', 'editor'].includes(user?.role)
  const [graph, setGraph] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  // Filters live in the address, so a narrowed view can be shared or bookmarked.
  const [params, setParams] = useSearchParams()
  const focus = params.get('focus')
  const cluster = params.get('cluster')
  const setFilter = (key, value) => setParams((prev) => {
    const next = new URLSearchParams(prev)
    if (value) next.set(key, value); else next.delete(key)
    return next
  }, { replace: true })

  const load = () => api.pipeline().then((g) => { setGraph(g); setError(null) }).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const shown = useMemo(() => graph && filterGraph(graph, { cluster, focus }), [graph, cluster, focus])
  const layout = useMemo(() => {
    if (!shown) return null
    const types = new Map(shown.nodes.map((n) => [n.id, n.type]))
    return layoutGraph(shown.nodes, shown.edges, { colWidth: 215, sizeOf: (id) => SIZE[types.get(id)] })
  }, [shown])

  if (error && !graph) return <Alert level="danger" title="Could not load the pipeline">{error}</Alert>
  if (!graph) return <Spinner label="Drawing the pipeline" />

  const current = selected && shown.nodes.find((n) => n.id === selected)
  const clusters = [...new Set(graph.nodes.filter((n) => n.type === 'job' && n.cluster).map((n) => n.cluster))].sort()
  const byType = (type) => graph.nodes.filter((n) => n.type === type).sort((a, b) => a.label.localeCompare(b.label))
  const filtered = Boolean(focus || cluster)
  const jobCount = (nodes) => nodes.filter((n) => n.type === 'job').length
  const touches = (e) => current && (e.from === current.id || e.to === current.id)
  const select = (node) => {
    if (node.type === 'job' && selected === node.id) navigate(`/jobs/${encodeURIComponent(node.label)}`)
    else setSelected(node.id === selected ? null : node.id)
  }

  return (
    <>
      <PageHeader title="Pipeline" subtitle="How data moves: jobs, the topics and tables between them, and what feeds them from outside Flink." />
      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
      {!graph.nodes.length ? (
        <EmptyState title="Nothing to draw yet">Jobs appear here once they read or write catalog tables.</EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3 mb-3">
            <label className="text-[12px] text-slate-500">
              <span className="block mb-1">Focus on</span>
              <select className="input w-64 max-w-full" aria-label="Focus on" value={focus || ''} onChange={(e) => { setSelected(null); setFilter('focus', e.target.value) }}>
                <option value="">The whole pipeline</option>
                <optgroup label="Jobs">{byType('job').map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}</optgroup>
                <optgroup label="Topics and tables">{byType('resource').map((n) => <option key={n.id} value={n.id}>{n.label} ({n.kind})</option>)}</optgroup>
                {byType('external').length > 0 && (
                  <optgroup label="Outside Flink">{byType('external').map((n) => <option key={n.id} value={n.id}>{n.label}</option>)}</optgroup>
                )}
              </select>
            </label>
            {clusters.length > 1 && (
              <label className="text-[12px] text-slate-500">
                <span className="block mb-1">Cluster</span>
                <select className="input w-44" aria-label="Cluster" value={cluster || ''} onChange={(e) => { setSelected(null); setFilter('cluster', e.target.value) }}>
                  <option value="">All clusters</option>
                  {clusters.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </label>
            )}
            {filtered && (
              <div className="text-[12px] text-slate-500 pb-2">
                Showing {jobCount(shown.nodes)} of {jobCount(graph.nodes)} jobs ·{' '}
                <button type="button" className="link" onClick={() => { setSelected(null); setParams({}, { replace: true }) }}>Show everything</button>
              </div>
            )}
          </div>
          {current && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] mb-3">
              <span className="text-slate-500">Selected</span>
              <span className={`text-slate-900 ${current.type === 'resource' ? 'mono' : ''}`}>{current.label}</span>
              {focus !== current.id && (
                <button type="button" className="link text-[13px]" onClick={() => setFilter('focus', current.id)}>Show only what connects to this</button>
              )}
              {current.type === 'job' && (
                <Link className="link" to={`/jobs/${encodeURIComponent(current.label)}`}>Open job</Link>
              )}
            </div>
          )}
          <div className="flex flex-wrap gap-4 text-[12px] text-slate-500 mb-2">
            <span className="flex items-center gap-1.5"><span className="w-5 h-3 rounded-full bg-accent-50 border border-accent-400" />Topic or table</span>
            <span className="flex items-center gap-1.5"><span className="w-5 h-3 rounded-sm border border-slate-600" />Flink job</span>
            <span className="flex items-center gap-1.5"><span className="w-5 h-3 rounded-sm border border-dashed border-slate-400" />Outside Flink</span>
            <span className="sm:ml-auto">Drag to move around. Select a topic to see and add what reads and writes it.</span>
          </div>
          {shown.missing ? (
            <EmptyState title="Not on this cluster">What you focused on is not connected to any job on {cluster}.</EmptyState>
          ) : (
            <div className="card p-0">
              <PanZoom width={layout.width + PAD * 2} height={layout.height + PAD * 2}
                       fitKey={`${focus}|${cluster}`} label="Pipeline graph">
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" className="fill-slate-300" /></marker>
                  <marker id="arrow-on" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" className="fill-accent-500" /></marker>
                </defs>
                <g transform={`translate(${PAD} ${PAD})`}>
                  {shown.edges.map((e) => {
                    const a = layout.positions.get(e.from), b = layout.positions.get(e.to)
                    return a && b ? <Edge key={`${e.from}>${e.to}`} a={a} b={b} active={touches(e)} /> : null
                  })}
                  {shown.nodes.map((n) => <Node key={n.id} node={n} p={layout.positions.get(n.id)}
                                                selected={n.id === selected} onSelect={select} />)}
                </g>
              </PanZoom>
            </div>
          )}
          {current?.type === 'resource' && (
            <ResourcePanel node={current} graph={graph} canWrite={canWrite} onChanged={load} />
          )}
          {!filtered && graph.unused.length > 0 && (
            <p className="text-[12px] text-slate-500 mt-4">
              Not used by any job: {graph.unused.map((n, i) => <span key={n}>{i > 0 && ', '}
                <Link className="link mono" to={`/catalog/${encodeURIComponent(n)}/edit`}>{n}</Link></span>)}
            </p>
          )}
        </>
      )}
    </>
  )
}
