export const RESOURCE_DETAILS_DEFAULT_WIDTH = 400
export const RESOURCE_DETAILS_MIN_WIDTH = 320
export const RESOURCE_DETAILS_MAX_WIDTH = 720
export const RESOURCE_LIST_MIN_WIDTH = 640
export const RESOURCE_DETAILS_SEPARATOR_WIDTH = 10
const AGENT_SIDEBAR_WIDTH = 232

export function resourceDetailsWidthKey(userId: string): string {
  return `inteliscope.ui.automation-details-width.v1:${userId}`
}

export function resourceDetailsAvailableWidth(viewportWidth: number): number {
  return viewportWidth >= 1024 ? viewportWidth - AGENT_SIDEBAR_WIDTH : viewportWidth
}

export function maximumResourceDetailsWidth(viewportWidth: number): number {
  return Math.max(RESOURCE_DETAILS_MIN_WIDTH, Math.min(
    RESOURCE_DETAILS_MAX_WIDTH,
    resourceDetailsAvailableWidth(viewportWidth) - RESOURCE_LIST_MIN_WIDTH - RESOURCE_DETAILS_SEPARATOR_WIDTH,
  ))
}

export function canDockResourceDetails(viewportWidth: number): boolean {
  return resourceDetailsAvailableWidth(viewportWidth) - RESOURCE_LIST_MIN_WIDTH - RESOURCE_DETAILS_SEPARATOR_WIDTH >= RESOURCE_DETAILS_MIN_WIDTH
}

export function clampResourceDetailsWidth(width: number, viewportWidth: number): number {
  const safe = Number.isFinite(width) ? width : RESOURCE_DETAILS_DEFAULT_WIDTH
  return Math.round(Math.min(maximumResourceDetailsWidth(viewportWidth), Math.max(RESOURCE_DETAILS_MIN_WIDTH, safe)))
}

export function readResourceDetailsWidth(userId: string): number {
  try {
    const value = JSON.parse(localStorage.getItem(resourceDetailsWidthKey(userId)) || 'null')
    return typeof value?.width === 'number' && Number.isFinite(value.width) ? Math.round(value.width) : RESOURCE_DETAILS_DEFAULT_WIDTH
  } catch { return RESOURCE_DETAILS_DEFAULT_WIDTH }
}

export function writeResourceDetailsWidth(userId: string, width: number): number {
  const value = Math.round(width)
  try { localStorage.setItem(resourceDetailsWidthKey(userId), JSON.stringify({ width: value })) } catch { /* Best-effort layout preference. */ }
  return value
}
