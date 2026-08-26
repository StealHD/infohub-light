import { SettingsGroup, SettingsSection } from '../../components/settings'
import { PageFrame } from '../../design-system'
import { HeroNotificationSettings } from '../notifications/HeroNotificationSettings'
import { HeroNotificationTargets } from '../notifications/HeroNotificationTargets'

export function SettingsNotificationsPage() {
  return <div data-settings-page="notifications" data-page-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="通知渠道" description="管理员统一配置接收服务；成员只会看到自己可使用的目标。">
        <SettingsGroup className="p-4 min-[640px]:p-5" ariaLabel="通知服务设置">
          <HeroNotificationTargets />
        </SettingsGroup>
      </SettingsSection>

      <SettingsSection title="个人新内容通知" description="选择已经配置并验证的服务，不会重复保存地址或凭据。">
        <SettingsGroup className="p-4 min-[640px]:p-5" ariaLabel="个人通知设置">
          <HeroNotificationSettings />
        </SettingsGroup>
      </SettingsSection>
    </PageFrame>
  </div>
}
