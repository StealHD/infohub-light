import { useState } from 'react'

import { Button, Drawer, Icons, PageHeader, OverflowValue, StatusIndicator, ThemeModeToggle, Tooltip, TooltipTriggerButton } from '../../design-system'
import type { OpenClawChatController, OpenClawWorkspaceSession } from '../openclaw'
import { WorkspaceSwitcher } from '../workbench-live/WorkspaceSwitcher'
import { routeForInspector, type OpenClawInspector } from './agentWorkspaceModel'
import { AgentUseCasesDialog } from './AgentUseCasesDialog'

const inspectorActions = [
  { id: 'context' as const, label: '上下文', icon: Icons.Layers3 },
  { id: 'tasks' as const, label: 'Tasks', icon: Icons.ListChecks },
  { id: 'artifacts' as const, label: 'Artifacts', icon: Icons.FileText },
]

export function AgentWorkspaceHeader({
  chat,
  current,
  inspector,
  userId,
  pageTitle,
  onOpenSessions,
  onNavigate,
}: {
  chat: OpenClawChatController
  current?: OpenClawWorkspaceSession
  inspector: OpenClawInspector
  userId: string
  pageTitle?: string
  onOpenSessions: () => void
  onNavigate: (route: string) => void
}) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [examplesOpen, setExamplesOpen] = useState(false)
  const label = current?.label
  const generatedLabel = !label || label === current?.key || /^(?:Inscope|Inteliscope) · .+ · [a-f0-9-]+$/iu.test(label)
  const title = pageTitle ?? (generatedLabel ? 'OpenClaw 对话' : label)
  const connectionLabel = chat.status === 'connected'
    ? chat.isRunning ? '正在运行' : 'Gateway 已连接'
    : chat.status === 'reconnecting' ? '正在重连' : 'Gateway 未连接'
  const connectionTone = chat.status === 'connected' ? chat.isRunning ? 'accent' : 'success' : chat.status === 'error' ? 'danger' : 'neutral'

  return <><PageHeader title={title} className="absolute inset-x-0 top-0 z-20" leading={<>
    <span className="min-[1024px]:hidden"><WorkspaceSwitcher userId={userId} compact placement="bottom start" /></span>
    <Button
      variant="ghost"
      size="sm"
      isIconOnly
      className="min-[1024px]:hidden"
      aria-label="打开 OpenClaw 会话"
      onPress={onOpenSessions}
    ><Icons.Rows3 size={17} aria-hidden="true" /></Button>
    <StatusIndicator tone={connectionTone} label={connectionLabel} iconOnly />
    </>} actions={<>
    {current?.worktree?.branch && <span className="hidden min-w-0 max-w-40 min-[1024px]:inline-flex"><OverflowValue value={current.worktree.branch} ariaLabel="当前分支" className="type-meta text-muted" /></span>}
    <nav aria-label="OpenClaw 检查器" className="hidden items-center gap-1 min-[768px]:flex">
      {inspectorActions.map(({ id, label, icon: Icon }) => <Tooltip key={id} delay={250}>
        <TooltipTriggerButton
          aria-label={inspector === id ? `关闭${label}` : `打开${label}`}
          aria-pressed={inspector === id}
          className={`size-8 rounded-[var(--inteliscope-radius-control)] hover:bg-default ${inspector === id ? 'bg-accent/15 text-accent' : 'text-muted'}`}
          onClick={() => onNavigate(routeForInspector(inspector === id ? null : id))}
        ><Icon size={16} aria-hidden="true" /></TooltipTriggerButton>
        <Tooltip.Content placement="bottom" offset={8}>{inspector === id ? `关闭${label}` : `打开${label}`}</Tooltip.Content>
      </Tooltip>)}
    </nav>
    <span className="hidden min-[768px]:inline-flex"><ThemeModeToggle /></span>
    <Button variant="ghost" size="sm" className="hidden min-[768px]:inline-flex" onPress={() => setExamplesOpen(true)}><Icons.BookOpen size={15} aria-hidden="true" />使用示例</Button>
    <Drawer isOpen={mobileMenuOpen} onOpenChange={setMobileMenuOpen}>
      <Drawer.Trigger className="flex size-10 items-center justify-center rounded-[var(--inteliscope-radius-control)] text-muted hover:bg-default focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11 min-[768px]:hidden" aria-label="打开更多操作" render={(props) => <button {...props} type="button" />}><Icons.MoreHorizontal size={18} aria-hidden="true" /></Drawer.Trigger>
      <Drawer.Backdrop variant="blur"><Drawer.Content placement="bottom"><Drawer.Dialog aria-label="OpenClaw 更多操作" className="max-h-[72dvh] rounded-t-[var(--inteliscope-radius-panel)] bg-surface p-0 outline-none">
        <Drawer.Header className="border-b border-separator px-4 py-3"><Drawer.Heading>更多操作</Drawer.Heading></Drawer.Header>
        <Drawer.Body className="grid gap-1 p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          {inspectorActions.map(({ id, label, icon: Icon }) => <Button key={id} variant="ghost" className="min-h-11 justify-start" onPress={() => { setMobileMenuOpen(false); onNavigate(routeForInspector(id)) }}><Icon size={17} aria-hidden="true" />{label}{inspector === id && <Icons.Check size={16} className="ml-auto" aria-hidden="true" />}</Button>)}
          <div className="flex min-h-11 items-center justify-between rounded-[var(--inteliscope-radius-control)] px-3"><span className="type-control">主题</span><ThemeModeToggle /></div>
          <Button variant="ghost" className="min-h-11 justify-start" onPress={() => { setMobileMenuOpen(false); setExamplesOpen(true) }}><Icons.BookOpen size={17} aria-hidden="true" />使用示例</Button>
        </Drawer.Body>
      </Drawer.Dialog></Drawer.Content></Drawer.Backdrop>
    </Drawer>
  </>} />
  <AgentUseCasesDialog open={examplesOpen} onOpenChange={setExamplesOpen} /></>
}
