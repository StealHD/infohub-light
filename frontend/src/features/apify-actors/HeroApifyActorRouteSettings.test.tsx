import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type {
  ApifyActorAlertSettings,
  ApifyActorDiscoveryRun,
  ApifyActorRoute,
  ApifyActorRouteDetail,
  ApifyActorRoutesResponse,
  ApifyActorSourceValidation,
  ApifyActorSourceSupport,
} from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import {
  ApifyActorAlertSettingsForm,
  HeroApifyActorRouteSettings,
} from './HeroApifyActorRouteSettings'
import { APIFY_ACTOR_ROUTE_REFRESH_MS } from './apifyActorModel'

const route = (overrides: Partial<ApifyActorRoute> = {}): ApifyActorRoute => ({
  schema_version: 1,
  route: 'x/profile',
  generation: 7,
  status: 'ready',
  active_candidate_id: 'scrape-badger',
  last_switch_reason: 'placeholder_records',
  last_switch_at: '2026-07-29T08:00:00Z',
  retry_at: null,
  blocked_reason: null,
  quota: {
    currency: 'USD',
    total_remaining_usd: 5.06,
    x_allocatable_usd: 4.05,
    spend_24h_usd: 0.01,
    estimated_days_remaining: 7,
    as_of: '2026-07-29T08:00:00Z',
  },
  limits: {
    per_run_usd: 0.02,
    per_job_usd: 0.06,
    failed_spend_6h_usd: 0.08,
  },
  candidates: [
    {
      id: 'scrape-badger',
      position: 0,
      display_name: 'ScrapeBadger',
      actor_public_name: 'scrape.badger/twitter-tweets-scraper',
      state: 'closed',
      listed_price_usd_per_1000: 0.15,
      last_charge_usd: 0.00015,
      avg_charge_24h_usd: 0.0002,
      success_rate_24h: 0.99,
      last_success_at: '2026-07-29T08:00:00Z',
      last_failure_at: null,
      retry_at: null,
      last_error_code: null,
      can_enable: false,
      can_disable: true,
      can_canary: true,
    },
    {
      id: 'dami',
      position: 1,
      display_name: 'Dami',
      actor_public_name: 'dami_studio/tweet-scraper',
      state: 'probationary',
      listed_price_usd_per_1000: 0.3,
      last_charge_usd: null,
      avg_charge_24h_usd: null,
      success_rate_24h: null,
      last_success_at: null,
      last_failure_at: null,
      retry_at: null,
      last_error_code: null,
      can_enable: false,
      can_disable: true,
      can_canary: true,
    },
    {
      id: 'xquik',
      position: 2,
      display_name: 'Xquik',
      actor_public_name: 'xquik/x-tweet-scraper',
      state: 'open',
      listed_price_usd_per_1000: 15,
      paid_plan_listed_price_usd_per_1000: 0.15,
      last_charge_usd: 0.015,
      avg_charge_24h_usd: 0.015,
      success_rate_24h: 0,
      last_success_at: null,
      last_failure_at: '2026-07-29T07:00:00Z',
      retry_at: '2026-07-29T09:00:00Z',
      last_error_code: 'placeholder_records',
      can_enable: false,
      can_disable: true,
      can_canary: true,
    },
  ],
  ...overrides,
})

const actorOpsDetail = (
  overrides: Partial<ApifyActorRouteDetail> = {},
): ApifyActorRouteDetail => {
  const revisions = [
    {
      revision_id: 'revision-primary',
      actor_id: 'publisher-a/primary',
      actor_public_name: 'Publisher A Primary',
      publisher: 'publisher-a',
      build_id: 'build-primary',
      build_number: '1.0.1',
      manifest_hash: 'a'.repeat(64),
      lifecycle: 'certified' as const,
      last_charge_usd: 0.01,
      avg_charge_24h_usd: 0.009,
      last_canary_at: '2026-07-29T08:00:00Z',
      last_canary_status: 'valid_nonempty',
      can_canary: false,
      can_activate: true,
    },
    {
      revision_id: 'revision-backup-1',
      actor_id: 'publisher-b/backup',
      actor_public_name: 'Publisher B Backup',
      publisher: 'publisher-b',
      build_id: 'build-backup-1',
      build_number: '1.0.2',
      manifest_hash: 'b'.repeat(64),
      lifecycle: 'certified' as const,
      last_charge_usd: 0.01,
      avg_charge_24h_usd: 0.01,
      last_canary_at: '2026-07-29T08:00:00Z',
      last_canary_status: 'valid_nonempty',
      can_canary: false,
      can_activate: true,
    },
    {
      revision_id: 'revision-backup-2',
      actor_id: 'publisher-a/probationary',
      actor_public_name: 'Publisher A Probationary',
      publisher: 'publisher-a',
      build_id: 'build-backup-2',
      build_number: '1.0.3',
      manifest_hash: 'c'.repeat(64),
      lifecycle: 'probationary' as const,
      pricing: {
        model: 'PAY_PER_EVENT',
        billing_unit: 'event' as const,
        unit_price_min_usd: 0.001,
        unit_price_max_usd: 0.015,
        minimum_charge_usd: null,
        minimum_run_cap_usd: 0.02,
      },
      last_charge_usd: 0.01,
      avg_charge_24h_usd: 0.01,
      last_canary_at: '2026-07-29T08:00:00Z',
      last_canary_status: 'valid_empty',
      can_canary: true,
      can_activate: true,
    },
  ]
  return {
    route_id: 'route-x-profile',
    route_key: 'x/profile',
    platform: 'x',
    target_type: 'profile',
    capability: 'items',
    mode: 'primary',
    generation: 7,
    support_status: 'supported',
    runtime_status: 'ready',
    runnable_slots: 3,
    required_slots: 3,
    min_runtime_healthy: 2,
    publisher_count: 2,
    per_run_cap_usd: 0.02,
    discovery_run_id: null,
    blocked_reason: null,
    updated_at: '2026-07-29T08:00:00Z',
    slots: [
      {
        slot: 'primary',
        revision_id: revisions[0].revision_id,
        runnable: true,
        revision: revisions[0],
      },
      {
        slot: 'backup_1',
        revision_id: revisions[1].revision_id,
        runnable: true,
        revision: revisions[1],
      },
      {
        slot: 'backup_2',
        revision_id: revisions[2].revision_id,
        runnable: true,
        revision: revisions[2],
      },
    ],
    revisions,
    source_validations: [],
    source_validation_summary: { ready: 0, pending: 0, failed: 0 },
    replacement_needed: false,
    ...overrides,
  }
}

