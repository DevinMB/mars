import { useCallback, useEffect, useRef } from 'react'
import { useBeforeUnload, useBlocker } from 'react-router-dom'
import { useConfirm, usePendingEdits } from '../components/InteractionProvider'

export default function useUnsavedChanges(dirty) {
  const leaving = useRef(false)
  const confirm = useConfirm()
  const unsaved = usePendingEdits()
  useEffect(() => { unsaved.current = dirty; return () => { unsaved.current = false } }, [dirty, unsaved])
  const blocker = useBlocker(useCallback(({ currentLocation, nextLocation }) =>
    dirty && !leaving.current && (currentLocation.pathname !== nextLocation.pathname ||
      currentLocation.search !== nextLocation.search), [dirty]))
  useBeforeUnload(useCallback((e) => {
    if (dirty && !leaving.current) { e.preventDefault(); e.returnValue = '' }
  }, [dirty]))
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    confirm({ title: 'Discard unsaved changes?', message: 'Your changes have not been saved.',
      confirmLabel: 'Discard changes', cancelLabel: 'Keep editing' })
      .then((yes) => yes ? blocker.proceed() : blocker.reset())
  }, [blocker, confirm])
  return () => { leaving.current = true }
}
