import { writeBootstrapShellSnapshot } from './bootstrapShell'

export type SidebarPreference = 'collapsed' | 'expanded'

export function sidebarPreferenceKey(userId: string): string {
  return `inteliscope.ui.sidebar.v1:${userId}`
}

export function readSidebarPreference(userId: string): SidebarPreference {
  try {
    const value = window.localStorage.getItem(sidebarPreferenceKey(userId))
    return value === 'expanded' ? 'expanded' : 'collapsed'
  } catch {
    return 'collapsed'
  }
}

export function writeSidebarPreference(userId: string, value: SidebarPreference): void {
  try {
    window.localStorage.setItem(sidebarPreferenceKey(userId), value)
    writeBootstrapShellSnapshot(userId, value)
  } catch {
    // Storage may be unavailable in private or restricted browser contexts.
  }
}
