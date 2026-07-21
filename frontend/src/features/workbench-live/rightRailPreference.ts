export type RightRailWidthPreferenceV1 = { width: number }

export const RIGHT_RAIL_DEFAULT_WIDTH = 360
export const RIGHT_RAIL_MIN_WIDTH = 320
export const RIGHT_RAIL_MAX_WIDTH = 720
export const WORKBENCH_FEED_MIN_WIDTH = 640
export const RIGHT_RAIL_SEPARATOR_WIDTH = 10

export function rightRailWidthPreferenceKey(userId: string): string {
  return `inteliscope.ui.right-rail.v1:${userId}`
}

export function maximumRightRailWidth(viewportWidth: number, sidebarWidth: number): number {
  return Math.max(
    RIGHT_RAIL_MIN_WIDTH,
    Math.min(
      RIGHT_RAIL_MAX_WIDTH,
      viewportWidth - sidebarWidth - WORKBENCH_FEED_MIN_WIDTH - RIGHT_RAIL_SEPARATOR_WIDTH,
    ),
  )
}

export function clampRightRailWidth(width: number, viewportWidth: number, sidebarWidth: number): number {
  const safeWidth = Number.isFinite(width) ? width : RIGHT_RAIL_DEFAULT_WIDTH
  return Math.round(Math.min(maximumRightRailWidth(viewportWidth, sidebarWidth), Math.max(RIGHT_RAIL_MIN_WIDTH, safeWidth)))
}

export function readRightRailWidth(userId: string): number {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(rightRailWidthPreferenceKey(userId)) || 'null') as Partial<RightRailWidthPreferenceV1> | null
    return typeof parsed?.width === 'number' && Number.isFinite(parsed.width)
      ? Math.round(parsed.width)
      : RIGHT_RAIL_DEFAULT_WIDTH
  } catch {
    return RIGHT_RAIL_DEFAULT_WIDTH
  }
}

export function writeRightRailWidth(userId: string, width: number): RightRailWidthPreferenceV1 {
  const preference = { width: Math.round(width) }
  try { window.localStorage.setItem(rightRailWidthPreferenceKey(userId), JSON.stringify(preference)) } catch { /* Layout persistence is best-effort. */ }
  return preference
}
