export const BOOTSTRAP_SHELL_ID = 'inteliscope-bootstrap-shell'
export const BOOTSTRAP_SHELL_STORAGE_KEY = 'inteliscope.ui.bootstrap-shell.v1'

export type BootstrapShellSnapshot = {
  userId: string
  sidebar: 'collapsed' | 'expanded'
}

export function readBootstrapShellSnapshot(): BootstrapShellSnapshot | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(BOOTSTRAP_SHELL_STORAGE_KEY) || 'null') as Partial<BootstrapShellSnapshot> | null
    if (!value || typeof value.userId !== 'string' || !value.userId) return null
    return { userId: value.userId, sidebar: value.sidebar === 'expanded' ? 'expanded' : 'collapsed' }
  } catch {
    return null
  }
}

export function writeBootstrapShellSnapshot(userId: string, sidebar: BootstrapShellSnapshot['sidebar']): void {
  try {
    window.localStorage.setItem(BOOTSTRAP_SHELL_STORAGE_KEY, JSON.stringify({ userId, sidebar }))
  } catch {
    // Layout persistence is best-effort when storage is restricted.
  }
}

export function clearBootstrapShellSnapshot(): void {
  try {
    window.localStorage.removeItem(BOOTSTRAP_SHELL_STORAGE_KEY)
  } catch {
    // Layout persistence is best-effort when storage is restricted.
  }
}

export function releaseBootstrapShell(): void {
  document.getElementById(BOOTSTRAP_SHELL_ID)?.remove()
}
