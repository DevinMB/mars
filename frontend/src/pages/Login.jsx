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
        <div className="flex flex-col items-center mb-8">
          <img src="/icon-192.png" alt="MARS" className="w-16 h-16 rounded-2xl shadow-card mb-3" />
          <div className="text-center">
            <div className="text-lg font-semibold text-slate-900 tracking-tight leading-tight">
              MARS
            </div>
            <div className="text-[12px] text-slate-500">Marsden Apache Real-time Streaming</div>
            <div className="mx-auto mt-2 h-0.5 w-10 rounded-full bg-accent-500/70" />
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
