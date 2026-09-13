import { expect, test } from '@playwright/test'
import { emptyInformationRule } from '../src/features/information-automations/informationRuleModel'
import { installAgentApi } from './agentWorkspaceFixtures'

test('icon actions keep their geometry and order; deleting a draft requires confirmation', async ({ page }) => {
  await installAgentApi(page)
  const makeRule = (id: string, name: string, state: 'draft' | 'active' | 'paused', updatedAt: string) => ({
    id, version: 1, state, issue: null, config: { ...emptyInformationRule(), name },
    created_at: '2026-09-08', updated_at: updatedAt, confirmed_at: null,
  })
  const draft = makeRule('iar_' + 'd'.repeat(32), '草稿任务', 'draft', '2026-09-10')
  const active = makeRule('iar_' + 'a'.repeat(32), '运行中任务', 'active', '2026-09-09')
  let rules = [draft, active]
  let deleted = 0
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url())
    let data: unknown
    if (url.pathname === '/api/me/information-automations') data = { items: [...rules].sort((a, b) => b.updated_at.localeCompare(a.updated_at)), has_more: false, next_offset: null }
    else if (url.pathname.endsWith('/transition')) {
      active.state = 'paused'; active.updated_at = '2026-09-11'; data = active
    } else if (url.pathname.endsWith('/' + draft.id) && route.request().method() === 'DELETE') {
      deleted += 1; rules = rules.filter((rule) => rule.id !== draft.id); data = { id: draft.id, deleted: true }
    } else return route.fallback()
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  await page.goto('/agent/automations')
  const list = page.getByRole('list', { name: '自动化任务' })
  await expect(list.getByRole('listitem')).toHaveCount(2)
  const pause = page.getByRole('button', { name: '暂停任务：运行中任务' })
  const before = await pause.boundingBox()
  expect(before).not.toBeNull()
  await pause.hover()
  await expect(page.getByRole('tooltip')).toContainText('暂停任务')
  await pause.click()
  const start = page.getByRole('button', { name: '启动任务：运行中任务' })
  await expect(start).toBeVisible()
  const after = await start.boundingBox()
  expect(after).not.toBeNull()
  expect({ x: after!.x, y: after!.y, width: after!.width, height: after!.height }).toEqual({ x: before!.x, y: before!.y, width: before!.width, height: before!.height })
  expect(await list.getByRole('listitem').first().innerText()).toContain('草稿任务')
  await page.getByRole('button', { name: '删除任务：草稿任务' }).click()
  await expect(page.getByRole('dialog', { name: '删除任务' })).toBeVisible()
  expect(deleted).toBe(0)
  await page.getByRole('button', { name: '取消' }).click()
  await page.getByRole('button', { name: '删除任务：草稿任务' }).click()
  await page.getByRole('button', { name: '确认删除' }).click()
  await expect(list.getByRole('listitem')).toHaveCount(1)
  expect(deleted).toBe(1)
  await expect(page.getByRole('searchbox', { name: '搜索已安排任务' })).toBeFocused()
})
