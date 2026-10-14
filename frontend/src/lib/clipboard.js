// Copying text, including from a console served over plain HTTP.
//
// navigator.clipboard exists only in a secure context (HTTPS or localhost), and
// MARS is commonly opened as http://<lan-ip>:8080, where it is undefined. The
// older execCommand('copy') still works there. If both fail, the caller selects
// the text and asks for Ctrl+C rather than claiming success: some of what is
// copied, such as a one-time password, cannot be shown again.
export async function copyText(text) {
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Fall through: permission denied, or the document is not focused.
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.top = '-1000px'
  area.style.opacity = '0'
  document.body.appendChild(area)
  const previous = document.activeElement
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(area)
  previous?.focus?.()
  return ok
}

// Selects an element's text, so the user can copy it by hand.
export function selectContents(element) {
  if (!element) return
  const range = document.createRange()
  range.selectNodeContents(element)
  const selection = window.getSelection()
  selection.removeAllRanges()
  selection.addRange(range)
}
