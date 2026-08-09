import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { ServiceApi } from '../../api/service'
import type {
  ApifyActorCanaryBatch,
  ApifyActorCanaryPlan,
  ApifyActorRevisionSummary,
  ApifyActorRevisionLifecycle,
  ApifyActorRouteDetail,
  ApifyActorRouteSummary,
  ApifyActorRoutesResponse,
  ApifyActorWorkflow,
} from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import { HeroActorOpsControlPlane } from './HeroActorOpsControlPlane'

function revision(id: string, publisher: string, lifecycle: ApifyActorRevisionLifecycle = 'certified'): ApifyActorRevisionSummary {
  return {
    revision_id: `revision-${id}`,
    actor_id: `${publisher}/${id}`,
    actor_public_name: `${publisher} ${id}`,
    publisher,
    build_id: `build-${id}`,
    build_number: `2026.08.${id}`,
    manifest_hash: id.padEnd(64, id[0] || 'a').slice(0, 64),
    lifecycle,
    last_canary_at: '2026-08-09T08:00:00Z',
    last_canary_status: 'valid_nonempty',
    can_canary: false,
    can_activate: true,
  }
}

function workflow(kind: string, overrides: Partial<ApifyActorWorkflow> = {}): ApifyActorWorkflow {
  return {
    kind,
    goal: null,
    progress: {},
    blockers: [],
    ...overrides,
  }
}

function detail(overrides: Partial<ApifyActorRouteDetail> = {}): ApifyActorRouteDetail {
  const primary = revision('primary', 'publisher-a')
  const backup1 = revision('backup-1', 'publisher-b')
  return {
    route_id: 'route-x-profile',
    route_key: 'x/profile',
    platform: 'x',
    target_type: 'profile',
    capability: 'items',
    mode: 'primary',
    generation: 12,
    support_status: 'degraded',
    runtime_status: 'ready',
    runnable_slots: 2,
    required_slots: 3,
    min_runtime_healthy: 2,
    publisher_count: 2,
    per_run_cap_usd: 0.02,
    discovery_run_id: 'run-guided',
    blocked_reason: null,
    updated_at: '2026-08-09T08:00:00Z',
    workflow: workflow('backup_2_canary_approval_required', {
      goal: 'complete_third',
      run_id: 'run-guided',
    }),
    slots: [
      { slot: 'primary', revision_id: primary.revision_id, runnable: true, revision: primary },
      { slot: 'backup_1', revision_id: backup1.revision_id, runnable: true, revision: backup1 },
      { slot: 'backup_2', revision_id: null, runnable: false, revision: null },
    ],
    revisions: [primary, backup1],
    source_validations: [],
    source_validation_summary: { ready: 0, pending: 0, failed: 0 },
    ...overrides,
  }
}

function summary(route: ApifyActorRouteDetail): ApifyActorRouteSummary {
  return {
    route_id: route.route_id,
    route_key: route.route_key,
    platform: route.platform,
    target_type: route.target_type,
    capability: route.capability,
    mode: route.mode,
    generation: route.generation,
    support_status: route.support_status,
    runtime_status: route.runtime_status,
    runnable_slots: route.runnable_slots,
    required_slots: 3,
    min_runtime_healthy: 2,
    publisher_count: route.publisher_count,
    per_run_cap_usd: route.per_run_cap_usd,
    discovery_run_id: route.discovery_run_id,
    blocked_reason: route.blocked_reason,
    updated_at: route.updated_at,
    workflow: route.workflow,
  }
}

