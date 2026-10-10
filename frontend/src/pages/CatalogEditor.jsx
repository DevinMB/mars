import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import useUnsavedChanges from '../lib/useUnsavedChanges'
import { useNotify } from '../components/InteractionProvider'
import HealthCheck from '../components/HealthCheck'
import SourcePeek from '../components/SourcePeek'
import SchemaFill from '../components/SchemaFill'
import CatalogHistory from '../components/CatalogHistory'
import ColumnEditor from '../components/ColumnEditor'
import ConnectorForm from '../components/ConnectorForm'
import ConnectorPicker from '../components/ConnectorPicker'
import { Alert, CodeBlock, Field, PageHeader, Spinner } from '../components/ui'

export default function CatalogEditor() {
  const { name: editing } = useParams()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const notify = useNotify()
  const [loaded, setLoaded] = useState(false)
  const [initial, setInitial] = useState(null)

  const [kind, setKind] = useState(params.get('kind') || 'source')
  const [connectors, setConnectors] = useState(null)
  const [secretNames, setSecretNames] = useState([])
  const [connectorId, setConnectorId] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [values, setValues] = useState({})
  const [columns, setColumns] = useState([])
  const [usedBy, setUsedBy] = useState([])
  const [note, setNote] = useState('')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)

  const cloneOf = new URLSearchParams(window.location.search).get('from')

  useEffect(() => {
    (async () => {
      const [all, secrets] = await Promise.all([api.connectors(), api.secrets().catch(() => [])])
      setConnectors(all)
      setSecretNames(secrets.map((s) => s.name))

      if (!editing && cloneOf) {
        const e = await api.catalogEntry(cloneOf)
        setKind(e.kind)
        setConnectorId(e.connector)
        setName(`${e.name}_copy`)
        setDescription(e.description || '')
        setValues(e.options || {})
        setColumns((e.columns || []).map((c) => ({ name: c.name, sqlType: c.type })))
      }

      if (editing) {
        const e = await api.catalogEntry(editing)
        setKind(e.kind)
        setConnectorId(e.connector)
        setName(e.name)
        setDescription(e.description || '')
        setValues(e.options || {})
        setUsedBy(e.used_by || [])
        // This entry's own columns, not the connector's suggested ones. Seeding
        // from the connector meant opening any hand-written definition showed
        // someone else's schema, and saving would have written it back.
        const own = (e.columns || []).map((c) => ({ name: c.name, sqlType: c.type }))
        const declared = all.find((c) => c.connector === e.connector)?.columns || []
        setColumns(own.length ? own : declared.map((c) => ({ name: c.name, sqlType: c.sqlType })))
      }
      setLoaded(true)
    })().catch((err) => setError(err.message))
  }, [editing, cloneOf])

  const connector = useMemo(
    () => (connectors || []).find((c) => c.connector === connectorId) || null,
    [connectors, connectorId],
  )

  const chooseConnector = (id) => {
    setConnectorId(id)
    const selected = connectors.find((c) => c.connector === id)
    setColumns((selected?.columns || []).map((c) => ({ name: c.name, sqlType: c.sqlType })))
    setValues(Object.fromEntries((selected?.options || []).filter((o) => o.default != null)
      .map((o) => [o.key, o.default])))
  }

  const available = (connectors || []).filter((c) => c.kinds.includes(kind))

  const serialized = JSON.stringify({ name, description, kind, connectorId, values, columns, note })
  useEffect(() => { if (loaded && initial === null) setInitial(serialized) }, [loaded, initial, serialized])
  const unsaved = initial !== null && initial !== serialized
  const allowNavigation = useUnsavedChanges(unsaved)

  const save = async () => {
    setSaving(true)
    setError(null)
    const body = { name, kind, connector: connectorId, description, options: values,
                    columns, note: note || undefined }
    try {
      if (editing) await api.updateCatalog(editing, body)
      else await api.createCatalog(body)
      allowNavigation()
      notify(editing ? 'Changes saved.' : 'Catalog entry created.')
      navigate('/catalog')
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  if (!loaded && error) return <Alert level="danger">{error}</Alert>
  if (!loaded || !connectors) return <Spinner />

  return (
    <>
      <PageHeader
        title={editing ? `Edit ${editing}` : cloneOf ? `Copy of ${cloneOf}` : `New ${kind}`}
        back={{ to: '/catalog', label: 'Catalog' }}
        subtitle={unsaved ? 'Unsaved changes' : null}
        actions={
          <button className="btn-primary" disabled={saving || !name || !connectorId} onClick={save}>
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Create'}
          </button>
        }
      />

      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="editor-grid">
        <div className="space-y-6 min-w-0">
          <div className="form-section grid gap-4 sm:grid-cols-2">
            {!editing && (
              <Field label="Kind">
                <div className="flex gap-2">
                  {['source', 'sink'].map((k) => (
                    <button
                      key={k}
                      type="button"
                      onClick={() => { setKind(k); setConnectorId(''); }}
                      aria-pressed={kind === k} className={`choice ${kind === k ? 'choice-selected' : ''}`}
                    >
                      {k === 'source' ? 'Source' : 'Sink'}
                    </button>
                  ))}
                </div>
              </Field>
            )}

            <Field label="Name" required hint="Used as the table name in SQL, so letters, digits and underscores only.">
              <input className="input mono" value={name} disabled={!!editing}
                     onChange={(e) => setName(e.target.value)} placeholder="events_raw" />
            </Field>

            <Field label="Description">
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)}
                     placeholder="What this reads from, in plain words" />
            </Field>

            <div className="sm:col-span-2"><Field label="Connector" required>
              <ConnectorPicker
                connectors={available}
                value={connectorId}
                onChange={chooseConnector}
                disabled={!!editing}
              />
            </Field></div>
          </div>

          {connector && (
            <>
              <div className="form-section">
                <h2 className="font-medium text-slate-900 mb-4">Connection</h2>
                <ConnectorForm
                  connector={connector}
                  values={values}
                  onChange={(k, v) => setValues((prev) => ({ ...prev, [k]: v }))}
                  secretNames={secretNames}
                />

                <HealthCheck connector={connectorId} options={values} />

                {kind === 'source' && (
                  <SourcePeek connector={connectorId} options={values}
                              columns={columns} name={name} />
                )}
              </div>

              <div className="form-section">
                <h2 className="font-medium text-slate-900 mb-1">Columns</h2>
                <p className="text-xs text-slate-500 mb-4">
                  The shape of each record. The connector pre-fills what it expects.
                </p>
                <ColumnEditor columns={columns} onChange={setColumns} declared={connector.columns} />

                {/* Only for Avro, where the columns are a contract rather than a
                    convenience, and only when there is a registry to ask. */}
                {String(values.format || '').startsWith('avro') && (
                  <SchemaFill topic={values.topic} onColumns={setColumns} />
                )}
              </div>
            </>
          )}
        </div>

        <aside className="space-y-4">
          {editing && (
            <div className="border-b border-slate-200 pb-4">
              <Field label="Change note"
                     hint="Included in version history.">
                <input className="input" value={note}
                       onChange={(e) => setNote(e.target.value)}
                       placeholder="Pointed at the new topic" />
              </Field>
            </div>
          )}

          {connector?.description && (
            <div className="border-b border-slate-200 pb-4">
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
          <div className="border-b border-slate-200 pb-4">
            <h3 className="text-sm font-medium text-slate-900 mb-2">Generated SQL</h3>
            <p className="text-xs text-slate-500 mb-3">
              A summary of the table definition.
            </p>
            <CodeBlock className="text-xs">
              {connectorId && name
                ? `CREATE TABLE ${name} (\n${columns.map((c) => `  ${c.name || '…'} ${c.sqlType}`).join(',\n')}\n) WITH (\n  'connector' = '${connectorId}',\n  …\n)`
                : 'Choose a connector to see the statement.'}
            </CodeBlock>
          </div>
          {editing && <CatalogHistory name={editing} usedBy={usedBy} />}
        </aside>
      </div>
    </>
  )
}
