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
import Secrets from './pages/Secrets'
import Cluster from './pages/Cluster'
import Account from './pages/Account'
import Admin from './pages/Admin'
import Activity from './pages/Activity'
import Ai from './pages/Ai'

function Protected({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="min-h-screen grid place-items-center"><Spinner label="Starting" /></div>
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />
  return <Layout>{children}</Layout>
}

function Shell() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Navigate to="/jobs" replace />} />
      <Route path="/jobs" element={<Protected><Jobs /></Protected>} />
      <Route path="/jobs/new" element={<Protected><JobEditor /></Protected>} />
      <Route path="/jobs/:name" element={<Protected><JobDetail /></Protected>} />
      <Route path="/jobs/:name/edit" element={<Protected><JobEditor /></Protected>} />
      <Route path="/catalog" element={<Protected><Catalog /></Protected>} />
      <Route path="/catalog/new" element={<Protected><CatalogEditor /></Protected>} />
      <Route path="/catalog/:name/edit" element={<Protected><CatalogEditor /></Protected>} />
      <Route path="/secrets" element={<Protected><Secrets /></Protected>} />
      <Route path="/cluster" element={<Protected><Cluster /></Protected>} />
      <Route path="/activity" element={<Protected><Activity /></Protected>} />
      <Route path="/account" element={<Protected><Account /></Protected>} />
      <Route path="/admin" element={<Protected><Admin /></Protected>} />
      <Route path="/ai" element={<Protected><Ai /></Protected>} />
      <Route path="*" element={<Navigate to="/jobs" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}
