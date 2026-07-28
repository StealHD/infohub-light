/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, type ComponentPropsWithoutRef } from 'react'

export type TimelineDensity = 'compact' | 'comfortable'
export type TimelineItemStatus = 'default' | 'current'

export type TimelineProps = ComponentPropsWithoutRef<'ol'> & {
  density?: TimelineDensity
}

export type TimelineItemProps = ComponentPropsWithoutRef<'li'> & {
  status?: TimelineItemStatus
}

export type TimelineRailProps = ComponentPropsWithoutRef<'span'>
export type TimelineMarkerProps = ComponentPropsWithoutRef<'span'>
export type TimelineConnectorProps = ComponentPropsWithoutRef<'span'>
export type TimelineContentProps = ComponentPropsWithoutRef<'div'>

const TimelineItemStatusContext = createContext<TimelineItemStatus>('default')

const densityClasses: Record<TimelineDensity, string> = {
  compact: '[--timeline-connector-bottom:-2.5rem] [&>[data-timeline-item]]:pb-5',
  comfortable: '[--timeline-connector-bottom:-3.25rem] [&>[data-timeline-item]]:pb-8',
}

function TimelineRoot({
  density = 'comfortable',
  className = '',
  ...props
}: TimelineProps) {
  return <ol
    {...props}
    data-timeline
    data-density={density}
    className={`m-0 list-none p-0 [&>[data-timeline-item]:last-child]:pb-0 [&>[data-timeline-item]:last-child_[data-timeline-connector]]:hidden ${densityClasses[density]} ${className}`}
  />
}

function TimelineItem({
  status = 'default',
  className = '',
  children,
  'aria-current': ariaCurrent,
  ...props
}: TimelineItemProps) {
  return <TimelineItemStatusContext.Provider value={status}>
    <li
      {...props}
      data-timeline-item
      data-status={status}
      aria-current={status === 'current' ? 'true' : ariaCurrent}
      className={`grid min-w-0 grid-cols-[20px_minmax(0,1fr)] gap-3 ${className}`}
    >
      {children}
    </li>
  </TimelineItemStatusContext.Provider>
}

function TimelineRail({
  className = '',
  ...props
}: TimelineRailProps) {
  return <span
    {...props}
    data-timeline-rail
    aria-hidden="true"
    className={`relative flex h-full min-h-12 justify-center ${className}`}
  />
}

function TimelineMarker({
  className = '',
  ...props
}: TimelineMarkerProps) {
  const status = useContext(TimelineItemStatusContext)
  return <span
    {...props}
    data-timeline-marker
    data-status={status}
    aria-hidden="true"
    className={`relative z-[1] mt-5 size-3 shrink-0 rounded-full border transition-colors duration-[var(--inteliscope-motion-standard)] ${status === 'current' ? 'border-accent bg-accent' : 'border-separator bg-surface-secondary'} ${className}`}
  />
}

function TimelineConnector({
  className = '',
  ...props
}: TimelineConnectorProps) {
  return <span
    {...props}
    data-timeline-connector
    aria-hidden="true"
    className={`absolute bottom-[var(--timeline-connector-bottom)] left-1/2 top-8 w-px -translate-x-1/2 bg-separator ${className}`}
  />
}

function TimelineContent({ className = '', ...props }: TimelineContentProps) {
  return <div
    {...props}
    data-timeline-content
    className={`min-w-0 ${className}`}
  />
}

export const Timeline = Object.assign(TimelineRoot, {
  Item: TimelineItem,
  Rail: TimelineRail,
  Marker: TimelineMarker,
  Connector: TimelineConnector,
  Content: TimelineContent,
})