function routesResponse(selected: ApifyActorRouteDetail): ApifyActorRoutesResponse {
  const x = selected.platform === 'x' ? summary(selected) : summary(detail())
  const instagramDetail = selected.platform === 'instagram' ? selected : detail({
    route_id: 'route-instagram-profile',
    route_key: 'instagram/profile/items',
    platform: 'instagram',
    workflow: workflow('complete'),
  })
  const youtubeDetail = detail({
    route_id: 'route-youtube-channel',
    route_key: 'youtube/channel/items',
    platform: 'youtube',
    target_type: 'channel',
    mode: 'fallback',
    workflow: workflow('complete'),
  })
  return {
    schema_version: 1,
    generation: 22,
    support_profiles: [
      { id: 'youtube/channel/items', route_key: 'youtube/channel/items', platform: 'youtube', target_type: 'channel', capability: 'items', mode: 'fallback', label: 'YouTube' },
      { id: 'x/profile/items', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', label: 'X' },
      { id: 'instagram/profile/items', route_key: 'instagram/profile/items', platform: 'instagram', target_type: 'profile', capability: 'items', mode: 'primary', label: 'Instagram' },
    ],
    routes: [x, summary(youtubeDetail), summary(instagramDetail)],
  }
}

function canaryPlan(): ApifyActorCanaryPlan {
  return {
    schema_version: 2,
    goal: 'complete_third',
    run_id: 'run-guided',
    route_id: 'route-x-profile',
    route_key: 'x/profile',
    platform: 'x',
    target_type: 'profile',
    capability: 'items',
    mode: 'primary',
    generation: 12,
    status: 'ready',
    ready: true,
    activation_ready: false,
    plan_hash: 'plan-hash-guided',
    max_candidates: 1,
    max_total_charge_usd: 0.06,
    per_candidate_cap_usd: 0.02,
    successful_actor_count: 2,
    successful_publisher_count: 2,
    attempts_used: 0,
    attempts_remaining: 3,
    budget_remaining_usd: 6,
    base_pool_hash: 'base-pool-hash',
    required_success_count: 1,
    route_validation_cap_usd: 0.02,
    source_validation_cap_usd: 0.04,
    source_count: 2,
    source_validation_count: 2,
    items: [{
      ordinal: 1,
      revision_id: 'revision-backup-2',
      actor_id: 'publisher-c/backup-2',
      publisher: 'publisher-c',
      build_id: 'build-backup-2',
      build_number: '2026.08.2',
      lifecycle: 'static_valid',
      authorized_cap_usd: 0.02,
    }],
  }
}

function completedBatch(): ApifyActorCanaryBatch {
  const plan = canaryPlan()
  return {
    schema_version: 2,
    batch_id: 'batch-guided',
    route_id: plan.route_id,
    discovery_run_id: plan.run_id,
    approved_generation: plan.generation,
    plan_hash: plan.plan_hash,
    max_candidates: plan.max_candidates,
    max_total_charge_usd: plan.max_total_charge_usd,
    per_candidate_cap_usd: plan.per_candidate_cap_usd,
    goal: 'complete_third',
    pool_stage_id: 'stage-guided',
    status: 'completed',
    planned_count: 1,
    success_count: 1,
    publisher_count: 1,
    actual_cost_usd: 0.02,
    cost_final: true,
    stop_reason: 'goal_reached',
    created_at: '2026-08-09T08:00:00Z',
    completed_at: '2026-08-09T08:01:00Z',
    updated_at: '2026-08-09T08:01:00Z',
    items: plan.items.map((item) => ({ ...item, status: 'succeeded', actual_cost_usd: 0.02, cost_final: true })),
  }
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-search">{location.search}</output>
}

function renderControlPlane(selected = detail(), initialEntry = '/?route=x%2Fprofile%2Fitems&tab=pool', overrides: Partial<ServiceApi> = {}) {
  const response = routesResponse(selected)
  const api = {
    apifyActorRoutes: vi.fn().mockResolvedValue(response),
    apifyActorRoute: vi.fn().mockImplementation((routeId: string) => {
      if (routeId === selected.route_id) return Promise.resolve(selected)
      const routeSummary = response.routes.find((route) => route.route_id === routeId)
      return Promise.resolve(detail(routeSummary || {}))
    }),
    requestApifyActorSupportCheck: vi.fn().mockResolvedValue({ schema_version: 1, kind: 'discovery', generation: 23, route_generation: 1 }),
    apifyActorCanaryPlan: vi.fn().mockResolvedValue(canaryPlan()),
    createApifyActorCanaryBatch: vi.fn().mockResolvedValue({ schema_version: 2, batch: completedBatch(), job: { id: 'job-guided', status: 'queued' } }),
    apifyActorCanaryBatch: vi.fn().mockResolvedValue(completedBatch()),
    activateApifyActorRouteRecommendedPool: vi.fn().mockResolvedValue(selected),
    updateApifyActorRouteActivePool: vi.fn().mockResolvedValue(selected),
    apifyActorSourceSupport: vi.fn().mockResolvedValue({
      schema_version: 1,
      source_id: 'source-safe-abcdef',
      route_id: selected.route_id,
      generation: 3,
      binding_status: 'pending',
      verified_revision_set_hash: null,
      budget_cap_usd: 0.06,
      spent_usd: 0,
      reserved_usd: 0,
      remaining_budget_usd: 0.06,
      slots: selected.slots.map((slot) => ({ slot: slot.slot, revision_id: slot.revision_id, status: 'pending', can_canary: slot.slot === 'primary' })),
    }),
    canaryApifyActorSourceRevision: vi.fn(),
    activateApifyActorSourceBinding: vi.fn(),
    sources: vi.fn().mockResolvedValue({ sources: [{
      id: 'source-safe-abcdef',
      type: 'apify_social',
      display_name: 'Instagram · 产品账号',
      scope: 'workspace',
      enabled: true,
      config: { platform: 'instagram', kind: 'profile', target: 'private-target-must-not-render' },
    }] }),
    ...overrides,
  } as unknown as ServiceApi
  const context = {
    api,
    user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true },
    query: '',
    setQuery: vi.fn(),
    activity: { state: 'idle', message: '' },
    refresh: vi.fn(),
    beginAction: () => ({ userId: 'owner-1', generation: 0 }),
    isActionCurrent: () => true,
  } as unknown as AppOutletContext
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={queryClient}>
    <MemoryRouter initialEntries={[initialEntry]}>
      <DesignSystemProvider>
        <Routes><Route element={<Outlet context={context} />}><Route path="*" element={<><HeroActorOpsControlPlane /><LocationProbe /></>} /></Route></Routes>
      </DesignSystemProvider>
    </MemoryRouter>
  </QueryClientProvider>)
  return { api }
}

