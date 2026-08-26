import { Button } from '@heroui/react'

import * as Icons from './icons'
import { useThemePreference } from './themePreferenceContext'

export function ThemeModeToggle({ language = 'zh' }: { language?: 'zh' | 'en' }) {
  const { colorMode, toggleColorMode } = useThemePreference()
  const nextLabel = colorMode === 'dark' ? '白天' : '黑夜'
  const accessibleLabel = language === 'en'
    ? `Switch to ${colorMode === 'dark' ? 'light' : 'dark'} mode`
    : `切换到${nextLabel}模式`

  return <Button
    size="sm"
    variant="ghost"
    isIconOnly
    data-theme-mode-toggle
    className="h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
    aria-label={accessibleLabel}
    onPress={toggleColorMode}
  >
    {colorMode === 'dark'
      ? <Icons.Sun size={18} aria-hidden="true" />
      : <Icons.Moon size={18} aria-hidden="true" />}
  </Button>
}
