import { useMemo } from 'react'
import { Field } from './ui'

// Renders a form purely from a connector manifest. Nothing here knows what a
// CouchDB or a Kafka is: the fields, their grouping, which are required, which
// are secret and which only apply in certain modes all come from the manifest
// the connector shipped. Adding a connector adds a form, with no change here.

function visible(option, values) {
  if (!option.visibleWhen) return true
  const current = values[option.visibleWhen.option] ?? defaultOf(option.visibleWhen.option)
  return current === option.visibleWhen.equals
}

function defaultOf() {
  return undefined
}

function OptionInput({ option, value, onChange, secretNames }) {
  const common = {
    id: `opt-${option.key}`,
    'aria-label': option.label,
    className: 'input',
    value: value ?? '',
    placeholder: option.placeholder || option.default || '',
    onChange: (e) => onChange(option.key, e.target.value),
  }

  if (option.type === 'boolean') {
    const checked = String(value ?? option.default ?? 'false') === 'true'
    return (
      <label className="inline-flex items-center gap-2 text-sm text-slate-700">
        <input
          type="checkbox"
          aria-label={option.label}
          checked={checked}
          onChange={(e) => onChange(option.key, e.target.checked ? 'true' : 'false')}
          className="rounded-sm border-slate-300 text-brand-600 focus:ring-brand-500/30"
        />
        {checked ? 'Enabled' : 'Disabled'}
      </label>
    )
  }

  if (option.type === 'enum') {
    // Leaving an optional option unset writes nothing into the DDL, and the
    // connector then applies its own default -- so blank and explicitly choosing
    // the default produce identical SQL. Showing "—" alongside "none (default)"
    // made that look like two different settings. The blank now says what it
    // does, and the choices no longer repeat it.
    return (
      <select {...common}>
        {!option.required && (
          <option value="">
            {option.default ? `Default — ${option.default}` : 'Not set'}
          </option>
        )}
        {option.choices.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>
    )
  }

  if (option.secret) {
    // A secret is entered once under Settings and referenced here, so the value
    // never lands in the job's SQL. The picker keeps people on that path.
    return (
      <div className="space-y-1.5">
        <select
          aria-label={option.label}
          className="input"
          value={value ?? ''}
          onChange={(e) => onChange(option.key, e.target.value)}
        >
          <option value="">Select a secret…</option>
          {secretNames.map((n) => (
            <option key={n} value={`\${secret:${n}}`}>{n}</option>
          ))}
        </select>
        {value && !String(value).startsWith('${secret:') && (
          <p className="text-xs text-amber-700">
            This looks like a literal value. It will be stored in the table definition
            in plain text — use a secret instead.
          </p>
        )}
      </div>
    )
  }

  if (option.type === 'text') {
    return <textarea {...common} rows={3} className="input mono" />
  }

  return <input type={option.type === 'integer' ? 'number' : 'text'} {...common} />
}

export default function ConnectorForm({ connector, values, onChange, secretNames = [] }) {
  const groups = useMemo(() => {
    const out = new Map()
    for (const o of connector.options) {
      if (!out.has(o.group)) out.set(o.group, [])
      out.get(o.group).push(o)
    }
    return [...out.entries()]
  }, [connector])

  return (
    <div className="space-y-6">
      {groups.map(([group, options]) => {
        const shown = options.filter((o) => visible(o, values))
        if (shown.length === 0) return null
        return (
          <fieldset key={group}>
            <legend className="eyebrow-accent mb-3">{group}</legend>
            <div className="grid gap-4 sm:grid-cols-2">
              {shown.map((o) => (
                <div key={o.key} className={o.type === 'text' ? 'sm:col-span-2' : ''}>
                  <Field
                    label={o.label}
                    required={o.required}
                    hint={o.help || (o.default ? `Defaults to ${o.default}` : null)}
                  >
                    <OptionInput
                      option={o}
                      value={values[o.key]}
                      onChange={onChange}
                      secretNames={secretNames}
                    />
                  </Field>
                </div>
              ))}
            </div>
          </fieldset>
        )
      })}
    </div>
  )
}