describe('HeroActorOpsControlPlane guided workflows', () => {
  beforeEach(() => actionToast.clear())

  it.each([
    ['setup_discovery_required', '尚未建立 Actor 主备', '开始建立主备'],
    ['setup_discovery_running', '正在搜索可用 Actor', null],
    ['setup_canary_approval_required', '候选已就绪，下一步验证两路主备', '查看并确认付费验证'],
    ['setup_canary_running', '正在验证两路主备', null],
    ['setup_activation_approval_required', '两路主备验证通过', '查看并确认启用'],
    ['backup_2_discovery_required', '补齐第三路备用', '开始补齐备用 2'],
    ['backup_2_discovery_running', '正在寻找第三路备用', null],
    ['backup_2_canary_approval_required', '第三路候选已就绪', '查看并确认第三路验证'],
    ['backup_2_canary_running', '正在验证第三路备用', null],
    ['backup_2_activation_approval_required', '第三路验证通过', '查看并确认补位生效'],
    ['legacy_discovery_required', '兼容模式仍在运行', '开始旁路升级'],
    ['legacy_discovery_running', '正在旁路建立新版主备', null],
    ['legacy_canary_approval_required', '新版主备候选已就绪', '查看并确认新版验证'],
    ['legacy_canary_running', '正在验证新版主备', null],
    ['legacy_activation_approval_required', '新版主备验证通过', '查看并确认切换'],
    ['probation_observing', '观察中，无需手动转正', null],
    ['source_validation_required', '有 2 个来源等待启用', '前往来源启用'],
    ['runtime_degraded_monitoring', '正在使用备用线路', null],
    ['blocked_unknown_start', '需要先核对 Apify 运行', '刷新核对结果'],
    ['budget_blocked', '费用保护已暂停', '查看运行与费用'],
    ['complete', '主备配置完成', null],
  ] as const)('renders the single authoritative %s action', async (kind, title, cta) => {
    renderControlPlane(detail({
      workflow: workflow(kind, {
        goal: kind.startsWith('backup_2')
          ? 'complete_third'
          : kind.startsWith('legacy')
            ? 'upgrade_legacy'
            : kind.startsWith('setup')
              ? 'initial_pool'
              : null,
        progress: kind === 'source_validation_required'
          ? { pending_sources: 2 }
          : {},
      }),
    }))

    const nextAction = await screen.findByTestId('actorops-next-action')
    expect(within(nextAction).getByText(title)).toBeVisible()
    if (cta) expect(within(nextAction).getByRole('button', { name: cta })).toBeVisible()
    else expect(within(nextAction).queryByRole('button')).not.toBeInTheDocument()
  })

  it('fails closed for an unknown workflow kind', async () => {
    renderControlPlane(detail({ workflow: workflow('future_server_state') }))

    const nextAction = await screen.findByTestId('actorops-next-action')
    expect(within(nextAction).getByText('状态需要刷新')).toBeVisible()
    expect(within(nextAction).getByRole('button', { name: '刷新状态' })).toBeVisible()
  })

  it('canonicalizes invalid route, tab, source, and unknown parameters', async () => {
    renderControlPlane(
      detail(),
      '/?route=invalid%2Fprofile%2Fitems&tab=unknown&source=unsafe-source&extra=discard',
    )

    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent(
      '?route=x%2Fprofile%2Fitems&tab=pool',
    ))
  })

  it('keeps a valid source deep link and clears it when switching routes', async () => {
    const browser = userEvent.setup()
    const sourceDetail = detail({
      workflow: workflow('source_validation_required', {
        progress: { pending_sources: 1 },
      }),
      source_validations: [{
        source_id: 'source-safe-abcdef',
        binding_status: 'pending',
        generation: 3,
        slots: [],
      }],
      source_validation_summary: { ready: 0, pending: 1, failed: 0 },
    })
    renderControlPlane(
      sourceDetail,
      '/?route=x%2Fprofile%2Fitems&tab=sources&source=source-safe-abcdef',
    )

    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent(
      '?route=x%2Fprofile%2Fitems&tab=sources&source=source-safe-abcdef',
    ))
    await browser.click(await screen.findByRole('button', {
      name: /X 用户动态.*抓取类型/,
    }))
    await browser.click(await screen.findByRole('option', { name: /Instagram 主页内容/ }))
    await waitFor(() => expect(screen.getByTestId('location-search')).toHaveTextContent(
      '?route=instagram%2Fprofile%2Fitems&tab=sources',
    ))
  })

  it('uses the selected Instagram tuple for free setup discovery', async () => {
    const browser = userEvent.setup()
    const instagram = detail({
      route_id: 'route-instagram-profile',
      route_key: 'instagram/profile/items',
      platform: 'instagram',
      workflow: workflow('setup_discovery_required', { goal: 'initial_pool' }),
    })
    const { api } = renderControlPlane(instagram, '/?route=instagram%2Fprofile%2Fitems&tab=pool')

    await browser.click(await screen.findByRole('button', { name: '开始建立主备' }))

    expect(api.requestApifyActorSupportCheck).toHaveBeenCalledWith({
      platform: 'instagram',
      target_type: 'profile',
      capability: 'items',
      expected_generation: 22,
      force_discovery: true,
    })
    expect(screen.queryByText('ActorOps 路由控制面')).not.toBeInTheDocument()
    expect(screen.queryByText('支持 Profile')).not.toBeInTheDocument()
  })

  it('approves third-slot validation once and keeps the two active slots visible', async () => {
    const browser = userEvent.setup()
    const { api } = renderControlPlane()

    await browser.click(await screen.findByRole('button', { name: '查看并确认第三路验证' }))
    expect(await screen.findByRole('heading', { name: '确认付费验证第三路备用' })).toBeVisible()
    expect(screen.getByText('publisher-a primary')).toBeVisible()
    expect(screen.getByText('publisher-b backup-1')).toBeVisible()
    expect(api.apifyActorCanaryPlan).toHaveBeenCalledWith('run-guided', 'complete_third', expect.any(AbortSignal))

    await browser.click(screen.getByRole('button', { name: /确认付费验证（最高/ }))
    await waitFor(() => expect(api.createApifyActorCanaryBatch).toHaveBeenCalledTimes(1))
    expect(api.createApifyActorCanaryBatch).toHaveBeenCalledWith('run-guided', expect.objectContaining({
      goal: 'complete_third',
      expected_generation: 12,
      expected_plan_hash: 'plan-hash-guided',
      confirmation: '确认付费验证主备',
      approval_id: expect.any(String),
    }))
  })

  it('requires a second explicit apply confirmation for a frozen third-slot stage', async () => {
    const browser = userEvent.setup()
    const staged = detail({
      workflow: workflow('backup_2_activation_approval_required', {
        goal: 'complete_third',
        stage_id: 'stage-guided',
        plan_hash: 'plan-hash-guided',
      }),
    })
    const { api } = renderControlPlane(staged)

    await browser.click(await screen.findByRole('button', { name: '查看并确认补位生效' }))
    expect(await screen.findByRole('heading', { name: '确认补齐备用 2' })).toBeVisible()
    expect(screen.getByText('补齐为 3/3，原主用与备用 1 不变')).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '确认生效' }))

    await waitFor(() => expect(api.activateApifyActorRouteRecommendedPool).toHaveBeenCalledTimes(1))
    expect(api.activateApifyActorRouteRecommendedPool).toHaveBeenCalledWith(staged.route_id, {
      expected_generation: 12,
      confirmation: '确认启用 Actor 主备',
      stage_id: 'stage-guided',
      expected_plan_hash: 'plan-hash-guided',
      apply_id: expect.any(String),
    })
  })

  it('explains legacy sidecar replacement without exposing a fake conversion action', async () => {
    const legacyA = revision('legacy-a', 'builtin-a', 'legacy_builtin')
    const legacyB = revision('legacy-b', 'builtin-b', 'legacy_builtin')
    const legacy = detail({
      runnable_slots: 2,
      workflow: workflow('legacy_discovery_required', { goal: 'upgrade_legacy' }),
      revisions: [legacyA, legacyB],
      slots: [
        { slot: 'primary', revision_id: legacyA.revision_id, runnable: true, revision: legacyA },
        { slot: 'backup_1', revision_id: legacyB.revision_id, runnable: true, revision: legacyB },
        { slot: 'backup_2', revision_id: null, runnable: false, revision: null },
      ],
    })
    renderControlPlane(legacy)

    expect(await screen.findByText('兼容模式仍在运行')).toBeVisible()
    expect(screen.getByText(/旁路建立新版主备/)).toBeVisible()
    expect(screen.getByRole('button', { name: '开始旁路升级' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /转正/ })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('legacy_builtin')
  })

  it('shows server-projected certification progress and no manual promotion button', async () => {
    const observing = revision('observing', 'publisher-a', 'probationary')
    observing.certification_progress = {
      auto_promotes: true,
      lifecycle: 'probationary',
      success_identities: { current: 1, required: 2 },
      reference_targets: { current: 1, required: 2 },
      valid_samples: { current: 19, successful: 18, required: 20 },
      success_rate: { current: 18 / 19, required: 0.95 },
      observation_started_at: '2026-08-08T08:00:00Z',
      eligible_at: '2026-08-10T08:00:00Z',
      remaining_seconds: 86_400,
      blockers: ['observation_window'],
    }
    const probation = detail({
      workflow: workflow('probation_observing'),
      revisions: [observing],
      slots: [
        { slot: 'primary', revision_id: observing.revision_id, runnable: true, revision: observing },
        { slot: 'backup_1', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_2', revision_id: null, runnable: false, revision: null },
      ],
    })
    renderControlPlane(probation)

    expect(await screen.findByText('观察中，无需手动转正')).toBeVisible()
    expect(screen.getByText(/身份 1\/2 · 参考来源 1\/2/)).toBeVisible()
    expect(screen.getByText(/有效样本 19 · 成功率/)).toBeVisible()
    expect(screen.queryByRole('button', { name: /转正/ })).not.toBeInTheDocument()
  })

  it('lists authorized sources by name, hides targets, and removes the raw ID lookup form', async () => {
    const browser = userEvent.setup()
    const sourceDetail = detail({
      workflow: workflow('source_validation_required', {
        progress: { pending_sources: 1 },
      }),
      source_validations: [{
        source_id: 'source-safe-abcdef',
        binding_status: 'pending',
        generation: 3,
        slots: [],
      }],
      source_validation_summary: { ready: 0, pending: 1, failed: 0 },
    })
    const { api } = renderControlPlane(sourceDetail)

    expect(await screen.findByText('有 1 个来源等待启用')).toBeVisible()
    await browser.click(screen.getByRole('tab', { name: /来源启用/ }))
    expect(await screen.findByText('Instagram · 产品账号')).toBeVisible()
    expect(screen.queryByRole('textbox', { name: /来源 ID/ })).not.toBeInTheDocument()
    expect(document.body.textContent).not.toContain('private-target-must-not-render')
    await browser.click(screen.getByRole('button', { name: '继续验证' }))
    await waitFor(() => expect(api.apifyActorSourceSupport).toHaveBeenCalledWith('source-safe-abcdef', expect.any(AbortSignal)))
    await waitFor(() => expect(screen.getByTestId('actorops-source-detail-heading')).toHaveFocus())
    expect(document.body.textContent).not.toContain('private-target-must-not-render')
  })
})
