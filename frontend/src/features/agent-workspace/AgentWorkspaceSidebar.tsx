import { useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import type { User } from '../../api/types'
import {
  Button,
  EmptyState,
  Icons,
  LoadingState,
  StatusNotice,
  Tooltip,
  TooltipTriggerButton,
  actionToast,
  topAnchoredTooltipProps,
} from '../../design-system'
import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'
import { WorkspaceSwitcher } from '../workbench-live/WorkspaceSwitcher'
import { WorkspaceAccountMenu } from '../workbench-live/WorkspaceAccountMenu'
import { AgentSessionRow } from './AgentSessionRow'
import { AgentSessionHistory } from './AgentSessionHistory'
import { recentSessionRows, useAgentSessionDirectory } from './useAgentSessionDirectory'
import type { AgentWorkspaceSessionState } from './useAgentWorkspaceSessions'
import { readSessionDeleteConfirmation, writeSessionDeleteConfirmation } from './sessionDeletePreference'

const workspaceLinks = [
  { to: '/agent/skills', label: 'Skills', icon: Icons.Sparkles },
  { to: '/agent/automations', label: 'Automations', icon: Icons.Clock3 },
  { to: '/agent/examples', label: '使用示例', icon: Icons.BookOpen },
] as const

export function AgentWorkspaceSidebar({
  chat,
  sessions,
  user,
  onNavigate,
  onLogout,
}: {
  chat: OpenClawChatController
  sessions: AgentWorkspaceSessionState
  user: User
  onNavigate: () => void
  onLogout: () => void
  writeTrusted: boolean
  onRequireWriteTrust: () => void
}) {
  const navigate = useNavigate()
  const [historyOpen, setHistoryOpen] = useState(false)
  const [deleteConfirmationByUser, setDeleteConfirmationByUser] = useState<Record<string, boolean>>(
    () => ({ [user.id]: readSessionDeleteConfirmation(user.id) }),
  )
  const opening = useRef(false)
  const directory = useAgentSessionDirectory(chat, user.id)
  const rows = recentSessionRows(directory.page?.sessions ?? [], sessions.current)
  const firstQuestion = chat.messages.find((message) => message.role === 'user')?.text
  const switchingDisabled = chat.isRunning || chat.runtimeUpdating
  const confirmBeforeDelete = deleteConfirmationByUser[user.id] ?? readSessionDeleteConfirmation(user.id)

  function updateDeleteConfirmation(enabled: boolean) {
    const stored = writeSessionDeleteConfirmation(user.id, enabled)
    setDeleteConfirmationByUser((current) => ({ ...current, [user.id]: stored ? enabled : true }))
  }

  async function openSession(session: OpenClawWorkspaceSession): Promise<boolean> {
    if (opening.current || chat.runtimeUpdating) return false
    if (session.key === chat.sessionKey) { navigate('/agent'); onNavigate(); return true }
    if (switchingDisabled) return false
    opening.current = true
    try {
      if (await chat.openSession(session.key, session.agentId)) {
        navigate('/agent'); onNavigate()
        return true
      }
      actionToast.danger('无法切换会话', { description: '当前对话仍保持不变。' })
      return false
    } finally { opening.current = false }
  }

  return <div className="flex h-full min-h-0 flex-col" data-agent-workspace-sidebar>
    <div className="flex h-[var(--inteliscope-size-page-header)] shrink-0 items-center border-b border-separator px-2">
      <WorkspaceSwitcher userId={user.id} />
    </div>

    <div className="quiet-scroll-region min-h-0 flex-1 overflow-y-auto px-3 py-4">
      <div className="flex min-h-8 items-center justify-between gap-2 pb-2 pl-2">
        <p className="type-label text-muted">会话</p>
        <div className="flex shrink-0 items-center gap-1">
          <Tooltip delay={250}>
            <TooltipTriggerButton
              aria-label="全部会话"
              className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground"
              onClick={() => setHistoryOpen(true)}
            ><Icons.History size={15} aria-hidden="true" /></TooltipTriggerButton>
            <Tooltip.Content {...topAnchoredTooltipProps}>全部会话</Tooltip.Content>
          </Tooltip>
          <Tooltip delay={250}>
            <TooltipTriggerButton
              aria-label="新对话"
              pending={chat.runtimeUpdating}
              disabled={chat.status !== 'connected' || switchingDisabled}
              className="size-8 shrink-0 rounded-lg text-accent hover:bg-accent/10"
              onClick={async () => { if (await chat.newConversation()) { navigate('/agent'); onNavigate() } }}
            ><Icons.Plus size={16} aria-hidden="true" /></TooltipTriggerButton>
            <Tooltip.Content {...topAnchoredTooltipProps}>新对话</Tooltip.Content>
          </Tooltip>
        </div>
      </div>
      {chat.sessionKey ? <div className="grid gap-1">
        {rows.map((session) => <AgentSessionRow workspace={chat.workspace}
          key={session.key} session={session}
          current={session.key === chat.sessionKey}
          firstQuestion={session.key === chat.sessionKey ? firstQuestion : undefined}
          disabled={session.key !== chat.sessionKey && switchingDisabled} onOpen={(target) => { void openSession(target) }}
          confirmBeforeDelete={confirmBeforeDelete} onConfirmBeforeDeleteChange={updateDeleteConfirmation}
        />)}
      </div> : chat.status === 'connected'
        ? <EmptyState title="等待 Session" description="Gateway 已连接，正在等待当前 Session。" />
        : <EmptyState title="连接 OpenClaw" description="在对话区完成 Gateway 连接后，会话会显示在这里。" actions={<Button variant="secondary" onPress={() => { navigate('/agent'); onNavigate() }}>前往连接</Button>} />}
      {directory.loading && !sessions.current && <LoadingState label="正在读取会话" rows={2} />}
      {directory.error && <div className="mt-2"><StatusNotice title="会话暂不可用" status="warning">{directory.error}</StatusNotice></div>}
      <p role="status" className="sr-only">{chat.runtimeUpdating ? '正在更新会话，请稍候。' : chat.isRunning ? '当前生成完成或取消后才可切换会话。' : ''}</p>

      <p className="type-label mt-4 px-2 pb-2 text-muted">工作区</p>
      <nav aria-label="OpenClaw 工作区" className="grid gap-1">
        {workspaceLinks.map(({ to, label, icon: Icon }) => <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className="type-control flex min-h-10 items-center gap-3 rounded-[var(--inteliscope-radius-control)] px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus aria-[current=page]:bg-default aria-[current=page]:text-foreground"
        ><Icon size={17} aria-hidden="true" />{label}</NavLink>)}

      </nav>
    </div>

    <div className="flex h-[var(--inteliscope-size-sidebar-footer)] shrink-0 items-center border-t border-separator p-2">
      <WorkspaceAccountMenu user={user} onLogout={onLogout} variant="agent" />
    </div>
    <AgentSessionHistory open={historyOpen} onOpenChange={setHistoryOpen} chat={chat} userId={user.id} onOpen={openSession}
      confirmBeforeDelete={confirmBeforeDelete} onConfirmBeforeDeleteChange={updateDeleteConfirmation} />

  </div>
}
