import { useRef, useState } from 'react'
import { copyText, selectContents } from '../lib/clipboard'

/**
 * Shows a credential that will never be shown again.
 *
 * Generated passwords and API tokens exist in readable form exactly once, at the
 * moment they are created — MARS keeps only a hash. So this makes copying the
 * obvious action, and says plainly that closing it loses the value, rather than
 * letting someone dismiss it and then discover that.
 */
export default function SecretOnce({ label, value, onDone }) {
  // '', 'copied', or 'manual' when the browser refused and the value is selected.
  const [copied, setCopied] = useState('')
  const valueRef = useRef(null)
  return (
    <div className="rounded-md border border-accent-300 bg-accent-50 p-4 mb-4">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div>
          <div className="text-[13px] font-semibold text-accent-900">{label}</div>
          <p className="text-[12px] text-accent-800/80 mt-0.5">
            Shown once. MARS stores only a hash, so this cannot be retrieved later —
            copy it now.
          </p>
        </div>
        <button onClick={onDone} className="text-accent-700 hover:text-accent-900 text-sm shrink-0">
          Done
        </button>
      </div>
      <div className="flex items-center gap-2">
        <code ref={valueRef} className="mono flex-1 bg-surface border border-accent-200 rounded-sm px-2.5 py-2
                         text-[12.5px] text-slate-800 break-all select-all">
          {value}
        </code>
        <button
          className="btn-secondary shrink-0"
          onClick={async () => {
            // Shown once and never again, so a failed copy must not look like a
            // success: select it and ask for Ctrl+C instead.
            const ok = await copyText(value)
            if (!ok) selectContents(valueRef.current)
            setCopied(ok ? 'copied' : 'manual')
            setTimeout(() => setCopied(''), ok ? 1500 : 4000)
          }}
        >
          {copied === 'copied' ? 'Copied' : copied === 'manual' ? 'Press Ctrl+C' : 'Copy'}
        </button>
      </div>
    </div>
  )
}
