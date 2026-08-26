import { useMemo, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import type { User } from '../../api/types'
import { SettingsSidebar } from '../../components/settings'
import { Button, Drawer, Icons, PageHeader, ThemeModeToggle } from '../../design-system'
import { settingsWorkspaceTitle } from './settingsNavigation'
import { settingsReturnToFromState } from './settingsReturnState'

export function SettingsLayout({ user, children }: { user: User; children: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const returnTo = useMemo(() => settingsReturnToFromState(location.state), [location.state])
  const title = settingsWorkspaceTitle(location.pathname, location.hash)
  const goBack = () => navigate(returnTo)

  return <div
    data-settings-workspace
    className="grid h-dvh min-h-0 min-w-0 grid-rows-[var(--inteliscope-size-page-header)_minmax(0,1fr)] overflow-hidden bg-background min-[768px]:grid-cols-[var(--inteliscope-width-settings-sidebar)_minmax(0,1fr)]"
  >
    <aside
      aria-label="设置侧栏"
      className="hidden min-h-0 border-r border-separator min-[768px]:row-span-2 min-[768px]:block"
    >
      <SettingsSidebar role={user.role} returnTo={returnTo} onBack={goBack} />
    </aside>

    <PageHeader
      title={title}
      className="relative z-20 col-start-1 row-start-1 min-w-0 gap-1 min-[768px]:col-start-2 min-[768px]:gap-2"
      leading={<>
        <Button
          size="sm"
          variant="ghost"
          isIconOnly
          aria-label="返回应用"
          className="min-[768px]:hidden"
          onPress={goBack}
        ><Icons.ArrowLeft size={18} aria-hidden="true" /></Button>
        <Button
          size="sm"
          variant="ghost"
          isIconOnly
          aria-label="打开设置导航"
          aria-expanded={mobileSidebarOpen}
          className="min-[768px]:hidden"
          onPress={() => setMobileSidebarOpen(true)}
        ><Icons.Menu size={18} aria-hidden="true" /></Button>
      </>}
      actions={<ThemeModeToggle />}
    />

    <main data-page-canvas className="col-start-1 row-start-1 row-span-2 min-h-0 min-w-0 overflow-hidden bg-background min-[768px]:col-start-2">{children}</main>

    <Drawer isOpen={mobileSidebarOpen} onOpenChange={setMobileSidebarOpen}>
      <Drawer.Trigger aria-hidden="true" className="hidden">打开设置导航</Drawer.Trigger>
      <Drawer.Backdrop className="min-[768px]:hidden">
        <Drawer.Content placement="left">
          <Drawer.Dialog
            aria-label="设置导航"
            className="h-dvh w-[min(260px,calc(100vw-32px))] overflow-hidden rounded-r-2xl border-r border-separator bg-surface p-0 outline-none"
          >
            <SettingsSidebar
              role={user.role}
              returnTo={returnTo}
              onBack={goBack}
              onNavigate={() => setMobileSidebarOpen(false)}
            />
          </Drawer.Dialog>
        </Drawer.Content>
      </Drawer.Backdrop>
    </Drawer>
  </div>
}
