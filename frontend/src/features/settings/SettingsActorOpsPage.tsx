import { Navigate, useLocation } from 'react-router-dom'

import { useAppContext } from '../../app/AppContext'
import {
  SettingsGroup,
  SettingsItem,
  SettingsSection,
} from '../../components/settings'
import { Icons, PageFrame } from '../../design-system'
import { HeroActorOpsControlPlane } from '../apify-actors/HeroActorOpsControlPlane'
import {
  ApifyActorAlertSettingsPanel,
  ApifyActorIncidentList,
} from '../apify-actors/HeroApifyActorRouteSettings'
import { canAdministerWorkspace } from './settingsModel'
import { preserveSettingsReturnState } from './settingsReturnState'

export function SettingsActorOpsPage() {
  const { user } = useAppContext()
  const location = useLocation()
  const returnState = preserveSettingsReturnState(location.state)

  if (!canAdministerWorkspace(user)) return <Navigate to="/settings" state={returnState} replace />

  return <div data-settings-page="actorops" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="运行概览" description="查看 Route 可用度、主备池、发现和来源级验证；所有付费操作仍需单独确认。">
        <HeroActorOpsControlPlane queryEnabled />
      </SettingsSection>

      <SettingsSection title="告警与事件" description="告警只使用已配置的工作区共享通知服务；最近事件最多保留 20 条。">
        <SettingsGroup ariaLabel="ActorOps 告警与事件">
          <SettingsItem
            density="compact"
            label="故障告警"
            description="选择共享通知服务和需要关注的 ActorOps 事件。"
            icon={<Icons.BellRing size={17} aria-hidden="true" />}
          ><ApifyActorAlertSettingsPanel queryEnabled /></SettingsItem>
          <SettingsItem
            density="compact"
            label="最近事件"
            description="显示切换、熔断、费用保护与恢复记录。"
            icon={<Icons.Activity size={17} aria-hidden="true" />}
          ><ApifyActorIncidentList queryEnabled /></SettingsItem>
        </SettingsGroup>
      </SettingsSection>
    </PageFrame>
  </div>
}
