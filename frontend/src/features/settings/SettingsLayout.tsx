import { useMemo, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import type { User } from '../../api/types'
import { SettingsSidebar } from '../../components/settings'
import { Button, Drawer, Icons, ThemeModeToggle } from '../../design-system'
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

    <header className="flex h-[var(--inteliscope-size-page-header)] min-w-0 items-center gap-1 border-b border-separator bg-surface px-2.5 min-[768px]:gap-2 min-[768px]:px-4">
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
      <h1 className="type-page-title min-w-0 flex-1 truncate">{title}</h1>
      <ThemeModeToggle />
    </header>

    <main className="min-h-0 min-w-0 overflow-hidden">{children}</main>

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
