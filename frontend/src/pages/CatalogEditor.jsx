import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import HealthCheck from '../components/HealthCheck'
import ColumnEditor from '../components/ColumnEditor'
import ConnectorForm from '../components/ConnectorForm'
import ConnectorPicker from '../components/ConnectorPicker'
import { Alert, CodeBlock, Field, PageHeader, Spinner } from '../components/ui'

export default function CatalogEditor() {
  const { name: editing } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()

  const [kind, setKind] = useState(params.get('kind') || 'source')
  const [connectors, setConnectors] = useState(null)
  const [secretNames, setSecretNames] = useState([])
  const [connectorId, setConnectorId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [values, setValues] = useState({})
  const [columns, setColumns] = useState([])
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    (async () => {
      const [all, secrets] = await Promise.all([api.connectors(), api.secrets().catch(() => [])])
      setConnectors(all)
      setSecretNames(secrets.map((s) => s.name))

      if (editing) {
        const e = await api.catalogEntry(editing)
        setKind(e.kind)
        setConnectorId(e.connector)
        setName(e.name)
        setDescription(e.description || '')
        setValues(e.options || {})
        // This entry's own columns, not the connector's suggested ones. Seeding
        // from the connector meant opening any hand-written definition showed
        // someone else's schema, and saving would have written it back.
        const own = (e.columns || []).map((c) => ({ name: c.name, sqlType: c.type }))
        const declared = all.find((c) => c.connector === e.connector)?.columns || []
        setColumns(own.length ? own : declared.map((c) => ({ name: c.name, sqlType: c.sqlType })))
      }
    })().catch((err) => setError(err.message))
  }, [editing])

  const connector = useMemo(
    () => (connectors || []).find((c) => c.connector === connectorId) || null,
    [connectors, connectorId],
  )

  // Choosing a connector seeds the columns it declares, so the common case needs
  // no typing at all.
  useEffect(() => {
    if (!connector || editing) return
    setColumns(connector.columns.map((c) => ({ name: c.name, sqlType: c.sqlType })))
    const defaults = {}
    for (const o of connector.options) if (o.default) defaults[o.key] = o.default
    setValues(defaults)
  }, [connector, editing])

  const available = (connectors || []).filter((c) => c.kinds.includes(kind))

  const save = async () => {
    setSaving(true)
    setError(null)
    const body = { name, kind, connector: connectorId, description, options: values, columns }
    try {
      if (editing) await api.updateCatalog(editing, body)
      else await api.createCatalog(body)
      navigate('/catalog')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!connectors) return <Spinner />

  return (
    <>
      <PageHeader
        title={editing ? `Edit ${editing}` : `New ${kind}`}
        back={{ to: '/catalog', label: 'Catalog' }}
        actions={
          <button className="btn-primary" disabled={saving || !name || !connectorId} onClick={save}>
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Create'}
          </button>
        }
      />

      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div className="card p-6 space-y-4">
            {!editing && (
              <Field label="Kind">
                <div className="flex gap-2">
                  {['source', 'sink'].map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => { setKind(k); setConnectorId(''); }}
                      className={kind === k ? 'btn-primary' : 'btn-secondary'}
                    >
                      {k === 'source' ? 'Source' : 'Sink'}
                    </button>
                  ))}
                </div>
              </Field>
            )}

            <Field label="Name" required hint="Used as the table name in SQL, so letters, digits and underscores only.">
              <input className="input mono" value={name} disabled={!!editing}
                     onChange={(e) => setName(e.target.value)} placeholder="whispers_raw" />
            </Field>

            <Field label="Description">
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)}
                     placeholder="What this reads from, in plain words" />
            </Field>

            <Field label="Connector" required>
              <ConnectorPicker
                connectors={available}
                value={connectorId}
                onChange={setConnectorId}
                disabled={!!editing}
              />
            </Field>
          </div>

          {connector && (
            <>
              <div className="card p-6">
                <h2 className="font-medium text-slate-900 mb-4">Connection</h2>
                <ConnectorForm
                  connector={connector}
                  values={values}
                  onChange={(k, v) => setValues((prev) => ({ ...prev, [k]: v }))}
                  secretNames={secretNames}
                />

                <HealthCheck connector={connectorId} options={values} />
              </div>

              <div className="card p-6">
                <h2 className="font-medium text-slate-900 mb-1">Columns</h2>
                <p className="text-xs text-slate-500 mb-4">
                  The shape of each record. The connector pre-fills what it expects.
                </p>
                <ColumnEditor columns={columns} onChange={setColumns} declared={connector.columns} />
              </div>
            </>
          )}
        </div>

        <aside className="space-y-4">
          {connector?.description && (
            <div className="card p-4">
              <h3 className="text-sm font-medium text-slate-900 mb-1">{connector.displayName}</h3>
              <p className="text-xs text-slate-600">{connector.description}</p>
              {connector.docsUrl && (
                <a href={connector.docsUrl} target="_blank" rel="noreferrer"
                   className="text-xs text-brand-600 hover:text-brand-700 mt-2 inline-block">
                  Connector documentation →
                </a>
              )}
            </div>
          )}
          <div className="card p-4">
            <h3 className="text-sm font-medium text-slate-900 mb-2">Generated SQL</h3>
            <p className="text-xs text-slate-500 mb-3">
              MARS writes this for you. It is saved as text, so you can edit it by hand later.
            </p>
            <CodeBlock className="text-xs">
              {connectorId && name
                ? `CREATE TABLE ${name} (\n${columns.map((c) => `  ${c.name || '…'} ${c.sqlType}`).join(',\n')}\n) WITH (\n  'connector' = '${connectorId}',\n  …\n)`
                : 'Choose a connector to see the statement.'}
            </CodeBlock>
          </div>
        </aside>
      </div>
    </>
  )
}
