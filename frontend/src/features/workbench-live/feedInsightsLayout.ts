export const FLOATING_INSIGHTS_REQUIRED_GUTTER = 376
export const FLOATING_INSIGHTS_WIDTH = 352
export const FLOATING_INSIGHTS_INSET = 12
export const FLOATING_INSIGHTS_GAP = 12

type HorizontalBounds = Pick<DOMRectReadOnly, 'left' | 'right'>

export type FeedInsightsLayout = {
  panelLeft: number
  readingShift: number
  obstructsFeed: boolean
}

export function canFloatFeedInsights(mainRight: number, readingRight: number): boolean {
  return Number.isFinite(mainRight)
    && Number.isFinite(readingRight)
    && mainRight - readingRight >= FLOATING_INSIGHTS_REQUIRED_GUTTER
}

export function calculateFeedInsightsLayout(
  main: HorizontalBounds,
  reading: HorizontalBounds,
  shiftReading: boolean,
): FeedInsightsLayout {
  const values = [main.left, main.right, reading.left, reading.right]
  if (values.some((value) => !Number.isFinite(value)) || main.right <= main.left || reading.right <= reading.left) {
    return { panelLeft: 0, readingShift: 0, obstructsFeed: false }
  }

  const panelLeft = main.right - FLOATING_INSIGHTS_INSET - FLOATING_INSIGHTS_WIDTH
  const requiredShift = shiftReading
    ? Math.max(0, reading.right + FLOATING_INSIGHTS_GAP - panelLeft)
    : 0
  const availableLeftGutter = Math.max(0, reading.left - (main.left + FLOATING_INSIGHTS_INSET))
  const readingShift = requiredShift > 0 ? -Math.min(requiredShift, availableLeftGutter) : 0
  const shiftedReading = {
    left: reading.left + readingShift,
    right: reading.right + readingShift,
  }
  const obstructsFeed = shiftedReading.left < panelLeft + FLOATING_INSIGHTS_WIDTH
    && shiftedReading.right > panelLeft

  return { panelLeft, readingShift, obstructsFeed }
}
