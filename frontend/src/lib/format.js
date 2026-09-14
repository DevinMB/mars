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
