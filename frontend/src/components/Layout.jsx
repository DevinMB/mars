import { NavLink, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import MarsMark from './MarsMark'
import ThemeToggle from './ThemeToggle'
import ActionMenu from './ActionMenu'
import { useConfirm, usePendingEdits } from './InteractionProvider'
import { useAuth } from '../lib/auth'
import { ComponentUpdate, componentsBehind, short } from './UpdateDetails'

const NAV = [
  { to: '/jobs', label: 'Jobs' },
  { to: '/catalog', label: 'Catalog' },
  { to: '/pipeline', label: 'Pipeline' },
  { to: '/activity', label: 'Activity' },
  { to: '/cluster', label: 'Clusters' },
  { to: '/settings', label: 'Settings', adminOnly: true },
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
    ? 'No cluster is reachable'
    : partial
      ? `${reachable} of ${total} targets reachable \u2014 capacity shown is only what answered`
      : `Flink ${state.flink_version}` + (total > 1 ? ` across ${total} clusters` : '')

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
          <span>slots free</span>
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
  const [version, setVersion] = useState(null)
  const [showUpdate, setShowUpdate] = useState(false)
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem('mars.updateDismissed') } catch { return null }
  })
  useEffect(() => {
    if (!user) return
    api.version().then(setVersion).catch(() => setVersion(null))
  }, [user])
  // Administrators only: they are the ones who can act on it. Dismissed per
  // release, so the next one still shows.
  const behind = user?.role === 'admin' ? componentsBehind(version) : []
  const latestRev = version?.latest?.revision
  const updateBanner = behind.length > 0 && dismissed !== latestRev
  const navigate = useNavigate()
  const confirm = useConfirm()
  const unsaved = usePendingEdits()

  return (
    <div className="min-h-screen flex flex-col">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="bg-surface border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 flex flex-wrap items-center gap-x-7">
          <NavLink to="/jobs" aria-label="MARS home" className="flex items-center gap-2.5 h-14 shrink-0">
            <MarsMark size={24} />
            <span className="text-base font-semibold tracking-tight">MARS</span>
          </NavLink>
          <nav aria-label="Main navigation" className="order-3 w-full sm:order-0 sm:w-auto flex items-stretch gap-1 h-11 sm:h-14 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {NAV.filter((item) => !item.adminOnly || user?.role === 'admin').map((item) => (
              <NavLink key={item.to} to={item.to} className={({ isActive }) =>
                `nav-link ${isActive ? 'nav-link-active' : ''}`}>
                {item.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-4">
            <NavLink to="/cluster" className="hidden lg:block" aria-label="View cluster capacity"><ClusterDot /></NavLink>
            <ActionMenu label={<span className="max-w-28 truncate">{user?.username || 'Account'}</span>}>
              <div className="px-3 py-2 text-xs text-slate-500">Signed in as {user?.role}</div>
              <NavLink to="/account">Account</NavLink>
              <div data-keep-open className="px-3 py-3 border-y border-slate-200 my-1">
                <div className="text-xs text-slate-500 mb-2">Appearance</div>
                <ThemeToggle />
              </div>
              <button onClick={async () => {
                if (unsaved.current && !await confirm({ title: 'Sign out and discard changes?', message: 'Your edits have not been saved.', confirmLabel: 'Sign out', cancelLabel: 'Keep editing' })) return
                await logout(); navigate('/login')
              }}>Sign out</button>
            </ActionMenu>
          </div>
        </div>
      </header>
      {updateBanner && (
        <div className="bg-slate-50 border-b border-slate-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2 text-[13px] text-slate-700">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="w-2 h-2 rounded-full bg-accent-500" aria-hidden="true" />
              <span>
                <b className="font-medium text-slate-900">Update available:</b>{' '}
                {version.latest.label} for {behind.map((c) => (c === 'flink' ? 'Flink' : 'the console')).join(' and ')}.
              </span>
              <button type="button" className="link" aria-expanded={showUpdate} onClick={() => setShowUpdate(!showUpdate)}>
                {showUpdate ? 'Hide' : 'How to update'}
              </button>
              <button type="button" className="ml-auto text-[12px] text-slate-500 hover:text-slate-800" onClick={() => {
                try { localStorage.setItem('mars.updateDismissed', latestRev) } catch { /* private window */ }
                setDismissed(latestRev)
              }}>Dismiss</button>
            </div>
            {showUpdate && (
              <div className="grid gap-6 md:grid-cols-2 py-4">
                {behind.map((c) => <ComponentUpdate key={c} name={c} data={version[c]} latest={version.latest} />)}
              </div>
            )}
          </div>
        </div>
      )}
      {user?.must_change_password && (
        <div className="bg-accent-50 border-b border-accent-200">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 py-2 text-[13px] text-accent-900">
            Update your generated password.{' '}
            <NavLink to="/account" className="underline font-medium">Go to Account</NavLink>.
          </div>
        </div>
      )}
      <main id="main-content" tabIndex={-1} className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 py-7 sm:py-9 min-w-0">{children}</main>
      <footer className="max-w-7xl w-full mx-auto px-4 sm:px-6 py-5 text-xs text-slate-500">
        MARS{version?.console?.revision && (
          <span className="mono ml-1.5" title={`Built ${version.console.built_at || 'at an unknown time'}`}>
            {short(version.console.revision)}
          </span>
        )}
        <span className="mx-1.5" aria-hidden="true">/</span> Stream pipelines for Apache Flink®
      </footer>
    </div>
  )
}
