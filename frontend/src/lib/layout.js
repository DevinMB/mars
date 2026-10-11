// Lays out a directed graph left to right, in columns.
//
// The standard layered approach, small enough to own:
// 1. Break cycles (a job reading and writing one topic) by ignoring back edges.
// 2. Column = the longest path from any node with no inputs, so data flows right.
// 3. Order within each column by the average position of neighbours, swept left
//    to right and back a few times, which removes most crossings.
//
// Returns { positions: Map(id -> {x, y, col}), width, height }.
export function layoutGraph(nodes, edges, { colWidth = 230, rowHeight = 64, sizeOf } = {}) {
  const ids = nodes.map((n) => n.id)
  const out = new Map(ids.map((id) => [id, []]))
  const inc = new Map(ids.map((id) => [id, []]))
  for (const e of edges) {
    if (out.has(e.from) && inc.has(e.to)) { out.get(e.from).push(e.to); inc.get(e.to).push(e.from) }
  }

  // 1. Back edges found by depth-first search are left out of the ranking.
  const back = new Set()
  const state = new Map()
  const visit = (id) => {
    state.set(id, 'open')
    for (const next of out.get(id)) {
      if (state.get(next) === 'open') back.add(`${id}>${next}`)
      else if (!state.has(next)) visit(next)
    }
    state.set(id, 'done')
  }
  for (const id of ids) if (!state.has(id)) visit(id)
  const forward = (a, b) => !back.has(`${a}>${b}`)

  // 2. Longest path from the sources, in topological order.
  const col = new Map(ids.map((id) => [id, 0]))
  const indegree = new Map(ids.map((id) => [id, inc.get(id).filter((p) => forward(p, id)).length]))
  const queue = ids.filter((id) => indegree.get(id) === 0)
  while (queue.length) {
    const id = queue.shift()
    for (const next of out.get(id)) {
      if (!forward(id, next)) continue
      col.set(next, Math.max(col.get(next), col.get(id) + 1))
      indegree.set(next, indegree.get(next) - 1)
      if (indegree.get(next) === 0) queue.push(next)
    }
  }
  // Pull each node rightwards to just before its first reader, so a source that
  // feeds a late job does not sit far left with a long edge.
  for (let pass = 0; pass < 2; pass += 1) {
    for (const id of [...ids].sort((a, b) => col.get(b) - col.get(a))) {
      const readers = out.get(id).filter((n) => forward(id, n))
      if (readers.length && inc.get(id).every((p) => !forward(p, id))) {
        col.set(id, Math.max(col.get(id), Math.min(...readers.map((n) => col.get(n))) - 1))
      }
    }
  }

  // 3. Order within columns by neighbour barycentre.
  const columns = []
  for (const id of ids) (columns[col.get(id)] ||= []).push(id)
  const order = new Map()
  const reindex = () => columns.forEach((c) => c?.forEach((id, i) => order.set(id, i)))
  reindex()
  // Median rather than mean: one far-off neighbour should not drag a node away
  // from where the rest of its neighbours are.
  const centre = (id, neighbours) => {
    const ns = neighbours.get(id).map((n) => order.get(n)).filter((v) => v !== undefined).sort((a, b) => a - b)
    if (!ns.length) return order.get(id)
    const m = Math.floor(ns.length / 2)
    return ns.length % 2 ? ns[m] : (ns[m - 1] + ns[m]) / 2
  }
  // Ends on a left-to-right sweep, so each column follows what feeds it.
  for (let sweep = 7; sweep >= 0; sweep -= 1) {
    const down = sweep % 2 === 0
    const seq = down ? [...columns.keys()] : [...columns.keys()].reverse()
    for (const i of seq) {
      const c = columns[i]
      if (!c) continue
      const by = new Map(c.map((id) => [id, centre(id, down ? inc : out)]))
      c.sort((a, b) => by.get(a) - by.get(b) || order.get(a) - order.get(b))
      reindex()
    }
  }

  // Then swap neighbours wherever that removes crossings with either side.
  const crossings = (u, v) => {
    // Edges of u and v to one neighbouring column cross when their ends are inverted.
    let n = 0
    for (const nb of [inc, out]) {
      for (const a of nb.get(u)) for (const b of nb.get(v)) if (order.get(a) > order.get(b)) n += 1
    }
    return n
  }
  for (let round = 0, improved = true; improved && round < 12; round += 1) {
    improved = false
    for (const c of columns) {
      if (!c) continue
      for (let k = 0; k < c.length - 1; k += 1) {
        const [u, v] = [c[k], c[k + 1]]
        if (crossings(u, v) > crossings(v, u)) {
          c[k] = v; c[k + 1] = u
          order.set(v, k); order.set(u, k + 1)
          improved = true
        }
      }
    }
  }

  // 4. Heights: each node aims for the average height of its neighbours in the
  // column it is placed against, then is pushed down to keep one row apart. A
  // pass left to right lines readers up with writers; a pass back lines up
  // sources with the first thing that reads them.
  const y = new Map()
  columns.forEach((c) => c?.forEach((id, j) => y.set(id, j * rowHeight)))
  const settle = (c, want) => {
    let floor = -Infinity
    for (const id of c) {
      const target = want(id)
      y.set(id, Math.max(target ?? y.get(id), floor))
      floor = y.get(id) + rowHeight
    }
  }
  const avg = (list) => (list.length ? list.reduce((s, n) => s + y.get(n), 0) / list.length : null)
  for (let pass = 0; pass < 2; pass += 1) {
    columns.forEach((c) => c && settle(c, (id) => avg(inc.get(id).filter((n) => forward(n, id)))))
    ;[...columns].reverse().forEach((c) => c && settle(c, (id) =>
      inc.get(id).some((n) => forward(n, id)) ? null : avg(out.get(id).filter((n) => forward(id, n)))))
  }
  const top = Math.min(0, ...y.values())

  const positions = new Map()
  let height = 0
  columns.forEach((c, i) => c?.forEach((id) => {
    const size = sizeOf ? sizeOf(id) : { w: 180, h: 40 }
    const yy = y.get(id) - top
    positions.set(id, { x: i * colWidth, y: yy, col: i, ...size })
    height = Math.max(height, yy + size.h)
  }))
  return { positions, width: Math.max(1, columns.length) * colWidth, height }
}
