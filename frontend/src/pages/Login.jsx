import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { Alert, Field, Spinner } from '../components/ui'

export default function Login() {
  const { user, loading, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  if (loading) return <div className="min-h-screen grid place-items-center"><Spinner /></div>
  if (user) return <Navigate to={location.state?.from?.pathname || '/jobs'} replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate(location.state?.from?.pathname || '/jobs', { replace: true })
    } catch (err) {
      setError(err.message || 'Could not sign in')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen grid place-items-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        <div className="flex items-center gap-2.5 justify-center mb-8">
          <span className="w-9 h-9 rounded-lg bg-brand-600 text-white grid place-items-center font-bold">M</span>
          <div>
            <div className="font-semibold text-slate-900 leading-tight">MARS</div>
            <div className="text-xs text-slate-500">Stream pipelines for Apache Flink®</div>
          </div>
        </div>

        <form onSubmit={submit} className="card p-6 space-y-4">
          {error && <Alert level="danger">{error}</Alert>}
          <Field label="Username">
            <input className="input" value={username} autoFocus autoComplete="username"
                   onChange={(e) => setUsername(e.target.value)} />
          </Field>
          <Field label="Password">
            <input className="input" type="password" value={password} autoComplete="current-password"
                   onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <button className="btn-primary w-full justify-center" disabled={busy || !username || !password}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-xs text-slate-400 text-center mt-4">
          On a new install, the first administrator's password is printed once in the
          server log.
        </p>
      </div>
    </div>
  )
}
