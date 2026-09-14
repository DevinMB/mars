import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from '../lib/auth'

const NAV = [
  { to: '/jobs', label: 'Jobs' },
  { to: '/catalog', label: 'Catalog' },
  { to: '/secrets', label: 'Secrets' },
  { to: '/cluster', label: 'Cluster' },
]

function ClusterDot() {
  const [state, setState] = useState(null)
  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const c = await api.cluster()
        if (alive) setState(c)
      } catch {
        if (alive) setState({ reachable: false })
      }
    }
    poll()
    const t = setInterval(poll, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  if (!state) return null
  return (
    <span className="flex items-center gap-1.5 text-xs text-slate-500" title={
      state.reachable ? `Flink ${state.flink_version}` : 'Flink is not reachable'
    }>
      <span className={`w-2 h-2 rounded-full ${state.reachable ? 'bg-emerald-500' : 'bg-red-500'}`} />
      {state.reachable ? `${state.slots_available}/${state.slots_total} slots` : 'Cluster down'}
    </span>
  )
}

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex flex-col">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-14 gap-4">
            <div className="flex items-center gap-6 min-w-0">
              <NavLink to="/jobs" className="flex items-center gap-2 shrink-0">
                <span className="w-7 h-7 rounded-md bg-brand-600 text-white grid place-items-center
                                 font-bold text-sm">M</span>
                <span className="font-semibold text-slate-900">MARS</span>
              </NavLink>
              <nav className="flex items-center gap-1 overflow-x-auto">
                {NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors ${
                        isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-100'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </nav>
            </div>
            <div className="flex items-center gap-4 shrink-0">
              <ClusterDot />
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-600 hidden sm:inline">{user?.username}</span>
                <button
                  onClick={async () => { await logout(); navigate('/login') }}
                  className="text-sm text-slate-500 hover:text-slate-900"
                >
                  Sign out
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      {user?.must_change_password && (
        <div className="bg-amber-50 border-b border-amber-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2 text-sm text-amber-900">
            This account still uses its generated password.{' '}
            <NavLink to="/account" className="underline font-medium">Change it now</NavLink>.
          </div>
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-8">{children}</main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 text-xs text-slate-400">
          MARS — stream pipelines for Apache Flink®
        </div>
      </footer>
    </div>
  )
}
