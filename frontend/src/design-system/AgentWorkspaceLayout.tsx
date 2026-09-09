import { useState, type ReactNode } from 'react'

import { Drawer } from '@heroui/react'
import { Button } from './Button'
import { DisclosurePanel } from './DisclosurePanel'
import { X } from './icons'
import { useViewportWidth } from './useViewportWidth'

export function AgentInspectorFrame({ title, onClose, mobile = false, children }: { title: string; onClose: () => void; mobile?: boolean; children: ReactNode }) {
  return <div className="flex h-full min-h-0 flex-col" data-agent-inspector-frame>
    <header className="shrink-0 border-b border-separator px-4 py-3">
      {mobile && <span className="mx-auto mb-2 block h-1 w-10 rounded-full bg-separator" aria-hidden="true" />}
      <div className="flex min-h-8 items-center gap-2">
        <h2 className="type-page-title min-w-0 flex-1 truncate">{title}</h2>
        <Button variant="ghost" size="sm" isIconOnly aria-label={`关闭${title}`} onPress={onClose}><X size={16} aria-hidden="true" /></Button>
      </div>
    </header>
    <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
  </div>
}

export function WorkspaceDrawer({
  open,
  onOpenChange,
  title,
  placement,
  frameContent = false,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  placement: 'left' | 'right' | 'bottom'
  frameContent?: boolean
  children: ReactNode
}) {
  return <Drawer isOpen={open} onOpenChange={onOpenChange}>
    <Drawer.Backdrop variant="blur">
      <Drawer.Content placement={placement}>
        <Drawer.Dialog
          aria-label={title}
          className={`${placement === 'bottom' ? 'max-h-[86dvh] rounded-t-[var(--inteliscope-radius-panel)]' : 'w-[min(92vw,var(--inteliscope-width-agent-inspector))]'} bg-surface p-0 outline-none`}
        >
          {!frameContent && <Drawer.Header className="border-b border-separator px-4 py-3">
            <Drawer.Heading>{title}</Drawer.Heading>
          </Drawer.Header>}
          <Drawer.Body className="min-h-0 overflow-hidden p-0">{frameContent
            ? <AgentInspectorFrame title={title} mobile={placement === 'bottom'} onClose={() => onOpenChange(false)}>{children}</AgentInspectorFrame>
            : children}</Drawer.Body>
        </Drawer.Dialog>
      </Drawer.Content>
    </Drawer.Backdrop>
  </Drawer>
}

export function AgentWorkspaceLayout({
  sidebar,
  children,
  inspector,
  inspectorTitle,
  sidebarOpen,
  onSidebarOpenChange,
  inspectorOpen,
  onInspectorOpenChange,
}: {
  sidebar: ReactNode
  children: ReactNode
  inspector?: ReactNode
  inspectorTitle: string
  sidebarOpen: boolean
  onSidebarOpenChange: (open: boolean) => void
  inspectorOpen: boolean
  onInspectorOpenChange: (open: boolean) => void
}) {
  const [lastInspector, setLastInspector] = useState({ content: inspector, title: inspectorTitle })
  if (inspector && (lastInspector.content !== inspector || lastInspector.title !== inspectorTitle)) setLastInspector({ content: inspector, title: inspectorTitle })
  const viewportWidth = useViewportWidth()
  const desktop = viewportWidth >= 1024
  const wide = viewportWidth >= 1440
  const mobile = viewportWidth < 768

  return <div data-agent-workspace-layout className="flex h-full min-h-0 min-w-0 overflow-hidden bg-background">
    {desktop && <aside
      aria-label="OpenClaw 会话"
      className="flex min-h-0 w-[var(--inteliscope-width-agent-sidebar)] shrink-0 flex-col overflow-hidden border-r border-separator bg-surface"
    >{sidebar}</aside>}

    <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
      {children}
    </section>

    {wide && <DisclosurePanel width="var(--inteliscope-width-agent-inspector)" open={Boolean(inspectorOpen && inspector)} label={inspectorTitle + '检查器'}>
      <AgentInspectorFrame title={inspectorTitle} onClose={() => onInspectorOpenChange(false)}>{inspector}</AgentInspectorFrame>
    </DisclosurePanel>}

    {!desktop && <WorkspaceDrawer
      open={sidebarOpen}
      onOpenChange={onSidebarOpenChange}
      title="OpenClaw 会话"
      placement={mobile ? 'bottom' : 'left'}
    >{sidebar}</WorkspaceDrawer>}

    {!wide && <WorkspaceDrawer
      open={inspectorOpen}
      onOpenChange={onInspectorOpenChange}
      title={inspector ? inspectorTitle : lastInspector.title}
      placement={mobile ? 'bottom' : 'right'}
      frameContent
    >{inspector ?? lastInspector.content}</WorkspaceDrawer>}
  </div>
}
