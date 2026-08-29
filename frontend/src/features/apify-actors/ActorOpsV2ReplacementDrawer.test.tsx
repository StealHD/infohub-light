import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type { ActorOpsV2Candidate, ActorOpsV2ReplacementPlan } from '../../api/actorOpsV2Types'
import type { AppOutletContext } from '../../app/AppContext'
import { ActorOpsV2ReplacementDrawer, type ActorOpsV2ReplacementTarget } from './ActorOpsV2ReplacementDrawer'
import type { ActorOpsV2RouteView } from './actorOpsV2RouteModel'

const candidate: ActorOpsV2Candidate = {
  candidate_id: 'candidate-new', build_number: '2.0.0', lifecycle: 'static_valid', assignment: 'inactive', priority: null, generation: 2,
  operational_status: 'normal', issue_code: null, last_success_at: null, last_failure_at: null, retry_at: null, avatar_mapping_status: 'ready',
  store_metadata: { actor_slug: 'publisher/new-actor', display_name: 'New Actor', short_description: null, developer_name: 'publisher', maintained_by_apify: false, rating: 4.5, review_count: 10, bookmark_count: 20, total_users: 5000, monthly_active_users: null, pricing: [{ minimumChargeUsd: 0.02 }], last_modified_at: null, observed_at: '2026-08-27T00:00:00Z', generation: 1 },
  evidence_progress: { verified_bindings: 0, required_bindings: 1 },
}

const assigned: ActorOpsV2Candidate = {
  ...candidate, candidate_id: 'candidate-standby', assignment: 'standby', priority: 1,
  store_metadata: { ...candidate.store_metadata!, display_name: 'Current Standby' },
}

const route: ActorOpsV2RouteView = {
  route_id: 'route-x', route_key: 'x/profile/items', platform: 'x', target_type: 'profile', capability: 'items', runtime_mode: 'active', normalized_retired_mode: false,
  generation: 4, per_run_cap_usd: 0.05, health: 'degraded', health_reason: 'insufficient_stable_paths',
  stable_candidate_count: 1, cooling_candidate_count: 0, at_risk_source_count: 1, unavailable_source_count: 0,
  fallback_source_count: 0, next_repair_at: null, active_candidate: null, standby_candidates: [assigned], last_known_good: null,
  binding_summary: { ready_count: 1, pending_count: 0, disabled_count: 0 }, degraded_reason: null, updated_at: null,
  maintenance_policy: { authorized: false, workspace: { enabled: false, monthly_budget_usd: 3, generation: 1, authorization_origin: 'none' }, route: { enabled: false, max_probe_usd: 0.05, max_probes_per_utc_day: 5, auto_add_standby: false, auto_replace_non_last: false, generation: 1, authorization_origin: 'none' }, budget: { spent_usd: 0, reserved_usd: 0, probe_count: 0 } },
}

const target: ActorOpsV2ReplacementTarget = { candidate: assigned, assignment: 'standby', priority: 1, slotLabel: '备用 1' }

function replacementPlan(overrides: Partial<ActorOpsV2ReplacementPlan> = {}): ActorOpsV2ReplacementPlan {
  return { plan_id: 'plan-1', target_assignment: 'standby', target_priority: 1, status: 'previewed', generation: 1, binding_count: 1, per_probe_cap_usd: 0.05, total_cap_usd: 0.05, error_code: null, candidate, ...overrides }
}

function renderDrawer(overrides: Partial<ServiceApi> = {}, replacementTarget = target) {
  const api = {
    actorOpsV2Candidates: vi.fn().mockResolvedValue({ candidates: [candidate] }),
    actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [], discoveries: [] }),
    actorOpsV2Replacement: vi.fn().mockResolvedValue(replacementPlan()),
    createActorOpsV2Replacement: vi.fn().mockResolvedValue(replacementPlan()),
    authorizeActorOpsV2Replacement: vi.fn().mockResolvedValue(replacementPlan({ status: 'authorized', generation: 2 })),
    applyActorOpsV2Replacement: vi.fn().mockResolvedValue({}),
    cancelActorOpsV2Replacement: vi.fn().mockResolvedValue(replacementPlan({ status: 'cancelled', generation: 2 })),
    revalidateActorOpsV2Replacement: vi.fn().mockResolvedValue({ plan: replacementPlan({ status: 'ready', generation: 2 }), revalidated_attempt_count: 1, new_actor_run_count: 0, new_actor_cost_usd: 0 }),
    discoverActorOpsV2Candidates: vi.fn().mockResolvedValue({}),
    refreshActorOpsV2Metadata: vi.fn().mockResolvedValue({}),
    ...overrides,
  } as unknown as ServiceApi
  const context = { api, user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true } } as unknown as AppOutletContext
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>
    <MemoryRouter><Routes><Route element={<Outlet context={context} />}><Route path="*" element={<ActorOpsV2ReplacementDrawer route={route} target={replacementTarget} open onOpenChange={vi.fn()} onUpdated={vi.fn().mockResolvedValue(undefined)} />} /></Route></Routes></MemoryRouter>
  </QueryClientProvider>)
  return api
}

