import { AgentSessionDelete } from './AgentSessionDelete'
import { StatusIndicator } from '../../design-system'
import type { OpenClawWorkspaceController, OpenClawWorkspaceSession } from '../openclaw'
import { openClawSessionTitle } from '../openclaw/chat/openclawSessionTitle'

export function AgentSessionRow({ session, current, disabled, onOpen, firstQuestion, workspace, confirmBeforeDelete, onConfirmBeforeDeleteChange }: {
  workspace?: OpenClawWorkspaceController
  session: OpenClawWorkspaceSession; current: boolean; disabled: boolean
  onOpen: (session: OpenClawWorkspaceSession) => void; firstQuestion?: string
  confirmBeforeDelete?: boolean; onConfirmBeforeDeleteChange?: (enabled: boolean) => void
}) {
  const title = openClawSessionTitle(session, firstQuestion)
  return <div data-agent-session-row className={`group flex min-h-10 min-w-0 items-center gap-1 rounded-[var(--inteliscope-radius-control)] ${current ? 'bg-accent/10 text-foreground' : 'text-muted hover:bg-default'}`}>
    <button type="button" aria-current={current ? 'true' : undefined} aria-label={`打开会话：${title}`} disabled={disabled} onClick={() => onOpen(session)} className="type-control flex min-h-10 min-w-0 flex-1 items-center gap-2 rounded-[var(--inteliscope-radius-control)] px-3 text-left focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:min-h-11 disabled:cursor-default">
      <StatusIndicator iconOnly withTooltip={false} tone={session.hasActiveRun ? 'accent' : current ? 'success' : 'neutral'} label={session.hasActiveRun ? '生成中' : current ? '当前会话' : session.archived ? '已归档' : '历史会话'} />
      <span className="min-w-0 flex-1 truncate">{title}</span>
    </button>
    {workspace && <AgentSessionDelete session={session} current={current} workspace={workspace} disabled={disabled}
      confirmBeforeDelete={confirmBeforeDelete} onConfirmBeforeDeleteChange={onConfirmBeforeDeleteChange} />}
  </div>
}
