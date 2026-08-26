import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const routeScrollRoots = [
  'src/features/admin-heroui/HeroSubscriptionsPage.tsx',
  'src/features/admin-heroui/HeroAgentsPage.tsx',
  'src/features/admin-heroui/HeroUsersPage.tsx',
  'src/features/manual/HeroManualPage.tsx',
  'src/features/changelog/HeroChangelogPage.tsx',
  'src/features/settings/SettingsOverviewPage.tsx',
  'src/features/settings/SettingsAIPage.tsx',
  'src/features/settings/SettingsActorOpsPage.tsx',
  'src/features/settings/SettingsFetchingPage.tsx',
  'src/features/settings/SettingsAppearancePage.tsx',
  'src/features/settings/SettingsIgnoredPage.tsx',
  'src/features/settings/SettingsNotificationsPage.tsx',
  'src/features/settings/SettingsSecretsPage.tsx',
  'src/features/settings/SettingsStoragePage.tsx',
  'src/features/settings/SettingsSystemPage.tsx',
]

const source = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

describe('PageHeader scroll-through contract', () => {
  it('puts the header clearance inside every authenticated route scroll root', () => {
    for (const path of routeScrollRoots) expect(source(path), path).toContain('data-page-scroll-region')
  })

  it('keeps shell canvases unpadded and Feed content scrollable behind the header', () => {
    expect(source('src/features/workbench-live/HeroWorkbenchShell.tsx')).not.toContain('bg-background pt-[var(--inteliscope-size-page-header)]')
    expect(source('src/features/settings/SettingsLayout.tsx')).not.toContain('bg-background pt-[var(--inteliscope-size-page-header)]')
    expect(source('src/features/workbench-live/HeroWorkbenchPage.tsx')).toContain('PAGE_HEADER_SIZE_PX + feedToolbarInset')
    expect(source('src/features/workbench-live/HeroWorkbenchPage.tsx')).toContain('top-[var(--inteliscope-size-page-header)]')
  })

  it('does not double the header inset for sticky page toolbars', () => {
    const subscriptions = source('src/features/admin-heroui/HeroSubscriptionsPage.tsx')
    expect(subscriptions).toContain('px-4 pb-4 pt-2')
    expect(subscriptions).toContain('data-subscription-tabs-toolbar className="sticky top-0')
    expect(source('src/features/settings/SettingsActorOpsPage.tsx')).toContain('data-actorops-tabs-toolbar className="sticky top-0')
  })
})
