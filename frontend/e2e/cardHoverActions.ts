import { expect, type Locator, type Page } from '@playwright/test'

export async function expectCardHoverActions(page: Page, card: Locator) {
  const actions = card.locator('[data-card-hover-actions]')
  const footerActions = card.locator('[data-card-footer-actions]')
  const readGroupChrome = (element: Element) => {
    const style = getComputedStyle(element)
    return {
      backdropFilter: style.backdropFilter,
      backgroundColor: style.backgroundColor,
      borderTopWidth: style.borderTopWidth,
      boxShadow: style.boxShadow,
    }
  }
  const [hoverChrome, footerChrome] = await Promise.all([
    actions.evaluate(readGroupChrome),
    footerActions.evaluate(readGroupChrome),
  ])
  expect(hoverChrome).toEqual(footerChrome)
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
  const copy = card.getByRole('button', { name: /复制摘要 / })
  await card.hover()
  await expect(actions).toHaveCSS('opacity', '1')
  await copy.click()
  await expect(copy).toHaveAttribute('data-copy-state', 'success')
  await expect(copy.locator('.lucide-check')).toBeVisible()
  const feedback = page.getByRole('tooltip').filter({ hasText: '已复制' })
  await expect(feedback).toBeVisible()
  const [copyBounds, feedbackBounds] = await Promise.all([copy.boundingBox(), feedback.boundingBox()])
  expect(copyBounds).not.toBeNull()
  expect(feedbackBounds).not.toBeNull()
  expect(copyBounds!.y - (feedbackBounds!.y + feedbackBounds!.height)).toBeGreaterThanOrEqual(2)
  await expect(card.getByRole('button', { name: /更多操作/ })).toHaveCount(0)
}
