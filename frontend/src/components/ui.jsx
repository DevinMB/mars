import { Children, cloneElement, isValidElement, useId } from 'react'
import { Link } from 'react-router-dom'

export function PageHeader({ title, subtitle, actions, back }) {
  // A shared heading and wrapping toolbar for both lists and editors.
  return (
    <div className="flex flex-col sm:flex-row sm:flex-wrap items-start justify-between gap-4 mb-6">
      <div className="min-w-0 w-full sm:w-auto flex-1">
        {back && (
          <Link to={back.to} className="text-sm text-brand-600 hover:text-brand-700 mb-1 inline-block">
            ← {back.label}
          </Link>
        )}
        <h1 className="text-[24px] font-semibold text-slate-900 tracking-tight break-words">
          {title}
        </h1>
        {subtitle && <p className="text-[13px] text-slate-500 mt-1.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2 max-w-full">{actions}</div>}
    </div>
  )
}

// State is carried by colour *and* by the label, so it reads correctly without
// relying on colour perception.
const STATE_STYLES = {
  running:     'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
  finished:    'bg-slate-100 text-slate-600 ring-slate-500/20',
  restarting:  'bg-amber-50 text-amber-800 ring-amber-600/30',
  failed:      'bg-red-50 text-red-700 ring-red-600/20',
  canceled:    'bg-slate-100 text-slate-500 ring-slate-400/20',
  submitting:  'bg-brand-50 text-brand-700 ring-brand-600/20',
  never:       'bg-surface text-slate-400 ring-slate-300',
}

const STATE_LABELS = {
  running: 'Running',
  finished: 'Finished',
  restarting: 'Restarting',
  failed: 'Failed',
  canceled: 'Cancelled',
  submitting: 'Starting',
  never: 'Never run',
}

export function StatePill({ state }) {
  const key = state || 'never'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs
                      font-medium ring-1 ring-inset ${STATE_STYLES[key] || STATE_STYLES.never}`}>
      {key === 'running' && <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />}
      {key === 'restarting' && <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />}
      {STATE_LABELS[key] || key}
    </span>
  )
}

export function Badge({ children, tone = 'slate' }) {
  const tones = {
    slate: 'bg-slate-100 text-slate-600',
    blue: 'bg-brand-50 text-brand-700',
    accent: 'bg-accent-50 text-accent-800 ring-1 ring-inset ring-accent-200',
    amber: 'bg-amber-50 text-amber-800',
  }
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${tones[tone]}`}>{children}</span>
}

export function Alert({ level = 'info', title, children, onDismiss }) {
  const styles = {
    info: 'bg-brand-50 border-brand-200 text-brand-900',
    warning: 'bg-amber-50 border-amber-200 text-amber-900',
    danger: 'bg-red-50 border-red-200 text-red-900',
    success: 'bg-emerald-50 border-emerald-200 text-emerald-900',
  }
  return (
    <div role={level === 'danger' ? 'alert' : 'status'} className={`border rounded-md px-4 py-3 text-sm ${styles[level] || styles.info}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          {title && <div className="font-semibold mb-0.5">{title}</div>}
          <div className="break-words">{children}</div>
        </div>
        {onDismiss && (
          <button onClick={onDismiss} className="text-current/60 hover:text-current shrink-0" aria-label="Dismiss">
            ×
          </button>
        )}
      </div>
    </div>
  )
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="card p-12 text-center">
      <h3 className="text-base font-medium text-slate-900">{title}</h3>
      <p className="text-sm text-slate-500 mt-1 max-w-md mx-auto">{children}</p>
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function Spinner({ label = 'Loading' }) {
  return (
    <div className="flex items-center gap-2 text-sm text-slate-500 py-8 justify-center">
      <span className="w-4 h-4 border-2 border-slate-300 border-t-brand-600 rounded-full animate-spin" />
      {label}…
    </div>
  )
}

export function Field({ label, hint, error, required, children }) {
  const generated = useId()
  const child = Children.count(children) === 1 && isValidElement(children) ? children : null
  const direct = child && ['input', 'select', 'textarea'].includes(child.type)
  const id = child?.props.id || generated
  const description = hint || error ? `${generated}-description` : undefined
  const content = direct ? cloneElement(child, { id, 'aria-describedby': description,
    'aria-invalid': error ? true : undefined, 'aria-required': required || undefined }) : children
  const Tag = direct ? 'div' : 'fieldset'
  const Label = direct ? 'label' : 'legend'
  return (
    <Tag className="min-w-0">
      <Label className="label" htmlFor={direct ? id : undefined}>
        {label}{required && <span className="text-red-600 ml-0.5" aria-hidden="true">*</span>}
      </Label>
      {content}
      {error ? <p id={description} className="text-xs text-red-600 mt-1">{error}</p>
        : hint ? <p id={description} className="hint">{hint}</p> : null}
    </Tag>
  )
}

export function CodeBlock({ children, className = '' }) {
  return (
    <pre className={`mono bg-code-bg text-code-fg rounded-md p-4 overflow-x-auto
                     leading-relaxed ${className}`}>
      {children}
    </pre>
  )
}