describe('ActorOpsV2ReplacementDrawer', () => {
  it('creates a frozen replacement plan for the selected standby slot without authorizing a run', async () => {
    const api = renderDrawer()
    const browser = userEvent.setup()

    expect(await screen.findByRole('heading', { name: '替换备用 1 Actor' })).toBeInTheDocument()
    expect(await screen.findByText('系统推荐')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '免费检查并准备实测' }))

    await waitFor(() => expect(api.createActorOpsV2Replacement).toHaveBeenCalledWith('route-x', expect.objectContaining({ target_assignment: 'standby', target_priority: 1, candidate_id: 'candidate-new' })))
    expect(api.authorizeActorOpsV2Replacement).not.toHaveBeenCalled()
  })

  it('authorizes the capped probe with one explicit button and no phrase field', async () => {
    const previewed = replacementPlan({ status: 'previewed', generation: 3 })
    const api = renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [previewed], discoveries: [] }),
    } as Partial<ServiceApi>)
    const browser = userEvent.setup()

    expect(await screen.findByText(/免费预检已通过/)).toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '开始实测，最高 $0.05' }))

    await waitFor(() => expect(api.authorizeActorOpsV2Replacement).toHaveBeenCalledWith(
      'route-x', 'plan-1', { expected_generation: 3, confirmation: '确认实测替换 Actor' },
    ))
  })

  it('applies a ready plan to its frozen slot with one explicit button', async () => {
    const ready = replacementPlan({ status: 'ready', generation: 4 })
    const api = renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [ready], discoveries: [] }),
    } as Partial<ServiceApi>)
    const browser = userEvent.setup()

    await browser.click(await screen.findByRole('button', { name: '应用到备用 1' }))

    await waitFor(() => expect(api.applyActorOpsV2Replacement).toHaveBeenCalledWith(
      'route-x', 'plan-1', { expected_generation: 4, confirmation: '确认替换 Actor' },
    ))
  })

  it('offers free discovery and metadata refresh inside an empty drawer', async () => {
    const api = renderDrawer({ actorOpsV2Candidates: vi.fn().mockResolvedValue({ candidates: [] }) } as Partial<ServiceApi>)
    const browser = userEvent.setup()

    expect(await screen.findByText('暂无可替换候选')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '搜索更多候选' }))
    await waitFor(() => expect(api.discoverActorOpsV2Candidates).toHaveBeenCalledWith('route-x', { expected_route_generation: 4 }))
  })

  it('shows a schema mapping candidate with its specific disabled reason', async () => {
    renderDrawer({
      actorOpsV2Candidates: vi.fn().mockResolvedValue({
        candidates: [{
          ...candidate,
          lifecycle: 'mapping_pending',
          mapping_issue_code: 'output_not_content_items',
        }],
      }),
    } as Partial<ServiceApi>)

    expect(await screen.findByText('不可替换：Actor 输出不是帖子列表，可能只返回用户资料或关注关系')).toBeInTheDocument()
  })

  it('resumes the route open plan and lets the operator cancel it', async () => {
    const activePlan = replacementPlan({ target_assignment: 'active', target_priority: 0, status: 'authorized' })
    const api = renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [activePlan], discoveries: [] }),
      actorOpsV2Replacement: vi.fn().mockResolvedValue(activePlan),
      cancelActorOpsV2Replacement: vi.fn().mockResolvedValue({ ...activePlan, status: 'cancelled', generation: 2 }),
    } as Partial<ServiceApi>)
    const browser = userEvent.setup()

    expect(await screen.findByText('路线已有替换计划')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '替换主用 Actor' })).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '取消替换计划' }))
    await waitFor(() => expect(api.cancelActorOpsV2Replacement).toHaveBeenCalledWith('route-x', 'plan-1', { expected_generation: 1 }))
  })

  it('does not let an exhausted Dataset adaptation block a new candidate plan', async () => {
    const failedPlan = replacementPlan({
      status: 'failed', generation: 5,
      error_code: 'actorops_replacement_observed_mapping_failed',
    })
    const api = renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [failedPlan], discoveries: [] }),
    } as Partial<ServiceApi>)
    const browser = userEvent.setup()

    await browser.click(await screen.findByRole('button', { name: '免费检查并准备实测' }))
    await waitFor(() => expect(api.createActorOpsV2Replacement).toHaveBeenCalledOnce())
  })

  it('shows confirmed failures but prevents selecting them', async () => {
    const failedCandidate = {
      ...candidate,
      operational_status: 'confirmed_failure' as const,
      issue_code: 'build_unavailable' as const,
    }
    const api = renderDrawer({
      actorOpsV2Candidates: vi.fn().mockResolvedValue({ candidates: [failedCandidate] }),
    } as Partial<ServiceApi>)

    const blocked = await screen.findByRole('button', { name: '不可选择 New Actor' })
    expect(blocked).toBeDisabled()
    expect(screen.getByText('不可替换：固定 Build 不可用')).toBeInTheDocument()
    expect(screen.getByText('现有候选均已确认故障，请搜索新的候选。')).toBeInTheDocument()
    expect(api.createActorOpsV2Replacement).not.toHaveBeenCalled()
  })

  it('surfaces an asynchronous free-preflight failure with reason and zero cost', async () => {
    const activePlan = replacementPlan({ status: 'authorized', generation: 2 })
    renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [activePlan], discoveries: [] }),
      actorOpsV2Replacement: vi.fn().mockResolvedValue(replacementPlan({
        status: 'failed',
        generation: 3,
        error_code: 'actorops_replacement_target_native_id_missing',
      })),
    } as Partial<ServiceApi>)

    expect((await screen.findAllByText('替换未完成')).length).toBeGreaterThan(0)
    expect(screen.getByText('候选输入要求目标平台原生用户 ID，但当前来源只有账号 handle/URL。请改选支持 handle 的 Actor。')).toBeInTheDocument()
    expect(screen.getByText('已在创建 Attempt 和 Apify Run 前停止，费用为 $0。')).toBeInTheDocument()
  })

  it('revalidates a settled contract failure without authorizing another Actor run', async () => {
    const failedPlan = replacementPlan({
      status: 'failed', generation: 4,
      error_code: 'actorops_replacement_contract_mismatch',
    })
    const api = renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [failedPlan], discoveries: [] }),
      revalidateActorOpsV2Replacement: vi.fn().mockResolvedValue({
        plan: replacementPlan({ status: 'ready', generation: 2 }),
        revalidated_attempt_count: 1,
        new_actor_run_count: 0,
        new_actor_cost_usd: 0,
      }),
    } as Partial<ServiceApi>)
    const browser = userEvent.setup()

    expect(await screen.findByText('可以零费用重验')).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '重新验证已有结果（$0 Actor 费）' }))

    await waitFor(() => expect(api.revalidateActorOpsV2Replacement).toHaveBeenCalledWith(
      'route-x', 'plan-1', expect.objectContaining({ expected_generation: 4 }),
    ))
    expect(api.authorizeActorOpsV2Replacement).not.toHaveBeenCalled()
    expect(await screen.findByText(/全部 1 条来源已通过/)).toBeInTheDocument()
  })

  it('explains automatic Dataset remapping and guarantees no new Actor run', async () => {
    const adaptingPlan = replacementPlan({
      status: 'running', generation: 5,
      phase: 'dataset_revalidating',
      error_code: 'actorops_replacement_dataset_revalidating',
    })
    renderDrawer({
      actorOpsV2Route: vi.fn().mockResolvedValue({ replacements: [adaptingPlan], discoveries: [] }),
      actorOpsV2Replacement: vi.fn().mockResolvedValue(adaptingPlan),
    } as Partial<ServiceApi>)

    expect(await screen.findByText('正在复用已付费 Dataset 重映射')).toBeInTheDocument()
    expect(screen.getByText(/不会启动新的 Actor，也不会新增 Actor Run 费用/)).toBeInTheDocument()
  })
})
