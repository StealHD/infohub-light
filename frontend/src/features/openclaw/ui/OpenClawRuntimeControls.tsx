import { lazy, Suspense } from 'react'

import type { OpenClawChatController } from '../openclawContracts'

const WorkspaceRuntimeControls = lazy(() => import('./OpenClawWorkspaceRuntimeControls'))

export function OpenClawRuntimeControls({ chat }: {
  chat: OpenClawChatController
  variant?: 'compact' | 'workspace'
}) {
  return <Suspense fallback={<div className="flex min-w-0 justify-end"><button type="button" disabled className="effort-picker-trigger type-control">选择思考</button></div>}>
    <WorkspaceRuntimeControls chat={chat} />
  </Suspense>
}
