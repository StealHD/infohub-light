import { expect, test } from '@playwright/test'

test('refresh bootstrap mirrors the expanded sidebar anatomy', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The expanded sidebar is a wide-desktop refresh state.')
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.addInitScript(() => {
    window.localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({ themeName: 'graphite-purple', colorMode: 'light' }))
    window.localStorage.setItem('inteliscope.ui.bootstrap-shell.v1', JSON.stringify({ userId: 'skeleton-user', sidebar: 'expanded', rightRail: 'closed', rightRailWidth: 400 }))
  })

  let releaseAuth = () => undefined
  const authGate = new Promise<void>((resolve) => { releaseAuth = resolve })
  await page.route('**/api/auth/status', async (route) => {
    await authGate
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: { authenticated: false } }) })
  })
  await page.goto('/feed', { waitUntil: 'domcontentloaded' })

  const navigation = page.locator('[data-bootstrap-region="navigation"]')
  await expect(navigation).toBeVisible()
  await expect(navigation.locator('.bootstrap-shell-navigation-brand')).toBeVisible()
  await expect(navigation.locator('.bootstrap-shell-navigation-group')).toHaveCount(2)
  await expect(navigation.locator('.bootstrap-shell-nav-item')).toHaveCount(7)
  await expect(navigation.locator('.bootstrap-shell-navigation-account')).toBeVisible()
  await expect(navigation).toHaveScreenshot('refresh-expanded-sidebar.png', { animations: 'disabled', caret: 'hide' })

  releaseAuth()
})
