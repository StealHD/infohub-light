export const BOOTSTRAP_SHELL_ID = 'inteliscope-bootstrap-shell'
export const BOOTSTRAP_SHELL_STORAGE_KEY = 'inteliscope.ui.bootstrap-shell.v1'

export type BootstrapShellSnapshot = {
  userId: string
  sidebar: 'collapsed' | 'expanded'
  rightRail: 'closed' | 'agent'
  rightRailWidth: number
}

const DEFAULT_RIGHT_RAIL_WIDTH = 360

export function readBootstrapShellSnapshot(): BootstrapShellSnapshot | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(BOOTSTRAP_SHELL_STORAGE_KEY) || 'null') as Partial<BootstrapShellSnapshot> | null
    if (!value || typeof value.userId !== 'string' || !value.userId) return null
    return {
      userId: value.userId,
      sidebar: value.sidebar === 'expanded' ? 'expanded' : 'collapsed',
      rightRail: value.rightRail === 'agent' ? 'agent' : 'closed',
      rightRailWidth: typeof value.rightRailWidth === 'number' && Number.isFinite(value.rightRailWidth)
        ? Math.round(value.rightRailWidth)
        : DEFAULT_RIGHT_RAIL_WIDTH,
    }
  } catch {
    return null
  }
}

export function writeBootstrapShellSnapshot(
  userId: string,
  sidebar: BootstrapShellSnapshot['sidebar'],
  patch: Partial<Pick<BootstrapShellSnapshot, 'rightRail' | 'rightRailWidth'>> = {},
): void {
  try {
    const current = readBootstrapShellSnapshot()
    window.localStorage.setItem(BOOTSTRAP_SHELL_STORAGE_KEY, JSON.stringify({
      userId,
      sidebar,
      rightRail: patch.rightRail ?? (current?.userId === userId ? current.rightRail : 'closed'),
      rightRailWidth: patch.rightRailWidth ?? (current?.userId === userId ? current.rightRailWidth : DEFAULT_RIGHT_RAIL_WIDTH),
    } satisfies BootstrapShellSnapshot))
  } catch {
    // Layout persistence is best-effort when storage is restricted.
  }
}

export function readBootstrapShellRightRail(userId: string): BootstrapShellSnapshot['rightRail'] {
  const snapshot = readBootstrapShellSnapshot()
  return snapshot?.userId === userId ? snapshot.rightRail : 'closed'
}

export function writeBootstrapShellRightRail(userId: string, rightRail: BootstrapShellSnapshot['rightRail'], rightRailWidth?: number): void {
  const current = readBootstrapShellSnapshot()
  writeBootstrapShellSnapshot(userId, current?.userId === userId ? current.sidebar : 'collapsed', {
    rightRail,
    rightRailWidth: rightRailWidth ?? (current?.userId === userId ? current.rightRailWidth : DEFAULT_RIGHT_RAIL_WIDTH),
  })
}

export function writeBootstrapShellRightRailWidth(userId: string, rightRailWidth: number): void {
  const current = readBootstrapShellSnapshot()
  writeBootstrapShellSnapshot(userId, current?.userId === userId ? current.sidebar : 'collapsed', {
    rightRail: current?.userId === userId ? current.rightRail : 'closed',
    rightRailWidth,
  })
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
