import { forwardRef, useEffect, useImperativeHandle, useRef, useState, useId } from 'react'
import { CompletionList, useCompletion } from './Completion'

// A deliberately small SQL editor: a monospace textarea with a line gutter and
// tab handling. It keeps the bundle light and behaves predictably; a full
// language server is a later upgrade, not a prerequisite.
function SqlEditorInner(
  { value, onChange, rows = 16, readOnly = false, marker = null, completions = [] },
  ref,
) {
  const taRef = useRef(null)
  const [focused, setFocused] = useState(false)
  const escapeTab = useRef(false)
  const [tabHint, setTabHint] = useState(false)
  const hintId = useId()
  // The parent needs the caret position to insert a column name where the
  // cursor actually is, rather than appending to the end.
  useImperativeHandle(ref, () => taRef.current, [])
  const gutterRef = useRef(null)

  const lines = (value || '').split('\n').length

  useEffect(() => {
    const ta = taRef.current
    const gutter = gutterRef.current
    if (!ta || !gutter) return
    const sync = () => { gutter.scrollTop = ta.scrollTop }
    ta.addEventListener('scroll', sync)
    return () => ta.removeEventListener('scroll', sync)
  }, [])

  const completion = useCompletion({
    value: value || '', onChange, taRef, items: readOnly ? [] : completions, mode: 'sql',
  })

  const onKeyDown = (e) => {
    if (e.key === 'Escape') {
      completion.onKeyDown(e)
      escapeTab.current = true; setTabHint(true)
      return
    }
    if (e.key === 'Tab' && (e.shiftKey || escapeTab.current)) {
      escapeTab.current = false; setTabHint(false)
      return
    }
    if (completion.onKeyDown(e)) return
    if (e.key !== 'Tab' || readOnly) return
    // Tab indents rather than leaving the field: this is an editor, not a form.
    e.preventDefault()
    const ta = e.target
    const { selectionStart: s, selectionEnd: en } = ta
    const next = `${value.slice(0, s)}  ${value.slice(en)}`
    onChange(next)
    requestAnimationFrame(() => { ta.selectionStart = ta.selectionEnd = s + 2 })
  }

  return (
    <>
    <div className="flex border border-slate-300 rounded-md overflow-hidden bg-surface
                    focus-within:ring-2 focus-within:ring-brand-500/30 focus-within:border-brand-500">
      <div
        ref={gutterRef}
        aria-hidden="true"
        className="mono select-none text-right text-slate-400 bg-slate-50 border-r
                   border-slate-200 py-3 px-2 overflow-hidden leading-relaxed"
      >
        {Array.from({ length: lines }, (_, i) => {
          // The line Flink objected to, called out where the eye already is.
          const flagged = marker && marker.line === i + 1
          return (
            <div
              key={i}
              // The number stays: knowing it is line 7 is the point of a gutter.
              className={flagged ? 'text-red-600 font-semibold bg-red-50 -mx-2 px-2' : undefined}
              title={flagged ? marker.message : undefined}
            >
              {i + 1}
            </div>
          )
        })}
      </div>
      <textarea
        ref={taRef}
        aria-label="SQL statement"
        aria-describedby={readOnly ? undefined : hintId}
        onFocus={() => setFocused(true)}
        onBlur={() => { setFocused(false); escapeTab.current = false; setTabHint(false) }}
        value={value}
        readOnly={readOnly}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        rows={rows}
        className="min-w-0 flex-1 mono p-3 leading-relaxed resize-y focus:outline-hidden
                   text-slate-800 bg-transparent"
        placeholder="INSERT INTO my_sink SELECT … FROM my_source"
      />
    </div>
    {!readOnly && <p id={hintId} className="hint">{tabHint ? 'Press Tab to leave the editor.' : 'Tab indents. Escape, then Tab leaves the editor; Shift+Tab goes back.'}</p>}
    {focused && completion.open && (
      <CompletionList
        matches={completion.matches}
        active={completion.active}
        onPick={completion.accept}
      />
    )}
    </>
  )
}

export default forwardRef(SqlEditorInner)
