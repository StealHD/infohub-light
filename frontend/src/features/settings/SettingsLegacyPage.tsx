import { Suspense, lazy } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAppContext } from '../../app/AppContext'
import { LoadingState } from '../../design-system'
import { canAdministerSettings, settingsDestinationFromLegacyHash } from './settingsNavigation'
import { preserveSettingsReturnState } from './settingsReturnState'

const HeroSettingsPage = lazy(() => import('../admin-heroui/HeroSettingsPage').then((module) => ({ default: module.HeroSettingsPage })))

export function SettingsLegacyPage() {
  const { user } = useAppContext()
  const location = useLocation()
  const returnState = preserveSettingsReturnState(location.state)
  const destination = settingsDestinationFromLegacyHash(location.hash, user.role)
  const current = `/settings/legacy${location.hash}`

  if (location.hash && destination !== current) {
    return <Navigate to={destination} state={returnState} replace />
  }
  if (!canAdministerSettings(user.role)) return <Navigate to="/settings" state={returnState} replace />
  return <Suspense fallback={<main className="quiet-scroll-region h-full overflow-y-auto p-4 min-[768px]:p-6" role="status"><LoadingState label="正在加载高级设置" rows={3} /></main>}>
    <HeroSettingsPage />
  </Suspense>
}
