import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { poolManagementDetail, renderPoolManagement } from './actorOpsPoolManagementTestFixtures'

it('stages an add into the server-authorized empty slot', async () => {
  const selected = poolManagementDetail()
  const { api } = renderPoolManagement(selected)
  const browser = userEvent.setup()
  await browser.click(await screen.findByRole('button', { name: '添加 Actor' }))
  expect(await screen.findByRole('heading', { name: '添加 备用 2 Actor' })).toBeVisible()
  expect(screen.getByText(/商城质量：4.7 分（152 条评分） · 195K 使用人数/)).toBeVisible()
  await waitFor(() => expect(api.apifyActorPoolCandidates).toHaveBeenCalledWith(selected.route_id, 'add_slot', expect.any(AbortSignal), 'backup_2'))
  await browser.click(screen.getByRole('checkbox', { name: /新 Actor/ }))
  await browser.click(screen.getByRole('button', { name: '选择并启用' }))
  expect(api.activateVerifiedApifyActorPool).not.toHaveBeenCalled()
  expect(await screen.findByRole('heading', { name: '确认添加已验证 Actor' })).toBeVisible()
  await browser.click(screen.getByRole('button', { name: '确认并生效' }))
  await waitFor(() => expect(api.activateVerifiedApifyActorPool).toHaveBeenCalledWith(selected.route_id, expect.objectContaining({
    run_id: 'run-guided', goal: 'add_slot', target_slot: 'backup_2', target_slot_count: 3,
    confirmation: '确认启用 Actor 主备', apply_id: expect.any(String),
  })))
})

it('plans a server-controlled slot canary from the slot candidate run, not stale route workflow', async () => {
  const selected = {
    ...poolManagementDetail(),
    workflow: { ...poolManagementDetail().workflow!, run_id: 'run-stale', goal: 'complete_third' as const },
  }
  const { api } = renderPoolManagement(selected, {
    apifyActorPoolCandidates: vi.fn().mockResolvedValue({
      schema_version: 1,
      route_id: selected.route_id,
      generation: selected.generation,
      goal: 'add_slot',
      target_slot: 'backup_2',
      run_id: 'run-slot',
      required_selection_count: 1,
      blockers: ['candidate_shortfall', 'candidate_verification_pending'],
      candidates: [],
    }),
  })
  const browser = userEvent.setup()

  await browser.click(await screen.findByRole('button', { name: '添加 Actor' }))
  expect(screen.queryByText('待实测 Actor')).not.toBeInTheDocument()
  await browser.click(await screen.findByRole('button', { name: '更新已验证 Actor 库' }))

  await waitFor(() => expect(api.apifyActorCanaryPlan).toHaveBeenCalledWith(
    'run-slot', 'add_slot', expect.any(AbortSignal), 'backup_2',
  ))
})

it('sets an occupied backup as primary and changes only the future run cap', async () => {
  const selected = poolManagementDetail()
  const { api } = renderPoolManagement(selected)
  const browser = userEvent.setup()
  await browser.click(await screen.findByRole('button', { name: '设为主用' }))
  expect(await screen.findByRole('heading', { name: '设为当前主用 Actor' })).toBeVisible()
  await browser.type(screen.getByRole('textbox', { name: '确认短语' }), '确认设为主用 Actor')
  await browser.click(screen.getByRole('button', { name: '确认设为主用' }))
  await waitFor(() => expect(api.promoteApifyActorRouteActivePoolSlot).toHaveBeenCalledWith(selected.route_id, {
    target_slot: 'backup_1', expected_generation: selected.generation, confirmation: '确认设为主用 Actor',
  }))
  await waitFor(() => expect(screen.queryByRole('heading', { name: '设为当前主用 Actor' })).not.toBeInTheDocument())
  await browser.click(screen.getAllByRole('button', { name: '设为主用' })[0])
  expect(screen.getByRole('textbox', { name: '确认短语' })).toHaveValue('')
  expect(screen.getByRole('button', { name: '确认设为主用' })).toBeDisabled()
  await browser.click(screen.getByRole('button', { name: '取消' }))
  const cap = screen.getByRole('spinbutton', { name: '单次 Actor 费用上限（USD）' })
  await browser.clear(cap)
  await browser.type(cap, '0.1')
  await browser.click(screen.getByRole('button', { name: '保存上限' }))
  await waitFor(() => expect(api.setApifyActorRoutePriceCap).toHaveBeenCalledWith(selected.route_id, {
    expected_generation: selected.generation, per_run_cap_usd: 0.1,
  }))
  await browser.clear(cap)
  await browser.type(cap, '0.100001')
  expect(screen.getByRole('button', { name: '保存上限' })).toBeDisabled()
  await browser.clear(cap)
  await browser.type(cap, '100')
  expect(screen.getByRole('button', { name: '保存上限' })).toBeDisabled()
  expect(api.setApifyActorRoutePriceCap).toHaveBeenCalledTimes(1)
})

it('stages a replacement and removes an Actor only after the no-cost confirmation', async () => {
  const selected = poolManagementDetail()
  const { api } = renderPoolManagement(selected)
  const browser = userEvent.setup()
  const replace = (await screen.findAllByRole('button', { name: '替换' }))[0]
  await browser.click(replace)
  expect(await screen.findByRole('heading', { name: '替换 主用 Actor' })).toBeVisible()
  await browser.click(screen.getByRole('button', { name: '取消' }))
  await waitFor(() => expect(replace).toHaveFocus())
  await browser.click(screen.getAllByRole('button', { name: '移出主备池' })[0])
  expect(await screen.findByRole('heading', { name: '移出主备池' })).toBeVisible()
  expect(screen.getByText(/不收费，历史与认证证据会保留/)).toBeVisible()
  expect(screen.getByText(/压紧后顺序：备用 1 → 备用 2/)).toBeVisible()
  await browser.type(screen.getByRole('textbox', { name: '确认短语' }), '确认移出 Actor 主备池')
  await browser.click(screen.getByRole('button', { name: '确认移出主备池' }))
  await waitFor(() => expect(api.removeApifyActorRouteActivePoolSlot).toHaveBeenCalledWith(selected.route_id, { target_slot: 'primary', expected_generation: selected.generation, confirmation: '确认移出 Actor 主备池' }))
})
