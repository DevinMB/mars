import { useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import MarsMark from '../components/MarsMark'
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
          <div className="w-16 h-16 rounded-2xl bg-code-bg grid place-items-center
                          shadow-card mb-3">
            <MarsMark size={42} title="MARS" />
          </div>
          <div className="text-center">
            <div className="text-lg font-semibold text-slate-900 tracking-tight leading-tight">
              MARS
            </div>
            <div className="text-[12px] text-slate-500">Stream pipelines for Apache Flink®</div>
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

        <details className="text-xs text-slate-500 text-center mt-5">
          <summary className="cursor-pointer">First time signing in?</summary>
          <p className="mt-2 leading-relaxed">Find the initial administrator password in the server log, or ask your administrator for an account.</p>
        </details>
      </div>
    </div>
  )
}
