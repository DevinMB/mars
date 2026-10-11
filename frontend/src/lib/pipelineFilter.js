// Narrows the pipeline graph to the part someone is looking at.
//
// cluster: keep that cluster's jobs, and the topics, tables and outside systems
//   connected to them.
// focus: a node id; keep it and everything upstream and downstream of it, the
//   pipeline it belongs to. Siblings that only share a source are left out:
//   another reader of the same topic is not part of this one's flow.
//
// Returns { nodes, edges, missing }, missing when the focused node is not in
// what the cluster filter left.
export function filterGraph(graph, { cluster = null, focus = null } = {}) {
  let nodes = graph.nodes
  let edges = graph.edges

  if (cluster) {
    const jobs = new Set(nodes.filter((n) => n.type === 'job' && n.cluster === cluster).map((n) => n.id))
    const near = new Set(jobs)
    for (const e of edges) {
      if (jobs.has(e.from)) near.add(e.to)
      if (jobs.has(e.to)) near.add(e.from)
    }
    // Outside systems attach to topics, one step further out.
    for (const e of edges) {
      const ext = (id) => id.startsWith('ext:')
      if (near.has(e.to) && ext(e.from)) near.add(e.from)
      if (near.has(e.from) && ext(e.to)) near.add(e.to)
    }
    nodes = nodes.filter((n) => near.has(n.id) && (n.type !== 'job' || jobs.has(n.id)))
    const kept = new Set(nodes.map((n) => n.id))
    edges = edges.filter((e) => kept.has(e.from) && kept.has(e.to))
  }

  if (focus) {
    if (!nodes.some((n) => n.id === focus)) return { nodes: [], edges: [], missing: true }
    const walk = (start, next) => {
      const seen = new Set([start])
      const queue = [start]
      while (queue.length) {
        const id = queue.shift()
        for (const n of next(id)) if (!seen.has(n)) { seen.add(n); queue.push(n) }
      }
      return seen
    }
    const up = walk(focus, (id) => edges.filter((e) => e.to === id).map((e) => e.from))
    const down = walk(focus, (id) => edges.filter((e) => e.from === id).map((e) => e.to))
    const kept = new Set([...up, ...down])
    nodes = nodes.filter((n) => kept.has(n.id))
    // Only edges along the flow: within the upstream part or the downstream part.
    edges = edges.filter((e) => (up.has(e.from) && up.has(e.to)) || (down.has(e.from) && down.has(e.to)))
  }

  return { nodes, edges, missing: false }
}
