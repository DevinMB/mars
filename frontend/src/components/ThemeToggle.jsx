import { useState } from 'react'
import { readTheme, writeTheme } from '../lib/theme'

const OPTIONS = [
  { id: 'light', label: 'Light' },
  { id: 'system', label: 'Auto' },
  { id: 'dark', label: 'Dark' },
]

export default function ThemeToggle() {
  const [theme, setTheme] = useState(readTheme)


  return (
    <div className="flex items-center gap-0.5 p-0.5 rounded-md bg-slate-100"
         role="group" aria-label="Colour theme">
      {OPTIONS.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={theme === o.id}
          title={o.id === 'system' ? 'Follow this machine' : `Always ${o.label.toLowerCase()}`}
          onClick={() => { setTheme(o.id); writeTheme(o.id) }}
          className={`px-2 py-0.5 rounded-sm text-[11px] font-medium transition-colors ${
            theme === o.id
              ? 'bg-surface text-slate-900 shadow-xs'
              : 'text-slate-500 hover:text-slate-800'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}
