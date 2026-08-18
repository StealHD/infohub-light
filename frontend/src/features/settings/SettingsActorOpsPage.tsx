import { Navigate, useLocation } from 'react-router-dom'

import { useAppContext } from '../../app/AppContext'
import { Card, PageFrame, PageIntro } from '../../design-system'
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
    <PageFrame width="settings" className="grid gap-5 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <PageIntro description="为 X、Instagram 和 YouTube 管理 Actor 主备。服务器受控实测候选；你只会从已验证目录选择，启用不再重复收费。" />
      <HeroActorOpsControlPlane
        queryEnabled
        operationsContent={<>
          <Card variant="secondary" className="grid gap-4 border border-separator p-4">
            <div><Card.Title>运行告警</Card.Title><Card.Description className="mt-1">告警设置适用于整个工作区；任一通知服务失败不会阻断抓取。</Card.Description></div>
            <ApifyActorAlertSettingsPanel queryEnabled />
          </Card>
          <Card variant="secondary" className="grid gap-4 border border-separator p-4">
            <div><Card.Title>最近事件</Card.Title><Card.Description className="mt-1">默认查看最新切换、熔断、费用保护与恢复记录。</Card.Description></div>
            <ApifyActorIncidentList queryEnabled />
          </Card>
        </>}
      />
    </PageFrame>
  </div>
}
