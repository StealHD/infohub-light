import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import { Button, Drawer, Icons, Popover } from '../../design-system'
import {
  readWorkspaceRoute,
  rememberWorkspaceRoute,
  workspaceModeForPath,
  type WorkspaceMode,
} from './workspaceRoutePreference'

const workspaceOptions = [
  {
    id: 'inscope' as const,
    label: 'Inscope',
    description: '订阅、阅读与追踪',
    icon: Icons.InteliscopeMark,
  },
  {
    id: 'openclaw' as const,
    label: 'OpenClaw',
    description: '对话、执行与自动化',
    icon: Icons.Bot,
  },
]

export function WorkspaceSwitcher({
  userId,
  compact = false,
  placement = 'bottom start',
}: {
  userId: string
  compact?: boolean
  placement?: 'bottom start' | 'right top'
}) {
  const location = useLocation()
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const [viewportWidth, setViewportWidth] = useState(() => typeof window === 'undefined' ? 1440 : window.innerWidth)
  const popoverTriggerRef = useRef<HTMLButtonElement | null>(null)
  const sheetTriggerRef = useRef<HTMLButtonElement | null>(null)
  const mode = workspaceModeForPath(location.pathname)
  const active = workspaceOptions.find((option) => option.id === mode) ?? workspaceOptions[0]
  const ActiveIcon = active.icon
  const mobileSheet = compact && viewportWidth < 768

  useEffect(() => {
    rememberWorkspaceRoute(userId, location.pathname)
  }, [location.pathname, userId])

  useEffect(() => {
    const key = `workspace-focus:${userId}`
    if (window.sessionStorage.getItem(key) !== mode) return
    window.sessionStorage.removeItem(key)
    window.requestAnimationFrame(() => (mobileSheet ? sheetTriggerRef.current : popoverTriggerRef.current)?.focus())
  }, [mobileSheet, mode, userId])

  useEffect(() => {
    const update = () => setViewportWidth(window.innerWidth)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  function switchWorkspace(next: WorkspaceMode) {
    updateOpen(false)
    if (next === mode) return
    window.sessionStorage.setItem(`workspace-focus:${userId}`, next)
    navigate(readWorkspaceRoute(userId, next))
  }

  function updateOpen(next: boolean) {
    setOpen(next)
    if (!next && open) window.requestAnimationFrame(() => (mobileSheet ? sheetTriggerRef.current : popoverTriggerRef.current)?.focus())
  }

  const options = workspaceOptions.map((option) => {
    const selected = option.id === mode
    return <Button
      key={option.id}
      variant="ghost"
      className={`h-auto min-h-13 w-full min-w-0 justify-start gap-2 px-2 py-2 text-left ${selected ? 'bg-default text-foreground' : ''}`}
      aria-current={selected ? 'page' : undefined}
      onPress={() => switchWorkspace(option.id)}
    >
      <span className="min-w-0 flex-1">
        <span className="type-control block truncate">{option.label}</span>
        <span className="type-meta block truncate text-muted">{option.description}</span>
      </span>
      {selected && <Icons.Check size={14} className="shrink-0" aria-hidden="true" />}
    </Button>
  })

  const trigger = <>
    <ActiveIcon size={18} className="shrink-0 text-accent" aria-hidden="true" />
    {!compact && <span className="type-control min-w-0 flex-1 truncate">{active.label}</span>}
    {!compact && <Icons.ChevronDown size={14} className="shrink-0 text-muted" aria-hidden="true" />}
  </>
  const triggerProps = {
    'aria-label': `切换工作区，当前为 ${active.label}`,
    className: compact
      ? 'flex size-8 shrink-0 items-center justify-center rounded-[var(--inteliscope-radius-control)] text-foreground hover:bg-default focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11'
      : 'flex h-10 min-w-0 flex-1 items-center gap-2 rounded-[var(--inteliscope-radius-card)] bg-default/70 px-3 text-left hover:bg-default focus-visible:outline-2 focus-visible:outline-focus',
  }

  if (mobileSheet) return <Drawer isOpen={open} onOpenChange={updateOpen}>
    <Drawer.Trigger ref={sheetTriggerRef} {...triggerProps} render={(props) => <button {...props} type="button" />}>{trigger}</Drawer.Trigger>
    <Drawer.Backdrop variant="blur">
      <Drawer.Content placement="bottom">
        <Drawer.Dialog aria-label="切换工作区" className="max-h-[70dvh] rounded-t-[var(--inteliscope-radius-panel)] bg-surface p-0 outline-none">
          <Drawer.Header className="border-b border-separator px-4 py-3"><Drawer.Heading>切换工作区</Drawer.Heading></Drawer.Header>
          <Drawer.Body className="grid gap-1 p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))]">{options}</Drawer.Body>
        </Drawer.Dialog>
      </Drawer.Content>
    </Drawer.Backdrop>
  </Drawer>

  return <Popover isOpen={open} onOpenChange={updateOpen}>
    <Popover.Trigger<'button'> ref={popoverTriggerRef} {...triggerProps} render={(props) => <button {...props} type="button" />}>{trigger}</Popover.Trigger>
    <Popover.Content placement={placement} offset={8} containerPadding={12} className="workspace-switcher-popover z-50 p-0">
      <Popover.Dialog aria-label="切换工作区" className="grid gap-1 p-2">{options}</Popover.Dialog>
    </Popover.Content>
  </Popover>
}
