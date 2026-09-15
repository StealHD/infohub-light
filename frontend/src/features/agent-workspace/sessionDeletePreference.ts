const SESSION_DELETE_CONFIRM_KEY_PREFIX = 'inteliscope.ui.session-delete-confirm.v1:'
const SKIP_CONFIRMATION_VALUE = 'skip'

export function sessionDeleteConfirmPreferenceKey(userId: string): string {
  return `${SESSION_DELETE_CONFIRM_KEY_PREFIX}${encodeURIComponent(userId)}`
}

export function readSessionDeleteConfirmation(userId: string): boolean {
  try {
    return window.localStorage.getItem(sessionDeleteConfirmPreferenceKey(userId)) !== SKIP_CONFIRMATION_VALUE
  } catch {
    return true
  }
}

export function writeSessionDeleteConfirmation(userId: string, enabled: boolean): boolean {
  try {
    const key = sessionDeleteConfirmPreferenceKey(userId)
    if (enabled) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, SKIP_CONFIRMATION_VALUE)
    return true
  } catch {
    return false
  }
}
