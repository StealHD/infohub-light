import { Navigate, useLocation } from 'react-router-dom'

import { useAppContext } from '../../app/AppContext'
import { PageFrame } from '../../design-system'
import { StorageArchiveSettings } from '../admin-heroui/StorageArchiveSettings'
import { canAdministerSettings } from './settingsNavigation'
import { preserveSettingsReturnState } from './settingsReturnState'

export function SettingsStoragePage() {
  const { user } = useAppContext()
  const location = useLocation()
  const returnState = preserveSettingsReturnState(location.state)

  if (!canAdministerSettings(user.role)) {
    return <Navigate to="/settings" state={returnState} replace />
  }

  return <div data-settings-page="storage" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <StorageArchiveSettings queryEnabled />
    </PageFrame>
  </div>
}
