import { Button } from '@heroui/react'

import * as Icons from './icons'
import { useThemePreference } from './DesignSystemProvider'

export function ThemeModeToggle() {
  const { colorMode, toggleColorMode } = useThemePreference()
  const nextLabel = colorMode === 'dark' ? '白天' : '黑夜'

  return <Button
    size="sm"
    variant="ghost"
    isIconOnly
    data-theme-mode-toggle
    className="h-8 w-[34px] rounded-[var(--inteliscope-radius-control)] text-muted transition-[color,background-color,transform] duration-[var(--inteliscope-motion-standard)] hover:bg-default hover:text-foreground active:scale-95 motion-reduce:transform-none"
    aria-label={`切换到${nextLabel}模式`}
    onPress={toggleColorMode}
  >
    {colorMode === 'dark'
      ? <Icons.Sun size={18} aria-hidden="true" />
      : <Icons.Moon size={18} aria-hidden="true" />}
  </Button>
}
