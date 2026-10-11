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
    headers: { 'X-MARS-Request': '1', ...(body ? { 'Content-Type': 'application/json' } : {}) },
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
  catalogVersions: (name) =>
    request(`/api/catalog/${encodeURIComponent(name)}/versions`),
  sampleDraft: (body) => request('/api/catalog/sample', { method: 'POST', body }),
  checkHealth: (connector, options) =>
    request('/api/catalog/health', { method: 'POST', body: { connector, options } }),
  checkEntryHealth: (name) =>
    request(`/api/catalog/${encodeURIComponent(name)}/health`, { method: 'POST' }),
  sampleEntry: (name, limit = 5, start = 'earliest') =>
    request(`/api/catalog/${encodeURIComponent(name)}/sample?limit=${limit}&start=${start}`,
            { method: 'POST' }),
  catalogEntry: (name) => request(`/api/catalog/${encodeURIComponent(name)}`),
  createCatalog: (body) => request('/api/catalog', { method: 'POST', body }),
  updateCatalog: (name, body) => request(`/api/catalog/${encodeURIComponent(name)}`, { method: 'PUT', body }),
  deleteCatalog: (name) => request(`/api/catalog/${encodeURIComponent(name)}`, { method: 'DELETE' }),
  checkCatalog: (name) => request(`/api/catalog/${encodeURIComponent(name)}/check`, { method: 'POST' }),

  // users
  users: () => request('/api/users'),
  createUser: (body) => request('/api/users', { method: 'POST', body }),
  updateUser: (username, body) =>
    request(`/api/users/${encodeURIComponent(username)}`, { method: 'PATCH', body }),
  resetUserPassword: (username) =>
    request(`/api/users/${encodeURIComponent(username)}/password`, { method: 'POST' }),
  deleteUser: (username) =>
    request(`/api/users/${encodeURIComponent(username)}`, { method: 'DELETE' }),
  userTokens: (username) => request(`/api/users/${encodeURIComponent(username)}/tokens`),
  createUserToken: (username, body) =>
    request(`/api/users/${encodeURIComponent(username)}/tokens`, { method: 'POST', body }),
  revokeUserToken: (username, name) =>
    request(`/api/users/${encodeURIComponent(username)}/tokens/${encodeURIComponent(name)}`,
            { method: 'DELETE' }),

  // schema registry
  schemaRegistry: () => request('/api/schema-registry'),
  setSchemaRegistry: (body) => request('/api/schema-registry', { method: 'PUT', body }),
  testSchemaRegistry: (body) => request('/api/schema-registry/test', { method: 'POST', body }),
  registrySubjects: () => request('/api/schema-registry/subjects'),
  registrySchema: (subject) =>
    request(`/api/schema-registry/subjects/${encodeURIComponent(subject)}`),

  // backup and restore
  // The export is YAML, not JSON, so it bypasses the usual helper.
  exportDefinitions: async () => {
    const res = await fetch('/api/export', { credentials: 'same-origin' })
    if (!res.ok) throw new Error(`Export failed (${res.status})`)
    return res.text()
  },
  importDefinitions: (body) => request('/api/import', { method: 'POST', body }),

  // ai
  aiProvider: () => request('/api/ai'),
  setAiProvider: (body) => request('/api/ai', { method: 'PUT', body }),
  testAiProvider: (body) => request('/api/ai/test', { method: 'POST', body }),

  // targets
  targets: () => request('/api/targets'),
  version: () => request('/api/system/version'),
  pipeline: () => request('/api/pipeline'),
  addExternal: (body) => request('/api/pipeline/external', { method: 'POST', body }),
  removeExternal: (id) => request(`/api/pipeline/external/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  checkForUpdates: () => request('/api/system/version/check', { method: 'POST' }),
  clusterSetup: (slots = 8) => request(`/api/targets/setup?slots=${encodeURIComponent(slots)}`),
  createTarget: (body) => request('/api/targets', { method: 'POST', body }),
  savepointStorage: () => request('/api/targets/storage'),
  checkSavepointStorage: (a, b) => request('/api/targets/storage/check', { method: 'POST', body: { a, b } }),
  jobMovesOff: (cluster) => request('/api/targets/storage/off', { method: 'POST', body: { cluster } }),
  nfsExports: (server) => request(`/api/targets/storage/exports?server=${encodeURIComponent(server)}`),
  savepointStorageSetup: (server, exportPath) =>
    request(`/api/targets/storage/setup?server=${encodeURIComponent(server)}&export=${encodeURIComponent(exportPath)}`),
  probeTarget: (flink_rest_url, gateway_url) =>
    request('/api/targets/probe', { method: 'POST', body: { flink_rest_url, gateway_url } }),
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
  validateDraft: (body) => request('/api/jobs/validate', { method: 'POST', body }),
  draftJob: (body) => request('/api/jobs/draft', { method: 'POST', body }),
  previewJob: (body) => request('/api/jobs/preview', { method: 'POST', body }),
  runJob: (name, fromSavepoint = 'latest') =>
    request(`/api/jobs/${encodeURIComponent(name)}/run?from_savepoint=${encodeURIComponent(fromSavepoint)}`,
            { method: 'POST' }),
  cancelJob: (name) => request(`/api/jobs/${encodeURIComponent(name)}/cancel`, { method: 'POST' }),
  stopJob: (name, drain = false) =>
    request(`/api/jobs/${encodeURIComponent(name)}/stop?drain=${drain}`, { method: 'POST' }),
  activity: (limit = 200) => request(`/api/jobs/activity?limit=${limit}`),
  acknowledgeRun: (runId, undo = false) =>
    request(`/api/jobs/activity/${runId}/acknowledge?undo=${undo}`, { method: 'POST' }),
  jobRuns: (name) => request(`/api/jobs/${encodeURIComponent(name)}/runs`),
  jobVersions: (name) => request(`/api/jobs/${encodeURIComponent(name)}/versions`),
  jobDiagnostics: (name) => request(`/api/jobs/${encodeURIComponent(name)}/diagnostics`),
  setSchedule: (name, body) => request(`/api/jobs/${encodeURIComponent(name)}/schedule`, { method: 'PUT', body }),
  clearSchedule: (name) => request(`/api/jobs/${encodeURIComponent(name)}/schedule`, { method: 'DELETE' }),
}

export { ApiError }
