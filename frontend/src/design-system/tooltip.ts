/**
 * Keep hover help beside its trigger. React Aria will flip or shift the
 * overlay when the preferred right-hand side would leave the viewport.
 *
 * This stays a plain object on purpose: importing HeroUI here would make the
 * design-system barrel eagerly evaluate another Tooltip module instance.
 */
export const anchoredTooltipProps = {
  placement: 'right' as const,
  offset: 8,
  containerPadding: 8,
  shouldFlip: true,
}

/**
 * Card footer actions form a horizontal row, so their help belongs above the
 * trigger. Collision handling can still flip or shift the overlay when needed.
 */
export const topAnchoredTooltipProps = {
  placement: 'top' as const,
  offset: 8,
  containerPadding: 8,
  shouldFlip: true,
}

/**
 * Compact workbench ViewBars sit at the top of their reading surface, so
 * controls in that row explain themselves below the trigger.
 */
export const bottomAnchoredTooltipProps = {
  placement: 'bottom' as const,
  offset: 8,
  containerPadding: 8,
  shouldFlip: true,
}
