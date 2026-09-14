import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import MarsMark from './MarsMark'
import { useAuth } from '../lib/auth'

const NAV = [
  { to: '/jobs', label: 'Jobs' },
  { to: '/catalog', label: 'Catalog' },
  { to: '/secrets', label: 'Secrets' },
  { to: '/cluster', label: 'Cluster' },
  // Only administrators may manage accounts, so only they are offered the tab.
  // The API enforces it regardless.
  { to: '/admin', label: 'Admin', adminOnly: true },
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

  // Slots are summed across every enabled target, so this reads as fleet capacity
  // rather than the default cluster's. A partially reachable fleet is called out,
  // because otherwise a shrinking number looks like busy rather than broken.
  const total = state.targets_total || 0
  const reachable = state.targets_reachable || 0
  const partial = state.reachable && total > 1 && reachable < total

  const title = !state.reachable
    ? 'No execution target is reachable'
    : partial
      ? `${reachable} of ${total} targets reachable \u2014 capacity shown is only what answered`
      : `Flink ${state.flink_version}` + (total > 1 ? ` across ${total} targets` : '')

  return (
    <span className="flex items-center gap-1.5 text-[12px] text-slate-500" title={title}>
      <span
        className={`w-2 h-2 rounded-full ${
          !state.reachable ? 'bg-red-500' : partial ? 'bg-accent-500' : 'bg-emerald-500'
        }`}
      />
      {!state.reachable ? (
        'No cluster'
      ) : (
        <>
          <span className="tabular-nums">
            {state.slots_available}/{state.slots_total}
          </span>
          <span>slots</span>
          {total > 1 && (
            <span className="text-slate-400">
              · {partial ? `${reachable}/${total}` : total} targets
            </span>
          )}
        </>
      )}
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
          <div className="flex items-stretch justify-between h-16 gap-4">
            <div className="flex items-stretch gap-6 min-w-0">
              <NavLink to="/jobs" className="flex items-center gap-2.5 shrink-0 self-center">
                <MarsMark size={30} className="shrink-0" title="MARS" />
                <span className="leading-none">
                  <span className="block text-[15px] font-semibold text-slate-900 tracking-tight">
                    MARS
                  </span>
                  <span className="hidden lg:block text-[10.5px] text-slate-500 mt-1
                                   whitespace-nowrap">
                    Marsden Apache Real-time Streaming
                  </span>
                </span>
              </NavLink>
              <nav className="flex items-stretch gap-1 overflow-x-auto overflow-y-hidden
                              [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
                {NAV.filter((i) => !i.adminOnly || user?.role === 'admin').map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    className={({ isActive }) =>
                      `flex items-center px-3 text-[13px] font-medium whitespace-nowrap
                       border-b-2 -mb-px transition-colors ${
                        isActive
                          ? 'text-slate-900 border-accent-500'
                          : 'text-slate-500 border-transparent hover:text-slate-900 hover:border-slate-300'
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
              </nav>
            </div>
            <div className="flex items-center gap-4 shrink-0 self-center">
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
        <div className="bg-accent-50 border-b border-accent-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2 text-[13px] text-accent-900">
            This account still uses its generated password.{' '}
            <NavLink to="/account" className="underline font-medium">Change it now</NavLink>.
          </div>
        </div>
      )}

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-8">{children}</main>

      <footer className="border-t border-slate-200 bg-white">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex items-center gap-2
                        text-[11px] text-slate-400">
          <MarsMark size={14} className="shrink-0 opacity-80" />
          <span>
            <span className="text-slate-500 font-medium">MARS</span>
            {' '}· Marsden Apache Real-time Streaming · stream pipelines for Apache Flink®
          </span>
        </div>
      </footer>
    </div>
  )
}
