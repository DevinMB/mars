import { createContext, useCallback, useContext, useEffect, useId, useRef, useState } from 'react'

const Interactions = createContext(null)

export function InteractionProvider({ children }) {
  const [confirmation, setConfirmation] = useState(null)
  const [notice, setNotice] = useState('')
  const unsaved = useRef(false)
  const pending = useRef(null)
  const dialog = useRef(null)
  const cancel = useRef(null)
  const titleId = useId()
  const bodyId = useId()
  const confirm = useCallback((options) => new Promise((resolve) => {
    if (pending.current) { resolve(false); return }
    pending.current = resolve
    setConfirmation(typeof options === 'string' ? { message: options } : options)
  }), [])
  const finish = useCallback((accepted) => {
    dialog.current?.close()
    setConfirmation(null)
    pending.current?.(accepted)
    pending.current = null
  }, [])
  useEffect(() => {
    if (confirmation) { dialog.current.showModal(); cancel.current?.focus() }
  }, [confirmation])
  useEffect(() => {
    if (!notice) return
    const timer = setTimeout(() => setNotice(''), 5000)
    return () => clearTimeout(timer)
  }, [notice])
  return (
    <Interactions.Provider value={{ confirm, notify: setNotice, unsaved }}>
      {children}
      <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 max-w-[calc(100%-2rem)]" role="status" aria-live="polite">
        {notice && <div className="flex items-center gap-5 rounded-lg border border-slate-300 bg-surface px-4 py-3 shadow-lg text-sm">
          <span>{notice}</span>
          <button aria-label="Dismiss notification" onClick={() => setNotice('')} className="text-slate-500">×</button>
        </div>}
      </div>
      <dialog ref={dialog} className="confirmation" aria-labelledby={titleId} aria-describedby={bodyId}
              onCancel={(event) => { event.preventDefault(); finish(false) }}>
        <h2 id={titleId} className="text-lg font-semibold">{confirmation?.title || 'Confirm action'}</h2>
        <p id={bodyId} className="mt-3 text-sm text-slate-600 whitespace-pre-line leading-relaxed">{confirmation?.message}</p>
        <div className="flex justify-end gap-2 mt-6">
          <button ref={cancel} className="btn-secondary" onClick={() => finish(false)}>{confirmation?.cancelLabel || 'Cancel'}</button>
          <button className={confirmation?.danger === false ? 'btn-primary' : 'btn-danger'} onClick={() => finish(true)}>
            {confirmation?.confirmLabel || 'Continue'}
          </button>
        </div>
      </dialog>
    </Interactions.Provider>
  )
}

export const useConfirm = () => useContext(Interactions).confirm
export const useNotify = () => useContext(Interactions).notify

export const usePendingEdits = () => useContext(Interactions).unsaved
