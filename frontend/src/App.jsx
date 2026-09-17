import { Fragment, useEffect } from 'react'
import { applyTheme, watchSystem } from './lib/theme'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import { AuthProvider, useAuth } from './lib/auth'
import { Spinner } from './components/ui'

import Login from './pages/Login'
import Jobs from './pages/Jobs'
import JobDetail from './pages/JobDetail'
import JobEditor from './pages/JobEditor'
import Catalog from './pages/Catalog'
import CatalogEditor from './pages/CatalogEditor'
import Cluster from './pages/Cluster'
import Account from './pages/Account'
import Activity from './pages/Activity'
import Settings from './pages/Settings'
import { InteractionProvider } from './components/InteractionProvider'

function Protected({ children, writer = false }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="min-h-screen grid place-items-center"><Spinner label="Starting" /></div>
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  if (writer && !['admin', 'editor'].includes(user.role)) return <Navigate to="/jobs" replace />
  return <Layout><Fragment key={location.pathname + location.search}>{children}</Fragment></Layout>
}

function Shell() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Navigate to="/jobs" replace />} />
      <Route path="/jobs" element={<Protected><Jobs /></Protected>} />
      <Route path="/jobs/new" element={<Protected writer><JobEditor /></Protected>} />
      <Route path="/jobs/:name" element={<Protected><JobDetail /></Protected>} />
      <Route path="/jobs/:name/edit" element={<Protected writer><JobEditor /></Protected>} />
      <Route path="/catalog" element={<Protected><Catalog /></Protected>} />
      <Route path="/catalog/new" element={<Protected writer><CatalogEditor /></Protected>} />
      <Route path="/catalog/:name/edit" element={<Protected writer><CatalogEditor /></Protected>} />
      <Route path="/secrets" element={<Navigate to="/settings/secrets" replace />} />
      <Route path="/cluster" element={<Protected><Cluster /></Protected>} />
      <Route path="/activity" element={<Protected><Activity /></Protected>} />
      <Route path="/settings/*" element={<Protected><Settings /></Protected>} />
      <Route path="/account" element={<Protected><Account /></Protected>} />
      <Route path="/admin" element={<Navigate to="/settings/accounts" replace />} />
      <Route path="/ai" element={<Navigate to="/settings/ai" replace />} />
      <Route path="*" element={<Navigate to="/jobs" replace />} />
    </Routes>
  )
}

export default function App() {
  useEffect(() => watchSystem(() => applyTheme('system')), [])
  return (
    <AuthProvider>
      <InteractionProvider>
        <Shell />
      </InteractionProvider>
    </AuthProvider>
  )
}
