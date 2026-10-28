import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import MarsMark from './MarsMark'

// What a person sees when a page throws while rendering. Without it, React Router
// shows its developer screen ("Hey developer"), which tells an operator nothing
// and offers no way back. The error text stays visible: it is what a bug report
// needs, and this console has no telemetry to send it anywhere else.
export default function RouteError() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error?.message || String(error)
  return (
    <main className="min-h-screen grid place-items-center px-4 py-12">
      <div className="card max-w-lg w-full p-8 text-center">
        <MarsMark size={40} className="mx-auto mb-4" />
        <h1 className="text-lg font-semibold text-slate-900">This page stopped working</h1>
        <p className="text-sm text-slate-500 mt-1">
          Your jobs are unaffected: this is the console, not the cluster. Reload to
          try again, or go back to the job list.
        </p>
        <pre className="mono text-xs text-left text-slate-700 bg-slate-50 border border-slate-200 rounded-md p-3 mt-5 whitespace-pre-wrap wrap-break-word max-h-40 overflow-auto">{message}</pre>
        <div className="flex justify-center gap-2 mt-5">
          <button type="button" className="btn-primary" onClick={() => window.location.reload()}>Reload</button>
          {/* A plain link, not a router one: the router is what just failed. */}
          <a href="/jobs" className="btn-secondary">Back to jobs</a>
        </div>
      </div>
    </main>
  )
}
