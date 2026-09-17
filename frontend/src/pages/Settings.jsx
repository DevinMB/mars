import { useEffect, useState } from 'react'
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { api } from '../lib/api'
import Admin from './Admin'
import Ai from './Ai'
import Secrets from './Secrets'
import RegistryPanel from '../components/RegistryPanel'
import BackupPanel from '../components/BackupPanel'
import { Alert, PageHeader } from '../components/ui'

function Registry() {
  const [names, setNames] = useState([])
  const [error, setError] = useState(null)
  useEffect(() => { api.secrets().then((rows) => setNames(rows.map((row) => row.name))).catch((e) => setError(e.message)) }, [])
  return <>
    <PageHeader title="Schema registry" subtitle="Use registered Avro schemas in your catalog." />
    {error && <Alert level="warning">Could not load secret names: {error}</Alert>}
    <RegistryPanel secretNames={names} />
  </>
}

const SECTIONS = [
  ['Access', [['accounts', 'Accounts'], ['secrets', 'Secrets']]],
  ['Integrations', [['ai', 'AI provider'], ['registry', 'Schema registry']]],
  ['Data', [['backup', 'Backup & restore']]],
]

export default function Settings() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  if (user?.role !== 'admin') return <Navigate to="/jobs" replace />
  return <div className="grid gap-6 lg:gap-10 lg:grid-cols-[180px_minmax(0,1fr)]">
    <nav aria-label="Settings navigation" className="settings-nav">
      <h2 className="text-sm font-semibold mb-5">Settings</h2>
      <select aria-label="Settings section" className="input sm:hidden" value={location.pathname.split('/')[2] || 'accounts'} onChange={(e) => navigate(`/settings/${e.target.value}`)}>
        {SECTIONS.map(([heading, items]) => <optgroup key={heading} label={heading}>{items.map(([path, label]) => <option key={path} value={path}>{label}</option>)}</optgroup>)}
      </select>
      <div className="hidden sm:flex flex-wrap gap-x-6 gap-y-4 lg:block lg:space-y-6">
        {SECTIONS.map(([heading, items]) => <div key={heading}>
          <div className="text-xs text-slate-500 mb-1.5 px-2">{heading}</div>
          <select aria-label="Settings section" className="input sm:hidden" value={location.pathname.split('/')[2] || 'accounts'} onChange={(e) => navigate(`/settings/${e.target.value}`)}>
        {SECTIONS.map(([heading, items]) => <optgroup key={heading} label={heading}>{items.map(([path, label]) => <option key={path} value={path}>{label}</option>)}</optgroup>)}
      </select>
      <div className="hidden sm:flex flex-wrap gap-1 lg:block">
            {items.map(([path, label]) => <NavLink key={path} to={`/settings/${path}`} className={({ isActive }) =>
              `block px-2 py-2 rounded-md text-[13px] ${isActive ? 'bg-slate-100 text-slate-900 font-medium' : 'text-slate-600 hover:bg-slate-100'}`}>
              {label}
            </NavLink>)}
          </div>
        </div>)}
      </div>
    </nav>
    <div className="min-w-0">
      <Routes>
        <Route index element={<Navigate to="accounts" replace />} />
        <Route path="accounts" element={<Admin />} />
        <Route path="secrets" element={<Secrets />} />
        <Route path="ai" element={<Ai />} />
        <Route path="registry" element={<Registry />} />
        <Route path="backup" element={<><PageHeader title="Backup & restore" subtitle="Export definitions or restore them from a file." /><BackupPanel /></>} />
        <Route path="*" element={<Navigate to="accounts" replace />} />
      </Routes>
    </div>
  </div>
}
