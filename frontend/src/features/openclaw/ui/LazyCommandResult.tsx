import { lazy, Suspense, type ComponentProps } from 'react'
import type { OpenClawCommandResult } from './OpenClawCommandResult'

const Result = lazy(() => import('./OpenClawCommandResult').then((module) => ({ default: module.OpenClawCommandResult })))

export function LazyCommandResult(props: ComponentProps<typeof OpenClawCommandResult>) {
  return <Suspense fallback={<p role="status" className="type-meta py-2 text-muted">正在打开快捷操作…</p>}><Result {...props} /></Suspense>
}
