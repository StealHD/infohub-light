import { lazy, Suspense, type ComponentProps } from 'react'
import { CalmSkeleton } from '../../design-system'
import type { SourceOverviewFeed as SourceOverview } from './SourceOverviewFeed'

export type { SourceSummaryViewState } from './SourceOverviewFeed'
const Overview = lazy(() => import('./SourceOverviewFeed').then((module) => ({ default: module.SourceOverviewFeed })))

export function SourceOverviewFeed(props: ComponentProps<typeof SourceOverview>) {
  return <Suspense fallback={<div role="status" aria-label="正在加载专题速览" className="min-h-0 flex-1"><CalmSkeleton /></div>}>
    <Overview {...props} />
  </Suspense>
}
