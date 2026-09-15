// Light, dark, or whatever the machine is set to.
//
// Three states rather than two, because "follow the system" is a real preference
// and not the absence of one: someone whose laptop goes dark at sunset expects
// the console to go with it, and a boolean cannot express that.
const KEY = 'mars.theme'
const MEDIA = '(prefers-color-scheme: dark)'

export function readTheme() {
  try {
    const stored = localStorage.getItem(KEY)
    if (stored === 'light' || stored === 'dark' || stored === 'system') return stored
  } catch {
    // Private windows and blocked site data throw here. Following the system is
    // the right answer when we cannot remember a choice.
  }
  return 'system'
}

export function resolveTheme(theme) {
  if (theme === 'system') {
    return window.matchMedia?.(MEDIA).matches ? 'dark' : 'light'
  }
  return theme
}

export function applyTheme(theme) {
  document.documentElement.classList.toggle('dark', resolveTheme(theme) === 'dark')
}

export function writeTheme(theme) {
  try { localStorage.setItem(KEY, theme) } catch { /* not worth failing over */ }
  applyTheme(theme)
}

/** Keeps "system" honest when the machine changes while the page is open. */
export function watchSystem(onChange) {
  const mq = window.matchMedia?.(MEDIA)
  if (!mq) return () => {}
  const handler = () => { if (readTheme() === 'system') onChange() }
  mq.addEventListener('change', handler)
  return () => mq.removeEventListener('change', handler)
}
