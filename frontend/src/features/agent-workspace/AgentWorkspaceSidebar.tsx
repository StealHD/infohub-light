import { useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

import type { User } from '../../api/types'
import {
  Button,
  EmptyState,
  Icons,
  LoadingState,
  Separator,
  StableAsyncButton,
  StatusNotice,
  actionToast,
} from '../../design-system'
import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'
import { WorkspaceSwitcher } from '../workbench-live/WorkspaceSwitcher'
import { WorkspaceAccountMenu } from '../workbench-live/WorkspaceAccountMenu'
import { AgentSessionRow } from './AgentSessionRow'
import { AgentSessionHistory } from './AgentSessionHistory'
import { recentSessionRows, useAgentSessionDirectory } from './useAgentSessionDirectory'
import { AgentWorktreeDialog } from './AgentWorktreeDialog'
import type { AgentWorkspaceSessionState } from './useAgentWorkspaceSessions'

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
  writeTrusted,
  onRequireWriteTrust,
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
  const [worktreeOpen, setWorktreeOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const opening = useRef(false)
  const directory = useAgentSessionDirectory(chat, user.id)
  const rows = recentSessionRows(directory.page?.sessions ?? [], sessions.current)
  const firstQuestion = chat.messages.find((message) => message.role === 'user')?.text
  const switchingDisabled = chat.isRunning || chat.runtimeUpdating
  const canCreate = chat.status === 'connected'
    && !switchingDisabled
    && chat.workspace.capabilities()['sessions.create']

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
      <div className="grid grid-cols-[minmax(0,1fr)_40px] gap-2">
        <StableAsyncButton
          variant="secondary"
          pending={false}
          pendingContent="新建中…"
          isDisabled={chat.status !== 'connected' || switchingDisabled}
          className="justify-start"
          onPress={async () => { if (await chat.newConversation()) { navigate('/agent'); onNavigate() } }}
        >
          <Icons.Plus size={16} aria-hidden="true" />新对话
        </StableAsyncButton>
        <Button
          variant="secondary"
          isIconOnly
          aria-label="在新 Worktree 中执行"
          isDisabled={!canCreate}
          onPress={() => writeTrusted ? setWorktreeOpen(true) : onRequireWriteTrust()}
        ><Icons.GitCompareArrows size={16} aria-hidden="true" /></Button>
      </div>

      <p className="type-label mt-5 px-2 pb-2 text-muted">会话</p>
      {chat.sessionKey ? <div className="grid gap-1">
        {rows.map((session) => <AgentSessionRow
          key={session.key} session={session}
          current={session.key === chat.sessionKey}
          firstQuestion={session.key === chat.sessionKey ? firstQuestion : undefined}
          disabled={session.key !== chat.sessionKey && switchingDisabled} onOpen={(target) => { void openSession(target) }}
        />)}
        <Button variant="ghost" className="justify-start text-muted" onPress={() => setHistoryOpen(true)}>全部会话</Button>
      </div> : chat.status === 'connected'
        ? <EmptyState title="等待 Session" description="Gateway 已连接，正在等待当前 Session。" />
        : <EmptyState title="连接 OpenClaw" description="在对话区完成 Gateway 连接后，会话会显示在这里。" actions={<Button variant="secondary" onPress={() => { navigate('/agent'); onNavigate() }}>前往连接</Button>} />}
      {directory.loading && !sessions.current && <LoadingState label="正在读取会话" rows={2} />}
      {directory.error && <div className="mt-2"><StatusNotice title="会话暂不可用" status="warning">{directory.error}</StatusNotice></div>}
      <p role="status" className="sr-only">{chat.runtimeUpdating ? '正在更新会话，请稍候。' : chat.isRunning ? '当前生成完成或取消后才可切换会话。' : ''}</p>

      <Separator className="my-4" />
      <p className="type-label px-2 pb-2 text-muted">工作区</p>
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
    <AgentSessionHistory open={historyOpen} onOpenChange={setHistoryOpen} chat={chat} userId={user.id} onOpen={openSession} />

    <AgentWorktreeDialog
      open={worktreeOpen}
      onOpenChange={setWorktreeOpen}
      workspace={chat.workspace}
      onCreated={() => { sessions.refresh(); directory.refresh() }}
    />
  </div>
}
