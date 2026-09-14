// Thin wrapper over the MARS API. Session auth rides on an httpOnly cookie, so
// there is no token to keep in the browser.

class ApiError extends Error {
  constructor(message, status, detail) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const res = await fetch(path, {
    method,
    signal,
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })

  if (res.status === 204) return null

  let payload = null
  const text = await res.text()
  if (text) {
    try { payload = JSON.parse(text) } catch { payload = { detail: text } }
  }

  if (!res.ok) {
    // FastAPI puts the readable message in `detail`; validation errors put a
    // list there instead, so flatten that into something a human can act on.
    let msg = payload?.detail ?? res.statusText
    if (Array.isArray(msg)) {
      msg = msg.map((e) => `${(e.loc || []).slice(1).join('.')}: ${e.msg}`).join('; ')
    }
    throw new ApiError(msg, res.status, payload)
  }
  return payload
}

export const api = {
  // auth
  login: (username, password) => request('/api/auth/login', { method: 'POST', body: { username, password } }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),
  me: () => request('/api/auth/me'),
  changePassword: (current_password, new_password) =>
    request('/api/auth/password', { method: 'POST', body: { current_password, new_password } }),

  // system
  cluster: () => request('/api/cluster'),
  connectors: (kind) => request(`/api/connectors${kind ? `?kind=${kind}` : ''}`),
  connector: (id) => request(`/api/connectors/${id}`),

  // secrets
  secrets: () => request('/api/secrets'),
  putSecret: (name, value, description) =>
    request(`/api/secrets/${encodeURIComponent(name)}`, { method: 'PUT', body: { name, value, description } }),
  deleteSecret: (name) => request(`/api/secrets/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // catalog
  catalog: (kind) => request(`/api/catalog${kind ? `?kind=${kind}` : ''}`),
  catalogEntry: (name) => request(`/api/catalog/${encodeURIComponent(name)}`),
  createCatalog: (body) => request('/api/catalog', { method: 'POST', body }),
  updateCatalog: (name, body) => request(`/api/catalog/${encodeURIComponent(name)}`, { method: 'PUT', body }),
  deleteCatalog: (name) => request(`/api/catalog/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  checkCatalog: (name) => request(`/api/catalog/${encodeURIComponent(name)}/check`, { method: 'POST' }),

  // targets
  targets: () => request('/api/targets'),
  createTarget: (body) => request('/api/targets', { method: 'POST', body }),
  updateTarget: (name, body) => request(`/api/targets/${encodeURIComponent(name)}`, { method: 'PUT', body }),
  deleteTarget: (name) => request(`/api/targets/${encodeURIComponent(name)}`, { method: 'DELETE' }),

  // jobs
  jobs: () => request('/api/jobs'),
  job: (name) => request(`/api/jobs/${encodeURIComponent(name)}`),
  createJob: (body) => request('/api/jobs', { method: 'POST', body }),
  updateJob: (name, body) => request(`/api/jobs/${encodeURIComponent(name)}`, { method: 'PUT', body }),
  deleteJob: (name) => request(`/api/jobs/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  jobScript: (name) => request(`/api/jobs/${encodeURIComponent(name)}/script`),
  validateJob: (name) => request(`/api/jobs/${encodeURIComponent(name)}/validate`, { method: 'POST' }),
  runJob: (name) => request(`/api/jobs/${encodeURIComponent(name)}/run`, { method: 'POST' }),
  cancelJob: (name) => request(`/api/jobs/${encodeURIComponent(name)}/cancel`, { method: 'POST' }),
  jobRuns: (name) => request(`/api/jobs/${encodeURIComponent(name)}/runs`),
  jobVersions: (name) => request(`/api/jobs/${encodeURIComponent(name)}/versions`),
  setSchedule: (name, body) => request(`/api/jobs/${encodeURIComponent(name)}/schedule`, { method: 'PUT', body }),
  clearSchedule: (name) => request(`/api/jobs/${encodeURIComponent(name)}/schedule`, { method: 'DELETE' }),
}

export { ApiError }
