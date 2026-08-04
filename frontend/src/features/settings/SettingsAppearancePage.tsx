import {
  SettingsGroup,
  SettingsItem,
  SettingsSection,
  StatusBadge,
} from '../../components/settings'
import { Icons, PageFrame, Radio, RadioGroup, useThemePreference } from '../../design-system'
import type { ThemeColorMode } from '../../design-system'

function ThemePreview({ mode }: { mode: ThemeColorMode }) {
  return <span
    aria-hidden="true"
    data-settings-theme-preview={mode}
    className="settings-theme-preview grid h-24 w-full grid-cols-[28%_1fr] overflow-hidden rounded-xl border"
  >
    <span className="settings-theme-preview-sidebar border-r p-2">
      <span className="settings-theme-preview-bar block h-2 w-full rounded-full" />
      <span className="settings-theme-preview-bar mt-2 block h-2 w-3/4 rounded-full opacity-70" />
    </span>
    <span className="grid content-start gap-2 p-3">
      <span className="settings-theme-preview-bar block h-2 w-1/2 rounded-full" />
      <span className="settings-theme-preview-card block h-7 rounded-lg border" />
      <span className="settings-theme-preview-card block h-7 rounded-lg border" />
    </span>
  </span>
}

export function SettingsAppearancePage() {
  const { colorMode, setColorMode } = useThemePreference()

  return <div data-settings-page="appearance" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="显示模式" description="偏好保存在当前浏览器中，并与页面右上角的模式切换保持同步。">
        <SettingsGroup ariaLabel="显示模式">
          <SettingsItem
            label="主题"
            description="当前提供浅色与深色两种模式。"
            icon={<Icons.Palette size={17} aria-hidden="true" />}
            trailing={<StatusBadge tone="accent">{colorMode === 'dark' ? '深色' : '浅色'}</StatusBadge>}
          >
            <RadioGroup
              aria-label="显示模式"
              value={colorMode}
              onChange={(value) => setColorMode(value as ThemeColorMode)}
              className="grid gap-3 min-[560px]:grid-cols-2"
            >
              <Radio value="light" className="rounded-xl border border-separator bg-surface p-3 data-[selected=true]:border-accent">
                <Radio.Content className="grid w-full gap-3">
                  <ThemePreview mode="light" />
                  <span className="flex items-center gap-2">
                    <Radio.Control><Radio.Indicator /></Radio.Control>
                    <span className="type-control">浅色</span>
                  </span>
                </Radio.Content>
              </Radio>
              <Radio value="dark" className="rounded-xl border border-separator bg-surface p-3 data-[selected=true]:border-accent">
                <Radio.Content className="grid w-full gap-3">
                  <ThemePreview mode="dark" />
                  <span className="flex items-center gap-2">
                    <Radio.Control><Radio.Indicator /></Radio.Control>
                    <span className="type-control">深色</span>
                  </span>
                </Radio.Content>
              </Radio>
            </RadioGroup>
          </SettingsItem>
        </SettingsGroup>
      </SettingsSection>
    </PageFrame>
  </div>
}
