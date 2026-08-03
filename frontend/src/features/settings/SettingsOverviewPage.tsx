import { Navigate, useLocation, useNavigate } from 'react-router-dom'

import { useAppContext } from '../../app/AppContext'
import {
  SettingsCard,
  SettingsGroup,
  SettingsItem,
  SettingsSection,
  StatusBadge,
} from '../../components/settings'
import { Button, Icons, PageFrame, useThemePreference } from '../../design-system'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import { canAdministerSettings, settingsDestinationFromLegacyHash } from './settingsNavigation'
import { preserveSettingsReturnState } from './settingsReturnState'

const roleLabels = {
  owner: 'Owner',
  admin: 'Admin',
  member: 'Member',
  viewer: 'Viewer',
} as const

export function SettingsOverviewPage() {
  const { user } = useAppContext()
  const location = useLocation()
  const navigate = useNavigate()
  const { colorMode } = useThemePreference()
  const returnState = preserveSettingsReturnState(location.state)

  if (location.hash) {
    return <Navigate
      replace
      to={settingsDestinationFromLegacyHash(location.hash, user.role)}
      state={returnState}
    />
  }

  const admin = canAdministerSettings(user.role)
  return <div data-settings-page="overview" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="账户" description="当前登录身份与工作区权限。">
        <SettingsGroup ariaLabel="账户信息">
          <SettingsItem
            label={user.display_name || user.username}
            description={`@${user.username}${user.workspace_id ? ` · 工作区 ${user.workspace_id}` : ''}`}
            icon={<Icons.UserRound size={17} aria-hidden="true" />}
            trailing={<StatusBadge tone={admin ? 'accent' : 'neutral'}>{roleLabels[user.role]}</StatusBadge>}
          />
        </SettingsGroup>
      </SettingsSection>

      <SettingsSection title="设置" description="按职责进入对应区域；首批页面已经迁移到独立设置工作区。">
        <div className="grid gap-3 min-[640px]:grid-cols-2">
          <SettingsCard
            title="来源"
            description="管理来源目录、订阅和个人来源参数。"
            icon={<Icons.Rss size={18} aria-hidden="true" />}
            status={<StatusBadge>工作区</StatusBadge>}
            to="/subscriptions"
          />
          <SettingsCard
            title="AI"
            description={admin ? '配置分析模型、助手和内容生成。' : '查看 AI 能力与工作区配置状态。'}
            icon={<Icons.Sparkles size={18} aria-hidden="true" />}
            status={!admin ? <StatusBadge>只读</StatusBadge> : <StatusBadge tone="accent">已迁移</StatusBadge>}
            to="/settings/ai"
            state={returnState}
          />
          <SettingsCard
            title="已忽略内容"
            description="查看并恢复暂时从信息流隐藏的内容。"
            icon={<Icons.EyeOff size={18} aria-hidden="true" />}
            to="/settings/ignored"
            state={returnState}
          />
          <SettingsCard
            title="通知"
            description="管理通知服务和个人新内容通知。"
            icon={<Icons.Bell size={18} aria-hidden="true" />}
            status={<StatusBadge tone="accent">已迁移</StatusBadge>}
            to="/settings/notifications"
            state={returnState}
          />
          <SettingsCard
            title="外观"
            description="选择适合当前环境的明暗显示模式。"
            icon={<Icons.SunMoon size={18} aria-hidden="true" />}
            status={<StatusBadge>{colorMode === 'dark' ? '深色' : '浅色'}</StatusBadge>}
            to="/settings/appearance"
            state={returnState}
          />
          {admin && <SettingsCard
            title="密钥"
            description="管理工作区服务密钥和 Apify 主备 Key 池。"
            icon={<Icons.KeyRound size={18} aria-hidden="true" />}
            status={<StatusBadge tone="warning">管理员</StatusBadge>}
            to="/settings/secrets"
            state={returnState}
          />}
          {admin && <SettingsCard
            title="高级"
            description="管理获取策略、存储归档和工作区运行参数。"
            icon={<Icons.SlidersHorizontal size={18} aria-hidden="true" />}
            status={<StatusBadge tone="warning">管理员</StatusBadge>}
            to="/settings/legacy#settings-fetching"
            state={returnState}
          />}
        </div>
      </SettingsSection>

      <SettingsSection title="帮助与版本" description="查阅操作方法、产品变化和正式发布记录。">
        <SettingsGroup ariaLabel="帮助与版本">
          <SettingsItem
            label="操作手册"
            description="了解 Feed、来源和设置的使用方式。"
            icon={<Icons.BookOpen size={17} aria-hidden="true" />}
            trailing={<Button size="sm" variant="ghost" aria-label="查看操作手册" onPress={() => navigate('/manual')}>查看</Button>}
          />
          <SettingsItem
            label="更新日志"
            description="查看产品界面与能力变化。"
            icon={<Icons.ScrollText size={17} aria-hidden="true" />}
            trailing={<Button size="sm" variant="ghost" aria-label="查看更新日志" onPress={() => navigate('/changelog')}>查看</Button>}
          />
          <SettingsItem
            label="Release 发布页"
            description="查看正式版本与发布资产。"
            icon={<Icons.Rocket size={17} aria-hidden="true" />}
            trailing={<a
              href={PRODUCT_RELEASES_URL}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="打开 Release 发布页"
              className="type-control inline-flex min-h-8 items-center gap-2 rounded-xl px-3 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
            >打开<Icons.ExternalLink size={13} aria-hidden="true" /></a>}
          />
        </SettingsGroup>
      </SettingsSection>
    </PageFrame>
  </div>
}