const actorOpsRoutes = (
  detail: ApifyActorRouteDetail = actorOpsDetail(),
): ApifyActorRoutesResponse => ({
  schema_version: 1,
  generation: detail.generation,
  support_profiles: [
    { id: 'x/profile/items', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', label: 'X Profile' },
    { id: 'youtube/channel/items', route_key: 'youtube/channel/items', platform: 'youtube', target_type: 'channel', capability: 'items', mode: 'fallback', label: 'YouTube Channel' },
    { id: 'instagram/profile/items', route_key: 'instagram/profile/items', platform: 'instagram', target_type: 'profile', capability: 'items', mode: 'primary', label: 'Instagram Profile' },
  ],
  routes: [{
    route_id: detail.route_id,
    route_key: detail.route_key,
    platform: detail.platform,
    target_type: detail.target_type,
    capability: detail.capability,
    mode: detail.mode,
    generation: detail.generation,
    support_status: detail.support_status,
    runtime_status: detail.runtime_status,
    runnable_slots: detail.runnable_slots,
    required_slots: 3,
    min_runtime_healthy: 2,
    publisher_count: detail.publisher_count,
    per_run_cap_usd: detail.per_run_cap_usd,
    discovery_run_id: detail.discovery_run_id,
    blocked_reason: detail.blocked_reason,
    updated_at: detail.updated_at,
  }],
})

const discoveryRun = (
  detail: ApifyActorRouteDetail,
): ApifyActorDiscoveryRun => ({
  schema_version: 3,
  run_id: 'discovery-run-1',
  route_id: detail.route_id,
  generation: detail.generation,
  stage: 'awaiting_canary_approval',
  status: 'awaiting_canary_approval',
  queries_completed: 3,
  queries_limit: 3,
  budget_cap_usd: 0.1,
  spent_usd: 0,
  candidate_shortfall: 0,
  candidates: [{
    revision: {
      ...detail.revisions[2],
      revision_id: 'revision-discovered',
      actor_id: 'publisher-c/discovered',
      actor_public_name: 'Publisher C Discovered',
      publisher: 'publisher-c',
      build_id: 'build-discovered',
      build_number: '2.0.0',
      lifecycle: 'static_valid',
      can_canary: true,
      can_activate: false,
    },
    rank: 1,
    status: 'static_valid',
    awaiting_approval: true,
  }],
  updated_at: '2026-07-29T08:00:00Z',
})

const sourceSupport = (
  detail: ApifyActorRouteDetail,
  overrides: Partial<ApifyActorSourceSupport> = {},
): ApifyActorSourceSupport => ({
  schema_version: 1,
  source_id: 'source-opaque-1',
  route_id: detail.route_id,
  generation: 3,
  binding_status: 'pending_validation',
  verified_revision_set_hash: null,
  budget_cap_usd: 0.06,
  spent_usd: 0.045,
  remaining_budget_usd: 0.015,
  slots: detail.slots.map((slot, index) => ({
    slot: slot.slot,
    revision_id: slot.revision_id,
    status: 'pending',
    last_canary_at: null,
    last_canary_status: null,
    can_canary: index === 0,
  })),
  activation_confirmation: '确认首次启用',
  ...overrides,
})

const alertSettings = (
  overrides: Partial<ApifyActorAlertSettings> = {},
): ApifyActorAlertSettings => ({
  schema_version: 2,
  enabled: true,
  channel: 'webhook',
  events: [
    'actor_switched',
    'route_exhausted',
    'quota_low',
    'budget_blocked',
    'start_outcome_unknown',
    'recovered',
  ],
  email_configured: false,
  email_transport_ready: true,
  webhook_configured: true,
  webhook_provider: 'generic_event',
  webhook_provider_explicit: true,
  webhook_signing_secret_configured: false,
  webhook_verification_mode: 'http_status',
  webhook_provider_options: [
    {
      provider: 'generic_event',
      label: '通用事件 JSON',
      description: '发送 event/data，HTTP 2xx 仅表示接收端接受请求。',
      url_hint: 'https://example.com/webhook',
      signing: 'none',
      verification_mode: 'http_status',
    },
    {
      provider: 'generic_text',
      label: '通用文本 JSON',
      description: '发送 text，HTTP 2xx 仅表示接收端接受请求。',
      url_hint: 'https://example.com/webhook',
      signing: 'none',
      verification_mode: 'http_status',
    },
    {
      provider: 'feishu_lark_v2',
      label: '飞书 / Lark V2',
      description: '发送原生文本并校验平台业务响应，可选签名校验。',
      url_hint: 'https://open.feishu.cn/open-apis/bot/v2/hook/…',
      signing: 'optional',
      verification_mode: 'provider_response',
    },
    {
      provider: 'wecom',
      label: '企业微信群机器人',
      description: '发送原生文本并校验 errcode。',
      url_hint: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…',
      signing: 'none',
      verification_mode: 'provider_response',
    },
    {
      provider: 'dingtalk',
      label: '钉钉自定义机器人',
      description: '发送原生文本并校验 errcode，可选签名校验。',
      url_hint: 'https://oapi.dingtalk.com/robot/send?access_token=…',
      signing: 'optional',
      verification_mode: 'provider_response',
    },
    {
      provider: 'slack',
      label: 'Slack / GovSlack',
      description: '发送 Incoming Webhook 文本并校验 ok 响应。',
      url_hint: 'https://hooks.slack.com/services/…/…/…',
      signing: 'none',
      verification_mode: 'provider_response',
    },
    {
      provider: 'discord',
      label: 'Discord Incoming Webhook',
      description: '发送禁用 mentions 的文本并校验返回消息 ID。',
      url_hint: 'https://discord.com/api/webhooks/…/…',
      signing: 'none',
      verification_mode: 'provider_response',
    },
  ],
  last_test_status: null,
  last_tested_at: null,
  last_test_error_code: null,
  last_alert_status: null,
  last_alerted_at: null,
  last_alert_error_code: null,
  updated_at: '2026-07-29T08:00:00Z',
  ...overrides,
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((next) => {
    resolve = next
  })
  return { promise, resolve }
}

function renderFeature(apiOverrides: Partial<ServiceApi> = {}, queryEnabled = true) {
  const defaultDetail = actorOpsDetail()
  const api = {
    apifyActorXProfileRoute: vi.fn().mockResolvedValue(route()),
    reorderApifyActorXProfileRoute: vi.fn().mockResolvedValue(route({ generation: 8 })),
    enableApifyActorXProfileCandidate: vi.fn().mockResolvedValue(route({ generation: 8 })),
    disableApifyActorXProfileCandidate: vi.fn().mockResolvedValue(route({ generation: 8 })),
    canaryApifyActorXProfileCandidate: vi.fn().mockResolvedValue(route({ generation: 8 })),
    apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(defaultDetail)),
    apifyActorRoute: vi.fn().mockResolvedValue(defaultDetail),
    requestApifyActorSupportCheck: vi.fn().mockResolvedValue({
      schema_version: 1,
      kind: 'route',
      generation: 7,
      route_generation: 7,
      route_id: defaultDetail.route_id,
      support_status: 'supported',
      discovery_run_id: null,
      job: null,
    }),
    apifyActorDiscoveryRun: vi.fn().mockResolvedValue(
      discoveryRun(defaultDetail),
    ),
    canaryApifyActorDiscoveryCandidate: vi.fn().mockResolvedValue({
      schema_version: 1,
      validation: {
        validation_id: 'validation-1',
        route_id: defaultDetail.route_id,
        source_id: null,
        revision_id: 'revision-discovered',
        kind: 'route_reference',
        status: 'queued',
        cost_usd: 0.02,
        created_at: '2026-07-29T08:00:00Z',
      },
      job: { id: 'job-1', status: 'queued' },
    }),
    updateApifyActorRouteActivePool: vi.fn().mockResolvedValue(defaultDetail),
    apifyActorSourceSupport: vi.fn(),
    canaryApifyActorSourceRevision: vi.fn(),
    activateApifyActorSourceBinding: vi.fn(),
    apifyActorDiscoverySettings: vi.fn().mockResolvedValue({
      schema_version: 4,
      generation: 1,
      enabled: false,
      ai_config_id: 'global-ai-111111111111111111111111',
      ai_options: [{
        id: 'global-ai-111111111111111111111111',
        label: 'Gemini Secondary',
        provider: 'gemini',
        model: 'gemini-test',
        key_name: 'Gemini Secondary',
        preferred: true,
        ready: true,
        unavailable_reason: null,
      }],
      max_queries_per_run: 3,
      max_candidates: 12,
      max_output_tokens: 4096,
      recommended_max_output_tokens: null,
      measurements: { youtube: null, instagram: null },
      updated_at: '2026-07-29T08:00:00Z',
    }),
    updateApifyActorDiscoverySettings: vi.fn(),
    measureApifyActorDiscovery: vi.fn(),
    apifyActorAlertSettings: vi.fn().mockResolvedValue(alertSettings()),
    updateApifyActorAlertSettings: vi.fn().mockResolvedValue(alertSettings()),
    testApifyActorAlertSettings: vi.fn().mockResolvedValue({ sent: true, channel: 'webhook' }),
    apifyActorAlertIncidents: vi.fn().mockResolvedValue({
      schema_version: 1,
      incidents: [{
        id: 'incident-1',
        route: 'x/profile',
        event_type: 'actor_switched',
        severity: 'warning',
        status: 'open',
        actor_name: 'Xquik',
        active_actor_name: 'ScrapeBadger',
        reason_code: 'placeholder_records',
        opened_at: '2026-07-29T08:00:00Z',
        last_seen_at: '2026-07-29T08:00:00Z',
        resolved_at: null,
        delivery_status: 'sent',
        delivery_error_code: null,
      }],
    }),
    sources: vi.fn().mockResolvedValue({
      sources: [
        {
          id: 'source-x-1',
          type: 'apify_social',
          display_name: 'X · @thsottiaux',
          scope: 'workspace',
          enabled: true,
          config: { platform: 'x', kind: 'profile', target: 'not-rendered' },
        },
        {
          id: 'source-instagram',
          type: 'apify_social',
          display_name: 'Instagram · OpenAI',
          scope: 'workspace',
          enabled: true,
          config: { platform: 'instagram', kind: 'profile', target: 'not-rendered-either' },
        },
      ],
    }),
    ...apiOverrides,
  } as unknown as ServiceApi
  const token = { userId: 'owner-1', generation: 0 }
  const context = {
    api,
    user: { id: 'owner-1', username: 'owner', role: 'owner', enabled: true },
    query: '',
    setQuery: vi.fn(),
    activity: { state: 'idle', message: '' },
    refresh: vi.fn(),
    beginAction: () => token,
    isActionCurrent: () => true,
  } as unknown as AppOutletContext
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const tree = (enabled: boolean) => <QueryClientProvider client={queryClient}>
    <MemoryRouter>
      <DesignSystemProvider>
        <Routes>
          <Route element={<Outlet context={context} />}>
            <Route index element={<HeroApifyActorRouteSettings queryEnabled={enabled} />} />
          </Route>
        </Routes>
      </DesignSystemProvider>
    </MemoryRouter>
  </QueryClientProvider>
  const view = render(tree(queryEnabled))
  return {
    api,
    queryClient,
    setQueryEnabled: (enabled: boolean) => view.rerender(tree(enabled)),
  }
}

describe('HeroApifyActorRouteSettings', () => {
  beforeEach(() => actionToast.clear())

  it('refreshes route health on the specified 30-second interval', () => {
    expect(APIFY_ACTOR_ROUTE_REFRESH_MS).toBe(30_000)
  })

  it('starts queries only while its settings section is active and stops every poll after leaving', async () => {
    vi.useFakeTimers()
    try {
      const { api, setQueryEnabled } = renderFeature({}, false)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(APIFY_ACTOR_ROUTE_REFRESH_MS * 2)
      })
      expect(api.apifyActorRoutes).not.toHaveBeenCalled()
      expect(api.apifyActorAlertSettings).not.toHaveBeenCalled()
      expect(api.apifyActorAlertIncidents).not.toHaveBeenCalled()

      await act(async () => {
        setQueryEnabled(true)
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(api.apifyActorRoutes).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertSettings).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertIncidents).toHaveBeenCalledOnce()

      await act(async () => {
        setQueryEnabled(false)
        await vi.advanceTimersByTimeAsync(APIFY_ACTOR_ROUTE_REFRESH_MS * 2)
      })
      expect(api.apifyActorRoutes).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertSettings).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertIncidents).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps polling an in-flight Discovery Canary after the approval stage pauses', async () => {
    vi.useFakeTimers()
    try {
      const detail = actorOpsDetail({ discovery_run_id: 'discovery-run-1' })
      const running = discoveryRun(detail)
      running.candidates[0] = {
        ...running.candidates[0],
        validation_status: 'running',
        canary_in_flight: true,
        awaiting_approval: false,
      }
      const apifyActorDiscoveryRun = vi.fn().mockResolvedValue(running)
      renderFeature({
        apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
        apifyActorRoute: vi.fn().mockResolvedValue(detail),
        apifyActorDiscoveryRun,
      })

      await act(async () => {
        await vi.advanceTimersByTimeAsync(100)
      })
      expect(apifyActorDiscoveryRun).toHaveBeenCalledOnce()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3_000)
      })
      expect(apifyActorDiscoveryRun).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows persisted Actor and publisher shortfalls without hiding valid partials', async () => {
    const detail = actorOpsDetail({ discovery_run_id: 'discovery-run-1' })
    const partial = discoveryRun(detail)
    partial.stage = 'candidate_shortfall'
    partial.status = 'candidate_shortfall'
    partial.candidate_count = 1
    partial.candidate_shortfall = 2
    partial.publisher_count = 1
    partial.publisher_shortfall = 1
    partial.error_code = 'input_validation_candidate_shortfall'
    partial.failure_phase = 'input_validation'
    partial.rejections = [{
      reason: 'actor_input_validation_rejected',
      count: 2,
    }]
    partial.candidates[0] = {
      ...partial.candidates[0],
      awaiting_approval: false,
    }
    renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      apifyActorDiscoveryRun: vi.fn().mockResolvedValue(partial),
    })

    expect(await screen.findByText('缺少 2 个 Actor')).toBeVisible()
    expect(screen.getByText('固定 Build 输入校验需要处理')).toBeVisible()
    expect(screen.getByText(/候选输入与固定 Build Schema 不兼容/)).toBeVisible()
    expect(screen.getByText('1/3 Actor · 1/2 发布者；Canary 0/5 次')).toBeVisible()
    expect(within(
      screen.getByRole('list', { name: 'Actor 发现候选' }),
    ).getAllByRole('listitem')).toHaveLength(1)
  })

  it('stops approvals and explains a timed-out exhausted Canary cycle', async () => {
    const detail = actorOpsDetail({ discovery_run_id: 'discovery-run-1' })
    const exhausted = discoveryRun(detail)
    exhausted.stage = 'canary_exhausted'
    exhausted.status = 'canary_exhausted'
    exhausted.error_code = 'route_canary_attempts_exhausted'
    exhausted.failure_phase = 'route_canary'
    exhausted.canary_attempts_used = 5
    exhausted.canary_attempts_limit = 5
    exhausted.canary_attempts_remaining = 0
    exhausted.canary_timeout_seconds = 300
    exhausted.spent_usd = 0.01905
    exhausted.candidates[0] = {
      ...exhausted.candidates[0],
      awaiting_approval: false,
      validation_status: 'failed',
      validation_outcome: 'apify_actor_run_timed_out',
      validation_cost_usd: 0.01905,
      validation_cost_final: true,
      validation_duration_ms: 187_189,
      actor_run_status: 'aborted',
    }
    renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      apifyActorDiscoveryRun: vi.fn().mockResolvedValue(exhausted),
    })

    expect(await screen.findByText('当前候选组不能继续付费验证')).toBeVisible()
    expect(screen.getByText(/Actor 在时限内未完成/)).toBeVisible()
    expect(screen.getByText(/实际费用 \$0\.01905（已终结）/)).toBeVisible()
    expect(screen.getByText(/Canary 5\/5 次/)).toBeVisible()
    expect(screen.queryByRole('button', { name: '确认付费 Canary' })).not.toBeInTheDocument()
  })

  it('renders safe three-slot projections and submits a generation-checked support request', async () => {
    const browser = userEvent.setup()
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue({
        ...actorOpsRoutes(),
        generation: 41,
      }),
    })

    expect(await screen.findByRole(
      'grid',
      { name: 'ActorOps 路由列表' },
    )).toBeInTheDocument()
    expect(await screen.findByRole(
      'grid',
      { name: 'x/profile 三槽 Actor Pool' },
    )).toBeInTheDocument()
    expect(screen.getByText('Publisher A Primary')).toBeInTheDocument()
    expect(screen.getByText('Publisher B Backup')).toBeInTheDocument()
    expect(screen.getByText('Publisher A Probationary')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('not-rendered')

    await browser.click(screen.getByRole('button', { name: '请求支持检查' }))
    await waitFor(() => expect(api.requestApifyActorSupportCheck).toHaveBeenCalledWith({
      platform: 'x',
      target_type: 'profile',
      capability: 'items',
      expected_generation: 41,
      force_discovery: false,
    }))
  })

  it('renders only opaque source ids in embedded validation progress', async () => {
    const detail = actorOpsDetail({
      source_validations: [{
        source_id: 'source-opaque-1',
        source_name: '@private-target-must-not-render',
        binding_status: 'pending_validation',
        generation: 2,
        slots: [],
      } as unknown as ApifyActorSourceValidation],
      source_validation_summary: { ready: 0, pending: 1, failed: 0 },
    })
    renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
    })

    expect(await screen.findByText('source-opaque-1')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('@private-target-must-not-render')
  })

  it('supports explicit route-cap updates and administrator rediscovery', async () => {
    const browser = userEvent.setup()
    const { api } = renderFeature()
    const cap = await screen.findByLabelText('Route 单次费用上限（USD）')
    await browser.clear(cap)
    await browser.type(cap, '0.03')
    await browser.click(screen.getByRole('button', { name: '保存三槽配置' }))
    await waitFor(() => expect(api.updateApifyActorRouteActivePool).toHaveBeenCalledWith(
      'route-x-profile',
      {
        expected_generation: 7,
        per_run_cap_usd: 0.03,
        slots: [
          { slot: 'primary', revision_id: 'revision-primary' },
          { slot: 'backup_1', revision_id: 'revision-backup-1' },
          { slot: 'backup_2', revision_id: 'revision-backup-2' },
        ],
      },
    ))

    await browser.click(screen.getByRole('switch', { name: '仅检查现有支持' }))
    await browser.click(screen.getByRole('button', { name: '请求支持检查' }))
    await waitFor(() => expect(api.requestApifyActorSupportCheck).toHaveBeenLastCalledWith({
      platform: 'x',
      target_type: 'profile',
      capability: 'items',
      expected_generation: 7,
      force_discovery: true,
    }))
  })

  it('rolls back from canonical server slots and sends an explicit revision id', async () => {
    const browser = userEvent.setup()
    const detail = actorOpsDetail({
      revisions: [
        ...actorOpsDetail().revisions,
        {
          ...actorOpsDetail().revisions[0],
          revision_id: 'revision-primary-old',
          build_id: 'build-primary-old',
          build_number: '0.9.1',
          lifecycle: 'superseded',
          can_activate: true,
        },
      ],
    })
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
    })

    await screen.findByRole('grid', { name: 'x/profile 三槽 Actor Pool' })
    await browser.click(screen.getByRole('button', { name: /Backup 1 Revision$/ }))
    await browser.click(await screen.findByRole('option', { name: /Publisher A Primary · 1\.0\.1/ }))
    await browser.click(screen.getByRole('button', { name: '回滚到此 Revision' }))
    await browser.click(within(
      screen.getByRole('dialog', { name: '回滚不可变 Revision' }),
    ).getByRole('button', { name: '确认回滚' }))

    await waitFor(() => expect(api.updateApifyActorRouteActivePool).toHaveBeenCalledWith(
      'route-x-profile',
      {
        expected_generation: 7,
        rollback_revision_id: 'revision-primary-old',
        slots: [
          { slot: 'primary', revision_id: 'revision-primary-old' },
          { slot: 'backup_1', revision_id: 'revision-backup-1' },
          { slot: 'backup_2', revision_id: 'revision-backup-2' },
        ],
      },
    ))
  })

  it('does not offer an active legacy revision as rollback history', async () => {
    const base = actorOpsDetail()
    const activeLegacy = {
      ...base.revisions[0],
      revision_id: 'revision-active-legacy',
      build_id: null,
      build_number: null,
      manifest_hash: null,
      lifecycle: 'legacy_builtin' as const,
      can_activate: true,
    }
    const detail = actorOpsDetail({
      revisions: [activeLegacy, ...base.revisions.slice(1)],
      slots: [
        {
          slot: 'primary',
          revision_id: activeLegacy.revision_id,
          runnable: true,
          revision: activeLegacy,
        },
        ...base.slots.slice(1),
      ],
    })
    renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
    })

    expect(await screen.findByText('当前没有可回滚的历史 Revision。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '回滚到此 Revision' })).not.toBeInTheDocument()
  })

  it('uses an independent source Canary cap bounded by remaining source budget', async () => {
    const browser = userEvent.setup()
    const detail = actorOpsDetail()
    const support = sourceSupport(detail)
    const canaryApifyActorSourceRevision = vi.fn().mockResolvedValue({
      schema_version: 1,
      validation: {
        validation_id: 'validation-source-1',
        route_id: detail.route_id,
        source_id: support.source_id,
        revision_id: detail.revisions[0].revision_id,
        kind: 'source_canary',
        status: 'queued',
        created_at: '2026-07-29T08:00:00Z',
      },
      job: { id: 'job-source-1', status: 'queued' },
    })
    const { api } = renderFeature({
      apifyActorSourceSupport: vi.fn().mockResolvedValue(support),
      canaryApifyActorSourceRevision,
    })

    const lookup = await screen.findByLabelText('按来源 ID 查看三槽验证')
    await browser.type(lookup, support.source_id)
    await browser.click(screen.getByRole('button', { name: '读取验证状态' }))
    expect(await screen.findByText('$0.015 剩余')).toBeVisible()
    const cap = screen.getByLabelText('来源 Canary 单次上限（USD）')
    expect(cap).toHaveValue(0.015)
    await browser.clear(cap)
    await browser.type(cap, '0.007')
    await browser.click(screen.getByRole('button', { name: '验证此槽' }))
    await browser.click(within(
      screen.getByRole('dialog', { name: '确认付费 Canary' }),
    ).getByRole('button', { name: '确认付费试跑' }))

    await waitFor(() => expect(api.canaryApifyActorSourceRevision).toHaveBeenCalledWith(
      support.source_id,
      detail.revisions[0].revision_id,
      expect.objectContaining({
        expected_generation: support.generation,
        confirmation: '确认付费试跑',
        max_total_charge_usd: 0.007,
      }),
    ))
  })

  it('creates one opaque approval id only after the paid Canary confirmation', async () => {
    const browser = userEvent.setup()
    const detail = actorOpsDetail({ discovery_run_id: 'discovery-run-1' })
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      apifyActorDiscoveryRun: vi.fn().mockResolvedValue(discoveryRun(detail)),
    })
    const canaryTrigger = await screen.findByRole(
      'button',
      { name: '确认付费 Canary' },
    )

    await browser.click(canaryTrigger)
    const dialog = screen.getByRole('dialog', { name: '确认付费 Canary' })
    expect(api.canaryApifyActorDiscoveryCandidate).not.toHaveBeenCalled()
    expect(within(dialog).queryByText('not-rendered')).not.toBeInTheDocument()
    expect(within(dialog).getByText(/x \/ profile \/ items/)).toBeVisible()
    expect(within(dialog).getByText(/Route 认证公开参考来源/)).toBeVisible()
    expect(within(dialog).getByText(/\$0\.001–\$0\.015 每计费事件/)).toBeVisible()
    expect(within(dialog).getByText(/本次付费封顶/)).toBeVisible()
    expect(within(dialog).getByText(/总上限 \$0\.10/)).toBeVisible()

    await browser.click(within(dialog).getByRole('button', { name: '确认付费试跑' }))

    await waitFor(() => expect(api.canaryApifyActorDiscoveryCandidate).toHaveBeenCalledWith(
      'discovery-run-1',
      'revision-discovered',
      expect.objectContaining({
        expected_generation: 7,
        approval_id: expect.any(String),
        confirmation: '确认付费试跑',
        max_total_charge_usd: 0.02,
      }),
    ))
    const request = vi.mocked(
      api.canaryApifyActorDiscoveryCandidate,
    ).mock.calls[0][2]
    expect(request.approval_id).toMatch(/^[0-9a-f-]{36}$/)
    expect(document.body.textContent).not.toContain(request.approval_id)
  })

  it('manually selects one safe global AI option and hot-loads it', async () => {
    const browser = userEvent.setup()
    const current = {
      schema_version: 4 as const,
      generation: 4,
      enabled: false,
      ai_config_id: 'global-ai-111111111111111111111111',
      ai_options: [
        {
          id: 'global-ai-111111111111111111111111',
          label: 'Gemini Primary',
          provider: 'gemini',
          model: 'gemini-test',
          key_name: 'Gemini Primary',
          preferred: true,
          ready: true,
          unavailable_reason: null,
        },
        {
          id: 'global-ai-222222222222222222222222',
          label: 'Gemini Secondary',
          provider: 'gemini',
          model: 'gemini-test',
          key_name: 'Gemini Secondary',
          preferred: false,
          ready: true,
          unavailable_reason: null,
        },
      ],
      max_queries_per_run: 2,
      max_candidates: 12,
      max_output_tokens: 4096,
      recommended_max_output_tokens: null,
      measurements: { youtube: null, instagram: null },
      updated_at: '2026-07-29T08:00:00Z',
    }
    const updateApifyActorDiscoverySettings = vi.fn().mockResolvedValue({
      ...current,
      generation: 5,
    })
    const { api } = renderFeature({
      apifyActorDiscoverySettings: vi.fn().mockResolvedValue(current),
      updateApifyActorDiscoverySettings,
    })

    const selector = await screen.findByLabelText('Discovery 使用的全局 AI')
    expect(selector).toBeInTheDocument()
    expect(screen.queryByLabelText('SecretStore 引用')).not.toBeInTheDocument()
    await browser.click(selector)
    await browser.click(await screen.findByRole('option', { name: /Gemini Secondary/ }))
    await browser.click(screen.getByRole('button', { name: '保存并热加载' }))

    await waitFor(() => expect(api.updateApifyActorDiscoverySettings).toHaveBeenCalledWith({
      expected_generation: 4,
      enabled: false,
      ai_config_id: 'global-ai-222222222222222222222222',
      max_queries_per_run: 2,
      max_candidates: 12,
      max_output_tokens: 4096,
    }))
  })

  it('keeps unsafe server details out of ActorOps action feedback', async () => {
    const browser = userEvent.setup()
    renderFeature({
      requestApifyActorSupportCheck: vi.fn().mockRejectedValue(new ApiError(502, {
        code: 'unexpected_upstream_failure',
        message: 'runId=unsafe-run datasetId=unsafe-dataset',
      })),
    })

    await browser.click(await screen.findByRole(
      'button',
      { name: '请求支持检查' },
    ))
    expect(await screen.findByText('支持检查请求失败')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('unsafe-run')
    expect(document.body.textContent).not.toContain('unsafe-dataset')
  })

  it('refreshes and shows persisted unknown status after an ambiguous alert test', async () => {
    const browser = userEvent.setup()
    const apifyActorAlertSettings = vi.fn()
      .mockResolvedValueOnce(alertSettings())
      .mockResolvedValue(alertSettings({
        last_test_status: 'unknown',
        last_tested_at: '2026-07-30T08:00:00Z',
        last_test_error_code: 'notification_webhook_response_invalid',
      }))
    const testApifyActorAlertSettings = vi.fn().mockRejectedValue(new ApiError(502, {
      code: 'apify_actor_alert_test_outcome_unknown',
      message: 'raw upstream response must stay private',
      retryable: false,
    }))
    const { api } = renderFeature({
      apifyActorAlertSettings,
      testApifyActorAlertSettings,
    })

    expect(await screen.findByText(/尚未发送测试通知/)).toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '发送测试告警' }))

    await waitFor(() => expect(apifyActorAlertSettings).toHaveBeenCalledTimes(2))
    expect(await screen.findByText(/最近一次测试结果未知，不会自动重发/)).toBeVisible()
    expect(screen.getByText('测试告警结果未知，请勿重复发送；请先确认接收端。')).toBeVisible()
    expect(api.testApifyActorAlertSettings).toHaveBeenCalledOnce()
    expect(document.body.textContent).not.toContain('raw upstream')
  })
})

