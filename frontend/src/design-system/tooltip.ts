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
