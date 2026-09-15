// A line diff, so a proposed statement can be read as a change rather than a
// wall of text. A model asked for a small edit usually makes a small edit, and
// seeing that it made a small edit is most of the reassurance.

function lcs(a, b) {
  // Standard longest-common-subsequence table. Statements are tens of lines, so
  // the quadratic table is irrelevant here and the clarity is worth more.
  const m = a.length
  const n = b.length
  const table = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i -= 1) {
    for (let j = n - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j]
        ? table[i + 1][j + 1] + 1
        : Math.max(table[i + 1][j], table[i][j + 1])
    }
  }
  return table
}

export function diffLines(before, after) {
  const a = (before || '').split('\n')
  const b = (after || '').split('\n')
  if (!before) return b.map((text) => ({ kind: 'add', text }))

  const table = lcs(a, b)
  const out = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i] }); i += 1; j += 1
    } else if (table[i + 1][j] >= table[i][j + 1]) {
      out.push({ kind: 'remove', text: a[i] }); i += 1
    } else {
      out.push({ kind: 'add', text: b[j] }); j += 1
    }
  }
  while (i < a.length) { out.push({ kind: 'remove', text: a[i] }); i += 1 }
  while (j < b.length) { out.push({ kind: 'add', text: b[j] }); j += 1 }
  return out
}

const STYLE = {
  add: 'bg-emerald-50 text-emerald-900',
  remove: 'bg-red-50 text-red-900 line-through decoration-red-300',
  same: 'text-slate-600',
}
const SIGN = { add: '+', remove: '−', same: ' ' }

export default function SqlDiff({ before, after }) {
  const lines = diffLines(before, after)
  const added = lines.filter((l) => l.kind === 'add').length
  const removed = lines.filter((l) => l.kind === 'remove').length
  const unchanged = lines.filter((l) => l.kind === 'same').length

  return (
    <div>
      <div className="flex items-center gap-3 text-xs text-slate-500 mb-1">
        {before ? (
          <>
            <span className="text-emerald-700">+{added}</span>
            <span className="text-red-700">−{removed}</span>
            <span>{unchanged} unchanged</span>
          </>
        ) : (
          <span>{added} lines</span>
        )}
      </div>
      <div className="border border-slate-200 rounded-md overflow-hidden">
        <pre className="mono text-xs overflow-x-auto max-h-80 overflow-y-auto">
          {lines.map((line, i) => (
            <div key={i} className={`px-3 py-0.5 ${STYLE[line.kind]}`}>
              <span className="select-none text-slate-400 mr-2">{SIGN[line.kind]}</span>
              {line.text || ' '}
            </div>
          ))}
        </pre>
      </div>
    </div>
  )
}