describe('ApifyActorAlertSettingsForm', () => {
  beforeEach(() => actionToast.clear())

  it('keeps the Webhook write-only and clears it as soon as saving starts', async () => {
    const browser = userEvent.setup()
    const request = deferred<ApifyActorAlertSettings>()
    const onSave = vi.fn().mockReturnValue(request.promise)
    render(<MemoryRouter><DesignSystemProvider>
      <ApifyActorAlertSettingsForm
        settings={alertSettings({
          last_alert_status: 'sent',
          last_alerted_at: '2026-07-29T13:50:46Z',
        })}
        onSave={onSave}
        onTest={vi.fn().mockResolvedValue({ sent: true, channel: 'webhook' })}
      />
    </DesignSystemProvider></MemoryRouter>)

    const destination = screen.getByLabelText('告警 Webhook 地址')
    expect(destination).toHaveAttribute('type', 'password')
    expect(screen.getByText(/平台预设会校验业务响应/)).toBeVisible()
    expect(screen.getByText(/保存成功仅表示配置已写入/)).toBeVisible()
    expect(screen.getByText(/最近一次运行告警请求已发送，请确认接收端/)).toBeVisible()
    await browser.type(destination, 'https://example.invalid/actor-alert')
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channel: 'webhook',
      events: alertSettings().events,
      webhook_url: 'https://example.invalid/actor-alert',
      webhook_provider: 'generic_event',
    })
    expect(destination).toHaveValue('')
    expect(document.body.textContent).not.toContain('https://example.invalid/actor-alert')

    await act(async () => request.resolve(alertSettings()))
  })

  it('requires at least one event and never repeats an unsafe server message', async () => {
    const browser = userEvent.setup()
    const onSave = vi.fn().mockRejectedValue(new ApiError(500, {
      code: 'unexpected_alert_failure',
      message: 'https://secret.invalid/hook runId=never-render',
    }))
    render(<MemoryRouter><DesignSystemProvider>
      <ApifyActorAlertSettingsForm
        settings={alertSettings()}
        onSave={onSave}
        onTest={vi.fn().mockResolvedValue({ sent: true, channel: 'webhook' })}
      />
    </DesignSystemProvider></MemoryRouter>)

    const destination = screen.getByLabelText('告警 Webhook 地址')
    await browser.type(destination, 'https://secret.invalid/hook')
    for (const label of Object.values({
      switched: '自动切换 Actor',
      exhausted: '三个 Actor 全部不可用',
      quota: 'Apify 额度偏低',
      budget: '额度耗尽或费用熔断',
      unknown: 'Actor 启动结果未知',
      recovered: '故障恢复',
    })) {
      await browser.click(screen.getByRole('checkbox', { name: label }))
    }
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))
    expect(onSave).not.toHaveBeenCalled()
    expect(await screen.findByText('启用运行告警时，请至少选择一种告警事件。')).toBeInTheDocument()
    expect(destination).toHaveValue('')
    expect(document.body.textContent).not.toContain('https://secret.invalid/hook')

    await browser.click(screen.getByRole('checkbox', { name: '自动切换 Actor' }))
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))
    expect((await screen.findAllByText('Apify 运行告警设置保存失败，请稍后重试。')).length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toContain('secret.invalid')
    expect(document.body.textContent).not.toContain('never-render')
  })

  it('requires an active legacy Webhook to be upgraded before any alert edit', async () => {
    const browser = userEvent.setup()
    const onSave = vi.fn().mockResolvedValue(alertSettings({
      events: alertSettings().events.filter((event) => event !== 'actor_switched'),
      webhook_provider_explicit: true,
    }))
    render(<MemoryRouter><DesignSystemProvider>
      <ApifyActorAlertSettingsForm
        settings={alertSettings({ webhook_provider_explicit: false })}
        onSave={onSave}
        onTest={vi.fn().mockResolvedValue({ sent: true, channel: 'webhook' })}
      />
    </DesignSystemProvider></MemoryRouter>)

    await browser.click(screen.getByRole('checkbox', { name: '自动切换 Actor' }))
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))

    expect(onSave).not.toHaveBeenCalled()
    expect(await screen.findByText('升级旧 Webhook 配置时，请选择类型并重新输入对应地址。')).toBeVisible()

    await browser.type(
      screen.getByLabelText('告警 Webhook 地址'),
      'https://hooks.example.com/upgraded-alert',
    )
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channel: 'webhook',
      events: alertSettings().events.filter((event) => event !== 'actor_switched'),
      webhook_url: 'https://hooks.example.com/upgraded-alert',
      webhook_provider: 'generic_event',
    }))
  })
})
