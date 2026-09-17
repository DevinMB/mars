import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { useConfirm, useNotify } from '../components/InteractionProvider'
import ActionMenu from '../components/ActionMenu'
import SearchInput from '../components/SearchInput'
import { Alert, Badge, EmptyState, PageHeader, Spinner } from '../components/ui'

export default function Catalog() {
  const { user } = useAuth()
  const canWrite = ['admin', 'editor'].includes(user?.role)
  const confirm = useConfirm()
  const notify = useNotify()
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState('all')
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
  const shown = entries.filter((e) => (kind === 'all' || kind === e.kind) &&
    `${e.name} ${e.description || ''} ${e.connector} ${e.used_by.join(' ')}`.toLowerCase().includes(q))
  return <>
    <PageHeader title="Catalog" subtitle="Sources and sinks for your pipelines."
      actions={canWrite && <ActionMenu label="New entry" primary>
        <Link to="/catalog/new?kind=source">Source</Link>
        <Link to="/catalog/new?kind=sink">Sink</Link>
      </ActionMenu>} />
    {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}
    <div className="flex flex-wrap gap-3 items-center mb-5">
      <div className="w-full sm:w-72"><SearchInput value={query} onChange={setQuery} placeholder="Search catalog…" count={shown.length} /></div>
      <select className="input w-auto" aria-label="Filter by kind" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="all">Sources & sinks</option><option value="source">Sources</option><option value="sink">Sinks</option>
      </select>
      <span className="text-xs text-slate-500 sm:ml-auto">{shown.length} of {entries.length} entries</span>
    </div>
    {!entries.length ? <EmptyState title="No catalog entries" action={canWrite && <Link to="/catalog/new?kind=source" className="btn-primary">Add a source</Link>}>
      Define a source to read records and a sink to write them.
    </EmptyState> : <div className="table-scroll"><table className="tbl">
      <thead><tr><th>Name</th><th>Kind</th><th>Connector</th><th>Used by</th>{canWrite && <th><span className="sr-only">Actions</span></th>}</tr></thead>
      <tbody>{shown.length === 0 ? <tr><td colSpan={canWrite ? 5 : 4} className="text-center text-slate-500 py-8">No entries match your filters.</td></tr> : shown.map((e) => <tr key={e.name}>
        <td className="max-w-48 sm:max-w-sm">
          {canWrite ? <Link to={`/catalog/${encodeURIComponent(e.name)}/edit`} className="font-medium text-slate-900 hover:underline break-all">{e.name}</Link> : <span className="font-medium break-all">{e.name}</span>}
          {e.description && <p className="text-xs text-slate-500 mt-1">{e.description}</p>}
        </td>
        <td className="text-slate-600">{e.kind === 'source' ? 'Source' : 'Sink'}</td>
        <td><Badge>{e.connector}</Badge></td>
        <td className="text-slate-500 text-xs max-w-xs">{e.used_by.length ? e.used_by.map((job, i) => <span key={job}>{i > 0 && ', '}<Link className="link" to={`/jobs/${encodeURIComponent(job)}`}>{job}</Link></span>) : 'Not in use'}</td>
        {canWrite && <td className="text-right">
          {busy === e.name ? <span role="status">Deleting…</span> : <ActionMenu label={<><span className="sr-only">Actions for {e.name}</span><span aria-hidden="true">More</span></>}>
            <Link to={`/catalog/${encodeURIComponent(e.name)}/edit`}>Edit entry</Link>
            <Link to={`/catalog/new?from=${encodeURIComponent(e.name)}`}>Duplicate</Link>
            <button className="text-red-700" onClick={() => remove(e.name)}>Delete entry</button>
          </ActionMenu>}
        </td>}
      </tr>)}</tbody>
    </table></div>}
  </>
}
