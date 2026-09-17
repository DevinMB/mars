import { useConfirm } from '../components/InteractionProvider'
import { Fragment, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { relativeTime } from '../lib/format'
import ActionMenu from '../components/ActionMenu'
import SecretOnce from '../components/SecretOnce'
import { Alert, Badge, Field, PageHeader, Spinner } from '../components/ui'

// What each role can actually do, stated where the choice is made. "Editor" and
// "viewer" are not self-explanatory, and picking the wrong one is only discovered
// when somebody cannot do their job.
const ROLES = [
  {
    value: 'admin',
    label: 'Administrator',
    blurb: 'Everything, including secrets, execution targets and other accounts.',
  },
  {
    value: 'editor',
    label: 'Editor',
    blurb: 'Create and run jobs, edit the catalog. Cannot read or add secrets.',
  },
  {
    value: 'viewer',
    label: 'Viewer',
    blurb: 'Read-only. Can see jobs, runs and the catalog; cannot change anything.',
  },
]

function NewUserForm({ onCreated, onCancel }) {
  const [username, setUsername] = useState('')
  const [role, setRole] = useState('editor')
  const [password, setPassword] = useState('')
  const [generate, setGenerate] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const out = await api.createUser({
        username,
        role,
        password: generate ? null : password,
      })
      onCreated(out)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="card p-5 mb-4">
      <h2 className="eyebrow-accent mb-4">New account</h2>
      {error && <div className="mb-3"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Username" required>
          <input
            className="input mono"
            value={username}
            autoFocus
            placeholder="devin"
            onChange={(e) => setUsername(e.target.value.replace(/[^a-zA-Z0-9_.-]/g, ''))}
          />
        </Field>

        <Field label="Role" required hint={ROLES.find((r) => r.value === role)?.blurb}>
          <select className="input" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r.value} value={r.value}>{r.label}</option>
            ))}
          </select>
        </Field>

        <div className="sm:col-span-2 space-y-2">
          <label className="inline-flex items-center gap-2 text-[13px] text-slate-700">
            <input type="checkbox" checked={generate} onChange={(e) => setGenerate(e.target.checked)}
                   className="rounded border-slate-300 text-brand-600 focus:ring-brand-500/30" />
            Generate a password
            <span className="text-[11px] text-slate-400">
              (shown once; they are asked to change it)
            </span>
          </label>
          {!generate && (
            <Field label="Password" hint="At least 12 characters.">
              <input className="input" type="password" value={password}
                     onChange={(e) => setPassword(e.target.value)} />
            </Field>
          )}
        </div>
      </div>

      <div className="flex gap-2 mt-4">
        <button className="btn-primary"
                disabled={busy || !username || (!generate && password.length < 12)}>
          {busy ? 'Creating…' : 'Create account'}
        </button>
        <button type="button" className="btn-secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

