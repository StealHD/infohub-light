import { lazy, Suspense } from 'react'
const AgentSessionDelete = lazy(() => import('./AgentSessionDelete').then(module => ({ default: module.AgentSessionDelete })))
import { Button, Icons, Popover, StatusIndicator } from '../../design-system'
import type { OpenClawWorkspaceController, OpenClawWorkspaceSession } from '../openclaw'
import { openClawSessionTitle } from '../openclaw/chat/openclawSessionTitle'

export function AgentSessionRow({ session, current, disabled, onOpen, firstQuestion, workspace }: {
  workspace?: OpenClawWorkspaceController
  session: OpenClawWorkspaceSession; current: boolean; disabled: boolean
  onOpen: (session: OpenClawWorkspaceSession) => void; firstQuestion?: string
}) {
  const title = openClawSessionTitle(session, firstQuestion)
  return <div data-agent-session-row className={`flex min-h-10 min-w-0 items-center gap-1 rounded-[var(--inteliscope-radius-control)] ${current ? 'bg-accent/10 text-foreground' : 'text-muted hover:bg-default'}`}>
    <button type="button" aria-current={current ? 'true' : undefined} aria-label={`打开会话：${title}`} disabled={disabled} onClick={() => onOpen(session)} className="type-control flex min-h-10 min-w-0 flex-1 items-center gap-2 rounded-[var(--inteliscope-radius-control)] px-3 text-left focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:min-h-11 disabled:cursor-default">
      <StatusIndicator iconOnly withTooltip={false} tone={session.hasActiveRun ? 'accent' : current ? 'success' : 'neutral'} label={session.hasActiveRun ? '生成中' : current ? '当前会话' : session.archived ? '已归档' : '历史会话'} />
      <span className="min-w-0 flex-1 truncate">{title}</span>
    </button>
    <Popover>
      <Popover.Trigger aria-label={`会话详情：${title}`} className="flex size-8 shrink-0 items-center justify-center rounded-[var(--inteliscope-radius-control)] text-muted hover:bg-default focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11"><Icons.MoreHorizontal size={16} aria-hidden="true" /></Popover.Trigger>
      <Popover.Content placement="bottom start" containerPadding={12} className="max-w-[min(360px,calc(100vw-24px))] p-0">
        <Popover.Dialog aria-label="会话详情" className="grid gap-3 p-3">
          <p className="type-control [overflow-wrap:anywhere]">{title}</p>
          {session.worktree?.branch && <p className="type-meta text-muted [overflow-wrap:anywhere]">{session.worktree.branch}</p>}
          <Button variant="secondary" isDisabled={disabled} onPress={() => onOpen(session)}>打开会话</Button>
          {workspace && <Suspense fallback={null}><AgentSessionDelete session={session} current={current} workspace={workspace} disabled={disabled} /></Suspense>}
        </Popover.Dialog>
      </Popover.Content>
    </Popover>
  </div>
}
