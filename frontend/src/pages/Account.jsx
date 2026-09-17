import { useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Alert, Field, PageHeader } from '../components/ui'

export default function Account() {
  const { user, refresh } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError(null)
    if (next !== confirm) { setError('The two new passwords do not match.'); return }
    setBusy(true)
    try {
      await api.changePassword(current, next)
      setDone(true)
      setCurrent(''); setNext(''); setConfirm('')
      await refresh()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <PageHeader title="Account" subtitle={`Signed in as ${user?.username} (${user?.role})`} />
      <div className="max-w-md space-y-4">
        {done && <Alert level="success" onDismiss={() => setDone(false)}>Password changed.</Alert>}
        {error && <Alert level="danger" onDismiss={() => setError(null)}>{error}</Alert>}
        {user?.must_change_password && !done && (
          <Alert level="warning">
            Replace your generated password with one of your own.
          </Alert>
        )}
        <form onSubmit={submit} className="card p-6 space-y-4">
          <Field label="Current password">
            <input className="input" type="password" value={current} autoComplete="current-password"
                   onChange={(e) => setCurrent(e.target.value)} />
          </Field>
          <Field label="New password" hint="At least 12 characters.">
            <input className="input" type="password" value={next} autoComplete="new-password"
                   onChange={(e) => setNext(e.target.value)} />
          </Field>
          <Field label="Confirm new password">
            <input className="input" type="password" value={confirm} autoComplete="new-password"
                   onChange={(e) => setConfirm(e.target.value)} />
          </Field>
          <button className="btn-primary" disabled={busy || !current || next.length < 12}>
            {busy ? 'Changing…' : 'Change password'}
          </button>
        </form>
      </div>
    </>
  )
}
