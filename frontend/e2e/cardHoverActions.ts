import { expect, type Locator, type Page } from '@playwright/test'

export async function expectCardHoverActions(page: Page, card: Locator) {
  const actions = card.locator('[data-card-hover-actions]')
  await expect(actions).toHaveCSS('opacity', '0')
  for (const [name, text] of [[/复制摘要 /, '复制摘要'], [/忽略 /, '忽略这条内容']] as const) {
    await card.hover()
    await expect(actions).toHaveCSS('opacity', '1')
    const trigger = card.getByRole('button', { name })
    await trigger.hover()
    const tooltip = page.getByRole('tooltip').filter({ hasText: text })
    await expect(tooltip).toBeVisible()
    const [triggerBounds, tooltipBounds] = await Promise.all([trigger.boundingBox(), tooltip.boundingBox()])
    expect(triggerBounds).not.toBeNull()
    expect(tooltipBounds).not.toBeNull()
    expect(tooltipBounds!.y - (triggerBounds!.y + triggerBounds!.height)).toBeGreaterThanOrEqual(2)
    await page.mouse.move(1, 1)
    await expect(tooltip).toBeHidden()
  }
  await expect(card.getByRole('button', { name: /更多操作/ })).toHaveCount(0)
}
