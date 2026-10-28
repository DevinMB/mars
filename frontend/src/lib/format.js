// A timestamp with no zone is UTC. The API always sends one now, but a naive
// string reaches Date() as *local* time, which silently shifts everything by the
// viewer's offset -- that is what made every job read as having last run "in the
// future". Cheap to guard against a recurrence.
function parse(iso) {
  if (!iso) return NaN
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso)
  return new Date(hasZone ? iso : `${iso}Z`).getTime()
}

export function relativeTime(iso) {
  if (!iso) return '—'
  const then = parse(iso)
  if (Number.isNaN(then)) return '—'
  const secs = Math.round((Date.now() - then) / 1000)
  // A clock skew of a few seconds between server and viewer is normal.
  if (secs < -5) return 'in the future'
  if (secs < 0) return 'just now'
  if (secs < 45) return `${secs}s ago`
  const mins = Math.round(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.round(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

export function duration(fromIso, toIso) {
  if (!fromIso) return '—'
  const from = parse(fromIso)
  const to = toIso ? parse(toIso) : Date.now()
  const secs = Math.max(0, Math.round((to - from) / 1000))
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ${secs % 60}s`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

export function bytes(n) {
  if (n === null || n === undefined) return '—'
  if (n < 1024) return `${n} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let v = n / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1 }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`
}

export function millis(ms) {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const secs = ms / 1000
  if (secs < 60) return `${secs < 10 ? secs.toFixed(1) : Math.round(secs)}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ${Math.round(secs % 60)}s`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

export function count(n) {
  if (n === null || n === undefined) return '—'
  if (n < 1000) return `${n}`
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
  return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0)}M`
}

// Flink reports rates as floats that are frequently 0 on an idle stream; "0/s"
// is a real answer and must not be shown as "no data".
export function rate(n) {
  if (n === null || n === undefined) return '—'
  if (n === 0) return '0/s'
  if (n < 1) return `${n.toFixed(2)}/s`
  if (n < 1000) return `${n < 10 ? n.toFixed(1) : Math.round(n)}/s`
  return `${count(Math.round(n))}/s`
}

export function percent(ratio) {
  if (ratio === null || ratio === undefined) return '—'
  return `${Math.round(ratio * 100)}%`
}

// The common cron shapes in words, so a list reads "Hourly" rather than
// `0 * * * *`. Anything unusual comes back as the expression itself: a wrong
// paraphrase of a schedule is worse than the raw one.
const DAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
export function cronText(expr) {
  const parts = (expr || '').trim().split(/\s+/)
  if (parts.length !== 5) return expr || ''
  const [min, hour, dom, mon, dow] = parts
  const num = (v, max) => /^\d+$/.test(v) && Number(v) <= max
  const at = () => `${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (dom !== '*' || mon !== '*') return expr
  if (min === '*' && hour === '*' && dow === '*') return 'Every minute'
  const step = /^\*\/(\d+)$/.exec(min)
  if (step && hour === '*' && dow === '*') return `Every ${step[1]} minutes`
  if (num(min, 59) && hour === '*' && dow === '*') return min === '0' ? 'Hourly' : `Hourly at :${min.padStart(2, '0')}`
  if (num(min, 59) && num(hour, 23) && dow === '*') return `Daily at ${at()}`
  if (num(min, 59) && num(hour, 23) && num(dow, 7)) return `${DAYS[Number(dow) % 7]}s at ${at()}`
  return expr
}
