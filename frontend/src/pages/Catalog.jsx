import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { Alert, Badge, EmptyState, PageHeader, Spinner } from '../components/ui'

export default function Catalog() {
  const [entries, setEntries] = useState(null)
  const [error, setError] = useState(null)

  const load = async () => {
    try { setEntries(await api.catalog()); setError(null) }
    catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [])

  const remove = async (name) => {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return
    try { await api.deleteCatalog(name); load() }
    catch (err) { setError(err.message) }
  }

  if (error && !entries) return <Alert level="danger" title="Could not load the catalog">{error}</Alert>
  if (!entries) return <Spinner label="Loading catalog" />

  const sources = entries.filter((e) => e.kind === 'source')
  const sinks = entries.filter((e) => e.kind === 'sink')

  const Section = ({ title, blurb, rows }) => (
    <div className="card overflow-hidden mb-6">
      <div className="px-4 py-3 border-b border-slate-200">
        <h2 className="font-medium text-slate-900">{title}</h2>
        <p className="text-xs text-slate-500 mt-0.5">{blurb}</p>
      </div>
      {rows.length === 0 ? (
        <p className="px-4 py-8 text-sm text-slate-500 text-center">Nothing defined yet.</p>
      ) : (
        <table className="w-full text-sm">
          <tbody className="divide-y divide-slate-100">
            {rows.map((e) => (
              <tr key={e.id} className="hover:bg-slate-50/60">
                <td className="px-4 py-3">
                  <div className="font-medium text-slate-900 mono">{e.name}</div>
                  {e.description && <div className="text-xs text-slate-500">{e.description}</div>}
                </td>
                <td className="px-4 py-3"><Badge tone="blue">{e.connector}</Badge></td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {e.used_by.length ? `Used by ${e.used_by.join(', ')}` : 'Not used by any job'}
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  <Link to={`/catalog/${encodeURIComponent(e.name)}/edit`}
                        className="link text-sm mr-3">Edit</Link>
                  <button onClick={() => remove(e.name)}
                          className="text-slate-400 hover:text-red-600 text-sm">Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )

  return (
    <>
      <PageHeader
        title="Catalog"
        subtitle="The sources and sinks your jobs read from and write to"
        actions={
          <>
            <Link to="/catalog/new?kind=source" className="btn-secondary">New source</Link>
            <Link to="/catalog/new?kind=sink" className="btn-primary">New sink</Link>
          </>
        }
      />
      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {entries.length === 0 ? (
        <EmptyState
          title="Nothing in the catalog"
          action={<Link to="/catalog/new?kind=source" className="btn-primary">Define a source</Link>}
        >
          A source is where records come from and a sink is where they go. Pick a
          connector and MARS builds the table definition for you.
        </EmptyState>
      ) : (
        <>
          <Section title="Sources" blurb="Where records are read from." rows={sources} />
          <Section title="Sinks" blurb="Where records are written to." rows={sinks} />
        </>
      )}
    </>
  )
}