function TokenPanel({ username, onIssued }) {
  const confirm = useConfirm()
  const [tokens, setTokens] = useState(null)
  const [name, setName] = useState('')
  const [error, setError] = useState(null)

  const load = async () => {
    try { setTokens(await api.userTokens(username)) } catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [username])

  const issue = async () => {
    setError(null)
    try {
      const out = await api.createUserToken(username, { name })
      setName('')
      onIssued(out)
      await load()
    } catch (err) { setError(err.message) }
  }

  const revoke = async (n) => {
    if (!await confirm(`Revoke token "${n}"? Anything using it stops working immediately.`)) return
    try { await api.revokeUserToken(username, n); await load() } catch (err) { setError(err.message) }
  }

  return (
    <div className="bg-slate-50 border-t border-slate-200 px-4 py-3">
      <div className="eyebrow mb-2">API tokens for {username}</div>
      {error && <div className="mb-2"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {tokens === null ? (
        <Spinner label="Loading" />
      ) : tokens.length === 0 ? (
        <p className="text-[12px] text-slate-500 mb-2">
          None. A token lets automation act as this account, sent as
          {' '}<code className="mono">Authorization: Bearer …</code>
        </p>
      ) : (
        <table className="tbl mb-2 bg-surface rounded border border-slate-200">
          <thead><tr><th>Name</th><th>Prefix</th><th>Last used</th><th></th></tr></thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.name}>
                <td className="text-slate-800">{t.name}</td>
                <td><code className="mono text-[11px] text-slate-500">{t.prefix}…</code></td>
                <td className="text-slate-500">{t.last_used_at ? relativeTime(t.last_used_at) : 'never'}</td>
                <td className="text-right">
                  <button onClick={() => revoke(t.name)}
                          className="text-slate-400 hover:text-red-600 text-[12px]">Revoke</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="flex gap-2">
        <input className="input max-w-xs" aria-label="Token name" value={name} placeholder="What is it for? e.g. ci"
               onChange={(e) => setName(e.target.value)} />
        <button className="btn-secondary" disabled={!name} onClick={issue}>Issue token</button>
      </div>
    </div>
  )
}

export default function Admin() {
  const confirm = useConfirm()
  const { user: me } = useAuth()
  const [users, setUsers] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [adding, setAdding] = useState(false)
  const [secret, setSecret] = useState(null)   // { label, value }
  const [expanded, setExpanded] = useState(null)

  const load = async () => {
    try { setUsers(await api.users()); setError(null) } catch (err) { setError(err.message) }
  }
  useEffect(() => { load() }, [])

  const act = async (fn) => {
    setBusy(true); setError(null)
    try { await fn(); await load() } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  if (error && !users) return <Alert level="danger" title="Could not load accounts">{error}</Alert>
  if (!users) return <Spinner label="Loading accounts" />

  const admins = users.filter((u) => u.role === 'admin' && !u.disabled).length

  return (
    <>
      <PageHeader
        title="Accounts"
        subtitle={`${users.length} account${users.length === 1 ? '' : 's'}, ${admins} administrator${admins === 1 ? '' : 's'}`}
        actions={!adding && <button className="btn-primary" onClick={() => setAdding(true)}>New account</button>}
      />

      {error && <div className="mb-4"><Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert></div>}

      {secret && (
        <SecretOnce label={secret.label} value={secret.value} onDone={() => setSecret(null)} />
      )}


      {adding && (
        <NewUserForm
          onCancel={() => setAdding(false)}
          onCreated={async (out) => {
            setAdding(false)
            if (out.password) {
              setSecret({ label: `Password for ${out.username}`, value: out.password })
            }
            await load()
          }}
        />
      )}

      {/* Only while it is true. Once a second administrator exists the point is
          made and the banner is just noise on every visit. */}
      {admins === 1 && (
        <div className="mb-4">
          <Alert level="warning">
            <span className="font-medium">There is only one administrator.</span>{' '}
            If this account is lost, recovering access needs a shell on the host.
          </Alert>
        </div>
      )}

      <div className="table-scroll">
        <table className="tbl">
          <thead>
            <tr><th>Account</th><th>Role</th><th>State</th><th>Last sign-in</th><th>Tokens</th><th></th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <Fragment key={u.username}>
                <tr>
                  <td>
                    <span className="mono text-slate-900">{u.username}</span>
                    {u.is_self && <span className="ml-2 text-[11px] text-slate-400">you</span>}
                  </td>
                  <td>
                    <select
                      className="input py-1 text-[12px] max-w-[9.5rem]"
                      aria-label={`Role for ${u.username}`}
                      disabled={busy}
                      value={u.role}
                      onChange={(e) => act(() => api.updateUser(u.username, { role: e.target.value }))}
                    >
                      {ROLES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
                    </select>
                  </td>
                  <td>
                    {u.disabled ? <Badge>disabled</Badge>
                      : u.must_change_password ? <Badge tone="accent">must change password</Badge>
                      : <span className="text-slate-500 text-[12px]">active</span>}
                  </td>
                  <td className="text-slate-500">
                    {u.last_login_at ? relativeTime(u.last_login_at) : 'never'}
                  </td>
                  <td className="text-slate-500 tabular-nums">{u.token_count}</td>
                  <td className="text-right whitespace-nowrap">
                    <ActionMenu label={<><span className="sr-only">Actions for {u.username}</span><span aria-hidden="true">More</span></>}>
                    <button
                      className="link text-[12px] mr-3"
                      onClick={() => setExpanded(expanded === u.username ? null : u.username)}
                    >
                      Tokens
                    </button>
                    <button
                      className="link text-[12px] mr-3"
                      onClick={() => act(async () => {
                        if (!await confirm(`Reset the password for ${u.username}? Their current sessions end.`)) return
                        const out = await api.resetUserPassword(u.username)
                        setSecret({ label: `New password for ${out.username}`, value: out.password })
                      })}
                    >
                      Reset password
                    </button>
                    <button
                      className="text-slate-500 hover:text-slate-800 text-[12px] mr-3"
                      disabled={busy || u.is_self || (!u.disabled && u.role === 'admin' && admins === 1)}
                      onClick={() => act(() => api.updateUser(u.username, { disabled: !u.disabled }))}
                    >
                      {u.disabled ? 'Enable' : 'Disable'}
                    </button>
                    <button
                      className="text-slate-400 hover:text-red-600 text-[12px]"
                      disabled={busy || u.is_self || (u.role === 'admin' && !u.disabled && admins === 1)}
                      onClick={() => act(async () => {
                        if (!await confirm(`Delete ${u.username}? Their API tokens stop working.`)) return
                        await api.deleteUser(u.username)
                      })}
                    >
                      Delete
                    </button>
                    </ActionMenu>
                  </td>
                </tr>
                {expanded === u.username && (
                  <tr key={`${u.username}-tokens`}>
                    <td colSpan={6} className="p-0">
                      <TokenPanel
                        username={u.username}
                        onIssued={(t) => setSecret({ label: `API token "${t.name}" for ${u.username}`, value: t.token })}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-6 text-[12px] text-slate-500 max-w-2xl space-y-1.5">
        <p className="eyebrow-accent">What the roles mean</p>
        {ROLES.map((r) => (
          <p key={r.value}>
            <span className="font-medium text-slate-700">{r.label}</span> — {r.blurb}
          </p>
        ))}
      </div>
    </>
  )
}
