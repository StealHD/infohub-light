import { useAppContext } from '../../app/AppContext'
import { PageFrame } from '../../design-system'
import { AdminPageHeader, AdminSection } from './HeroAdminControls'
import { StorageArchiveSettings } from './StorageArchiveSettings'

export function HeroSettingsPage() {
  const { user } = useAppContext()

  return <div data-settings-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-5 p-4 min-[768px]:p-6">
      <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
      <AdminSection
        id="settings-storage"
        title="存储与归档"
        description="预演工作区清理、90 日冷归档与恢复；所有操作均先核对候选指纹并记录审计。"
      ><StorageArchiveSettings queryEnabled /></AdminSection>
    </PageFrame>
  </div>
}
