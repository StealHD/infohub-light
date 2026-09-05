import { useState } from 'react'
import { NavLink } from 'react-router-dom'

import type { User } from '../../api/types'
import {
  AvatarFallback,
  AvatarRoot,
  Button,
  EmptyState,
  Icons,
  LoadingState,
  Separator,
  StableAsyncButton,
  StatusIndicator,
  StatusNotice,
  actionToast,
} from '../../design-system'
import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'
import { WorkspaceSwitcher } from '../workbench-live/WorkspaceSwitcher'
import { AgentWorktreeDialog } from './AgentWorktreeDialog'
import type { AgentWorkspaceSessionState } from './useAgentWorkspaceSessions'

const workspaceLinks = [
  { to: '/agent/skills', label: 'Skills', icon: Icons.Sparkles },
  { to: '/agent/automations', label: 'Automations', icon: Icons.Clock3 },
] as const

function SessionRow({
  session,
  current,
  depth,
  disabled,
  onOpen,
}: {
  session: OpenClawWorkspaceSession
  current: boolean
  depth: number
  disabled: boolean
  onOpen: (session: OpenClawWorkspaceSession) => void
}) {
  const inset = depth > 1 ? 'ml-6' : depth === 1 ? 'ml-3' : ''
  if (current) return <div className={`${inset} rounded-[var(--inteliscope-radius-control)] bg-accent/10 px-3 py-2.5`}>
    <span className="type-control block truncate">{session.label}</span>
    <span className="type-meta mt-1 flex min-w-0 items-center gap-2 text-muted">
      <StatusIndicator tone={session.hasActiveRun ? 'accent' : 'success'} label={session.hasActiveRun ? '生成中' : '当前'} />
      {session.worktree?.branch && <span className="min-w-0 truncate">{session.worktree.branch}</span>}
    </span>
  </div>
  return <button
    type="button"
    disabled={disabled}
    className={`${inset} min-w-0 rounded-[var(--inteliscope-radius-control)] px-3 py-2.5 text-left text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-55`}
    onClick={() => onOpen(session)}
  >
    <span className="type-control flex min-w-0 items-center gap-2">
      <Icons.GitCompareArrows size={15} className="shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">{session.label}</span>
    </span>
    <span className="type-meta mt-1 block truncate">
      {session.worktree?.branch ?? '子 Session'} · {session.createdActor?.label ?? session.createdVia ?? '来源已验证'}
    </span>
  </button>
}

export function AgentWorkspaceSidebar({
  chat,
  sessions,
  user,
  onNavigate,
  writeTrusted,
  onRequireWriteTrust,
}: {
  chat: OpenClawChatController
  sessions: AgentWorkspaceSessionState
  user: User
  onNavigate: () => void
  writeTrusted: boolean
  onRequireWriteTrust: () => void
}) {
  const [worktreeOpen, setWorktreeOpen] = useState(false)
  const switchingDisabled = chat.isRunning || chat.runtimeUpdating
  const canCreate = chat.status === 'connected'
    && !switchingDisabled
    && chat.workspace.capabilities()['sessions.create']

  async function openSession(session: OpenClawWorkspaceSession) {
    if (switchingDisabled) return
    if (await chat.openSession(session.key)) {
      onNavigate()
      return
    }
    actionToast.danger('无法切换 Session', { description: '当前对话仍保持不变。' })
  }

  return <div className="flex h-full min-h-0 flex-col" data-agent-workspace-sidebar>
    <div className="flex h-[var(--inteliscope-size-page-header)] shrink-0 items-center border-b border-separator px-2">
      <WorkspaceSwitcher userId={user.id} />
    </div>

    <div className="quiet-scroll-region min-h-0 flex-1 overflow-y-auto px-3 py-4">
      <div className="grid grid-cols-[minmax(0,1fr)_40px] gap-2">
        <StableAsyncButton
          variant="secondary"
          pending={chat.runtimeUpdating}
          pendingContent="新建中…"
          isDisabled={chat.status !== 'connected' || chat.isRunning}
          className="justify-start"
          onPress={() => chat.newConversation()}
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
        {sessions.tree.map(({ session, depth }) => <SessionRow
          key={session.key}
          session={session}
          current={session.key === chat.sessionKey}
          depth={depth}
          disabled={switchingDisabled}
          onOpen={(target) => void openSession(target)}
        />)}
      </div> : chat.status === 'connected'
        ? <EmptyState title="等待 Session" description="Gateway 已连接，正在等待当前 Session。" />
        : <EmptyState title="连接 OpenClaw" description="在对话区完成 Gateway 连接后，会话会显示在这里。" />}
      {sessions.loading && !sessions.current && <LoadingState label="正在读取会话" rows={2} />}
      {sessions.error && <div className="mt-2"><StatusNotice title="会话暂不可用" status="warning">{sessions.error}</StatusNotice></div>}
      {switchingDisabled && sessions.tree.length > 1 && <p className="type-meta mt-3 px-2 text-muted">当前生成完成或取消后才可切换 Session。</p>}

      <Separator className="my-4" />
      <p className="type-label px-2 pb-2 text-muted">工作区</p>
      <nav aria-label="OpenClaw 工作区" className="grid gap-1">
        {workspaceLinks.map(({ to, label, icon: Icon }) => <NavLink
          key={to}
          to={to}
          onClick={onNavigate}
          className="type-control flex min-h-10 items-center gap-3 rounded-[var(--inteliscope-radius-control)] px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus aria-[current=page]:bg-default aria-[current=page]:text-foreground"
        ><Icon size={17} aria-hidden="true" />{label}</NavLink>)}
        <NavLink
          to="/agents"
          onClick={onNavigate}
          className="type-control flex min-h-10 items-center gap-3 rounded-[var(--inteliscope-radius-control)] px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
        ><Icons.Unplug size={17} aria-hidden="true" />助手连接</NavLink>
      </nav>
    </div>

    <NavLink
      to="/users"
      className="flex h-[var(--inteliscope-size-sidebar-footer)] shrink-0 items-center gap-3 border-t border-separator px-4 hover:bg-default focus-visible:outline-2 focus-visible:outline-focus"
    >
      <AvatarRoot className="size-8 shrink-0"><AvatarFallback>{(user.display_name || user.username).slice(0, 1).toUpperCase()}</AvatarFallback></AvatarRoot>
      <span className="min-w-0 flex-1">
        <span className="type-control block truncate">{user.display_name || user.username}</span>
        <span className="type-meta block truncate text-muted">账户与成员</span>
      </span>
      <Icons.ChevronRight size={15} className="shrink-0 text-muted" aria-hidden="true" />
    </NavLink>

    <AgentWorktreeDialog
      open={worktreeOpen}
      onOpenChange={setWorktreeOpen}
      workspace={chat.workspace}
      onCreated={sessions.refresh}
    />
  </div>
}
