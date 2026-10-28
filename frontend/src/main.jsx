import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import App from './App'
import RouteError from './components/RouteError'
// Bundled rather than fetched from Google Fonts: a self-hosted console should not
// call a third party on every page load, and must look right on a closed network.
import '@fontsource-variable/inter'
import './index.css'

const router = createBrowserRouter([{ path: '*', element: <App />, errorElement: <RouteError /> }])

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
)
