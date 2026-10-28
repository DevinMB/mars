import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useConfirm, useNotify } from '../components/InteractionProvider'
import ActionMenu from '../components/ActionMenu'
import SearchInput from '../components/SearchInput'
import { Alert, Badge, EmptyState, PageHeader, Spinner } from '../components/ui'

// Entries pointing at the same topic or database are the same thing seen
// differently (raw, with a watermark, sampled), so they are shown together.
function groupByResource(entries) {
  const groups = new Map()
  for (const e of entries) {
    const key = e.resource?.key || `table:${e.name}`
    if (!groups.has(key)) groups.set(key, { key, resource: e.resource, entries: [] })
    groups.get(key).entries.push(e)
  }
  return [...groups.values()].sort((a, b) =>
    (a.resource?.kind || '').localeCompare(b.resource?.kind || '')
    || (a.resource?.label || '').localeCompare(b.resource?.label || ''))
}

function Jobs({ names }) {
  if (!names.length) return <span className="text-slate-400">—</span>
  return names.map((job, i) => <span key={job}>{i > 0 && ', '}
    <Link className="link" to={`/jobs/${encodeURIComponent(job)}`}>{job}</Link></span>)
}

function ResourceGroup({ group, cols, canWrite, busy, remove }) {
  const { resource, entries } = group
  // A table that is its own resource (an unknown connector) needs no heading.
  const heading = resource && !resource.key.startsWith('table:')
  return <>
    {heading && <tr className="bg-slate-50/80">
      <td colSpan={cols} className="py-2!">
        <span className="text-[11px] uppercase tracking-wide text-slate-500">{resource.kind}</span>
        <span className="mono text-[13px] font-medium text-slate-900 ml-2">{resource.label}</span>
        {entries.length > 1 && <span className="text-[11px] text-slate-500 ml-2">{entries.length} entries</span>}
      </td>
    </tr>}
    {entries.map((e) => <tr key={e.name}>
      <td className="max-w-48 sm:max-w-sm">
        <div className={heading ? 'pl-4' : ''}>
          {canWrite ? <Link to={`/catalog/${encodeURIComponent(e.name)}/edit`} className="font-medium text-slate-900 hover:underline break-all">{e.name}</Link> : <span className="font-medium break-all">{e.name}</span>}
          {!e.read_by.length && !e.written_by.length && <span className="ml-2"><Badge>not used</Badge></span>}
          {e.description && <p className="text-xs text-slate-500 mt-1">{e.description}</p>}
        </div>
      </td>
      <td><Badge>{e.connector}</Badge></td>
      <td className="text-slate-600 text-xs max-w-xs"><Jobs names={e.written_by} /></td>
      <td className="text-slate-600 text-xs max-w-xs"><Jobs names={e.read_by} /></td>
      {canWrite && <td className="text-right">
        {busy === e.name ? <span role="status">Deleting…</span> : <ActionMenu icon label={`Actions for ${e.name}`}>
          <Link to={`/catalog/${encodeURIComponent(e.name)}/edit`}>Edit entry</Link>
          <Link to={`/catalog/new?from=${encodeURIComponent(e.name)}`}>Duplicate</Link>
          <button className="text-red-700" onClick={() => remove(e.name)}>Delete entry</button>
        </ActionMenu>}
      </td>}
    </tr>)}
  </>
}

export default function Catalog() {
  const { user } = useAuth()
  const canWrite = ['admin', 'editor'].includes(user?.role)
  const confirm = useConfirm()
  const notify = useNotify()
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [view, setView] = useState('all')
  const [busy, setBusy] = useState(null)
  const load = async () => {
    try { setEntries(await api.catalog()); setError(null) }
    catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [])
  const remove = async (name) => {
    if (!await confirm({ title: `Delete ${name}?`, message: 'This catalog entry will be permanently deleted. This cannot be undone.', confirmLabel: 'Delete entry' })) return
    setBusy(name)
    try { await api.deleteCatalog(name); await load(); notify('Catalog entry deleted.') }
    catch (err) { setError(err.message) }
    finally { setBusy(null) }
  }
  if (error && !entries) return <Alert level="danger" title="Could not load the catalog">{error}</Alert>
  if (!entries) return <Spinner label="Loading catalog" />
  const q = query.trim().toLowerCase()
  const matches = (e) => (view === 'all'
      || (view === 'kafka' && e.resource?.kind === 'kafka topic')
      || (view === 'unused' && !e.read_by.length && !e.written_by.length))
    && `${e.name} ${e.description || ''} ${e.connector} ${e.resource?.label || ''} ${e.read_by.join(' ')} ${e.written_by.join(' ')}`
      .toLowerCase().includes(q)
  const shown = entries.filter(matches)
  const groups = groupByResource(shown)
  const cols = canWrite ? 5 : 4
  return <>
    <PageHeader title="Catalog" subtitle="Tables your jobs read and write, grouped by what they point at."
      actions={canWrite && <Link to="/catalog/new" className="btn-primary">New entry</Link>} />
    {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
    <div className="flex flex-wrap gap-3 items-center mb-5">
      <div className="w-full sm:w-72"><SearchInput value={query} onChange={setQuery} placeholder="Search catalog…" count={shown.length} /></div>
      <select className="input input-compact w-auto" aria-label="Show" value={view} onChange={(e) => setView(e.target.value)}>
        <option value="all">Everything</option><option value="kafka">Kafka topics</option><option value="unused">Not used by any job</option>
      </select>
      <span className="text-xs text-slate-500 sm:ml-auto">{shown.length} of {entries.length} entries</span>
    </div>
    {!entries.length ? <EmptyState title="No catalog entries" action={canWrite && <Link to="/catalog/new" className="btn-primary">Add an entry</Link>}>
      Define the tables your jobs read from and write to: a Kafka topic, a database, an API.
    </EmptyState> : <div className="table-scroll"><table className="tbl">
      <thead><tr><th>Name</th><th>Connector</th><th>Written by</th><th>Read by</th>{canWrite && <th><span className="sr-only">Actions</span></th>}</tr></thead>
      <tbody>{groups.length === 0 ? <tr><td colSpan={cols} className="text-center text-slate-500 py-8">No entries match your filters.</td></tr>
        : groups.map((g) => <ResourceGroup key={g.key} group={g} cols={cols} canWrite={canWrite} busy={busy} remove={remove} />)}</tbody>
    </table></div>}
  </>
}
