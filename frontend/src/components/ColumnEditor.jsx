import { Badge } from './ui'
import TypePicker from './TypePicker'

// Columns a connector declares are pre-filled and explained; extra ones can be
// added freely, because the manifest describes a contract, not a limit.
export default function ColumnEditor({ columns, onChange, declared = [] }) {
  const declaredByName = Object.fromEntries(declared.map((c) => [c.name, c]))

  const update = (i, patch) =>
    onChange(columns.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))
  const remove = (i) => onChange(columns.filter((_, idx) => idx !== i))
  const add = () => onChange([...columns, { name: '', sqlType: 'STRING' }])

  return (
    <div className="space-y-2">
      {columns.map((col, i) => {
        const spec = declaredByName[col.name]
        return (
          <div key={i} className="flex flex-wrap sm:flex-nowrap items-start gap-2">
            <div className="flex-1 min-w-28">
              <input
                className="input mono"
                placeholder="column_name"
                aria-label={`Column ${i + 1} name`}
                value={col.name}
                onChange={(e) => update(i, { name: e.target.value })}
              />
              {spec?.help && <p className="hint">{spec.help}</p>}
            </div>
            <TypePicker
              value={col.sqlType}
              onChange={(sqlType) => update(i, { sqlType })}
            />
            <div className="pt-2 w-20 shrink-0">
              {spec?.required ? (
                <Badge tone="blue">required</Badge>
              ) : (
                <button
                  type="button"
                  onClick={() => remove(i)}
                  className="text-slate-400 hover:text-red-600 text-sm"
                  aria-label={`Remove ${col.name || 'column'}`}
                >
                  Remove
                </button>
              )}
            </div>
          </div>
        )
      })}
      <button type="button" onClick={add} className="btn-secondary text-sm">
        + Add column
      </button>
    </div>
  )
}
