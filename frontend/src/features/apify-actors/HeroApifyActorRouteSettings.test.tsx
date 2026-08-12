import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type {
  ApifyActorAlertSettings,
  ApifyActorCanaryBatch,
  ApifyActorCanaryPlan,
  ApifyActorDiscoveryRun,
  NotificationTarget,
  ApifyActorRouteDetail,
  ApifyActorRoutesResponse,
  ApifyActorSourceValidation,
  ApifyActorSourceSupport,
} from '../../api/types'
import type { AppOutletContext } from '../../app/AppContext'
import { actionToast, DesignSystemProvider } from '../../design-system'
import {
  ApifyActorAlertSettingsPanel,
  ApifyActorIncidentList,
} from './HeroApifyActorRouteSettings'
import { HeroActorOpsControlPlane } from './HeroActorOpsControlPlane'
import { APIFY_ACTOR_ROUTE_REFRESH_MS } from './apifyActorModel'

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
    activation_recommendation: {
      ready: true,
      already_active: true,
      confirmation: '确认启用 Actor 主备',
      problems: [],
      certified_actor_count: 2,
      backup_2_actor_count: 3,
      runnable_actor_count: 3,
      publisher_count: 2,
      activation_mode: 'standard_2plus1',
      slots: [
        { slot: 'primary', revision_id: revisions[0].revision_id, revision: revisions[0] },
        { slot: 'backup_1', revision_id: revisions[1].revision_id, revision: revisions[1] },
        { slot: 'backup_2', revision_id: revisions[2].revision_id, revision: revisions[2] },
      ],
    },
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
  schema_version: 5,
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

const canaryPlan = (
  detail: ApifyActorRouteDetail,
): ApifyActorCanaryPlan => ({
  schema_version: 1,
  run_id: 'discovery-run-1',
  route_id: detail.route_id,
  route_key: detail.route_key,
  platform: detail.platform,
  target_type: detail.target_type,
  capability: detail.capability,
  mode: detail.mode,
  generation: detail.generation,
  status: 'ready',
  ready: true,
  activation_ready: false,
  plan_hash: 'a'.repeat(64),
  max_candidates: 3,
  max_total_charge_usd: 0.04,
  per_candidate_cap_usd: 0.02,
  successful_actor_count: 0,
  successful_publisher_count: 0,
  attempts_used: 1,
  attempts_remaining: 4,
  budget_remaining_usd: 0.08,
  items: [
    {
      ordinal: 1,
      revision_id: 'revision-discovered',
      actor_id: 'publisher-c/discovered',
      publisher: 'publisher-c',
      build_id: 'build-discovered',
      build_number: '2.0.0',
      lifecycle: 'static_valid',
      pricing: {
        model: 'PAY_PER_EVENT',
        billing_unit: 'event',
        unit_price_min_usd: 0.001,
        unit_price_max_usd: 0.015,
        minimum_charge_usd: null,
        minimum_run_cap_usd: 0.02,
      },
      authorized_cap_usd: 0.02,
    },
    {
      ordinal: 2,
      revision_id: 'revision-second',
      actor_id: 'publisher-d/second',
      publisher: 'publisher-d',
      build_id: 'build-second',
      build_number: '3.0.0',
      lifecycle: 'static_valid',
      pricing: {
        model: 'PAY_PER_EVENT',
        billing_unit: 'event',
        unit_price_min_usd: 0.002,
        unit_price_max_usd: 0.002,
        minimum_charge_usd: null,
        minimum_run_cap_usd: 0.02,
      },
      authorized_cap_usd: 0.02,
    },
  ],
})

const queuedCanaryBatch = (detail: ApifyActorRouteDetail): ApifyActorCanaryBatch => ({
  schema_version: 1,
  batch_id: 'canary-batch-1',
  route_id: detail.route_id,
  discovery_run_id: 'discovery-run-1',
  approved_generation: detail.generation,
  plan_hash: 'a'.repeat(64),
  max_candidates: 3,
  max_total_charge_usd: 0.04,
  per_candidate_cap_usd: 0.02,
  status: 'queued',
  planned_count: 2,
  success_count: 0,
  publisher_count: 0,
  actual_cost_usd: null,
  cost_final: false,
  stop_reason: null,
  created_at: '2026-07-29T08:00:00Z',
  started_at: null,
  completed_at: null,
  updated_at: '2026-07-29T08:00:00Z',
  items: canaryPlan(detail).items.map((item) => ({
    ...item,
    status: 'planned',
    semantic_outcome: null,
    actual_cost_usd: null,
    cost_final: false,
    preflight_checked_at: null,
    started_at: null,
    completed_at: null,
  })),
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
  reserved_usd: 0,
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
  schema_version: 4,
  enabled: true,
  target_ids: [],
  selected_targets: [],
  channels: ['webhook'],
  channel: 'webhook',
  channel_states: {
    email: {
      enabled: false,
      configured: false,
      available: true,
      generation: 1,
      enabled_at: null,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
    },
    webhook: {
      enabled: true,
      configured: true,
      available: true,
      generation: 2,
      enabled_at: '2026-07-30T00:00:00Z',
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
      provider: 'generic_event',
      provider_explicit: true,
      signing_secret_configured: false,
      verification_mode: 'http_status',
    },
    telegram: {
      enabled: false,
      configured: false,
      available: true,
      generation: 1,
      enabled_at: null,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
    },
  },
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
  telegram_configured: false,
  telegram_transport_ready: true,
  last_test_status: null,
  last_tested_at: null,
  last_test_error_code: null,
  last_alert_status: null,
  last_alerted_at: null,
  last_alert_error_code: null,
  updated_at: '2026-07-29T08:00:00Z',
  ...overrides,
})

const sharedTarget = (overrides: Partial<NotificationTarget> = {}): NotificationTarget => ({
  id: 'target-shared-webhook',
  name: '运维告警群',
  scope: 'shared',
  channel: 'webhook',
  configured: true,
  enabled: true,
  available: true,
  transport_ready: true,
  config_generation: 1,
  activation_generation: 1,
  enabled_at: '2026-07-30T00:00:00Z',
  last_test_status: 'sent',
  last_tested_at: '2026-07-30T00:00:00Z',
  last_test_error_code: null,
  can_edit: true,
  can_test: true,
  can_enable: true,
  usage: {
    user_binding_count: 0,
    alert_binding_count: 0,
    preferred_active_delivery_count: 0,
    alert_active_delivery_count: 0,
  },
  updated_at: '2026-07-30T00:00:00Z',
  webhook_provider: 'generic_event',
  webhook_signing_secret_configured: false,
  webhook_verification_mode: 'http_status',
  ...overrides,
})

function renderFeature(apiOverrides: Partial<ServiceApi> = {}, queryEnabled = true) {
  const defaultDetail = actorOpsDetail()
  const api = {
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
    apifyActorCanaryPlan: vi.fn().mockResolvedValue(canaryPlan(defaultDetail)),
    createApifyActorCanaryBatch: vi.fn().mockResolvedValue({
      schema_version: 1,
      batch: queuedCanaryBatch(defaultDetail),
      job: { id: 'job-canary-batch-1', status: 'queued' },
    }),
    apifyActorCanaryBatch: vi.fn().mockResolvedValue(
      queuedCanaryBatch(defaultDetail),
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
    activateApifyActorRouteRecommendedPool: vi.fn().mockResolvedValue(defaultDetail),
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
    notificationServices: vi.fn().mockResolvedValue({
      schema_version: 1,
      services: [{ ...sharedTarget(), legacy_private: false, can_validate: true }],
      channel_credentials: {
        email: {
          configured: true,
          ready: true,
          generation: 1,
          provider: 'smtp',
          sender_name: 'Inteliscope',
          region: null,
          sender_email_configured: true,
          smtp_username_configured: true,
          providers: [],
        },
        telegram: { configured: false, ready: false, generation: 0 },
        webhook: { configured: true, ready: true, generation: 0 },
      },
      webhook_provider_options: alertSettings().webhook_provider_options,
      can_manage: true,
    }),
    apifyActorAlertIncidents: vi.fn().mockResolvedValue({
      schema_version: 3,
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
        deliveries: [],
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
            <Route index element={<>
              <HeroActorOpsControlPlane queryEnabled={enabled} />
              <ApifyActorAlertSettingsPanel queryEnabled={enabled} />
              <ApifyActorIncidentList queryEnabled={enabled} />
            </>} />
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

describe('current ActorOps settings panels', () => {
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

  it('offers expedited two-Actor activation without another paid attempt', async () => {
    const base = actorOpsDetail()
    const expeditedRevisions = base.revisions.map((revision, index) => ({
      ...revision,
      lifecycle: index < 2 ? 'probationary' as const : 'static_valid' as const,
    }))
    const detail = actorOpsDetail({
      discovery_run_id: 'discovery-run-1',
      workflow: {
        kind: 'setup_activation_approval_required',
        goal: 'initial_pool',
        progress: {},
        blockers: [],
      },
      support_status: 'pending',
      runtime_status: 'blocked',
      runnable_slots: 0,
      publisher_count: 0,
      revisions: expeditedRevisions,
      slots: [
        { slot: 'primary', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_1', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_2', revision_id: null, runnable: false, revision: null },
      ],
      activation_recommendation: {
        ready: true,
        already_active: false,
        confirmation: '确认启用 Actor 主备',
        problems: [],
        certified_actor_count: 0,
        backup_2_actor_count: 2,
        runnable_actor_count: 2,
        publisher_count: 2,
        activation_mode: 'expedited_2of3',
        slots: [
          { slot: 'primary', revision_id: expeditedRevisions[0].revision_id, revision: expeditedRevisions[0] },
          { slot: 'backup_1', revision_id: expeditedRevisions[1].revision_id, revision: expeditedRevisions[1] },
          { slot: 'backup_2', revision_id: null, revision: null },
        ],
      },
    })
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
    })

    expect(await screen.findByText('标准主备验证通过')).toBeVisible()
    expect(screen.getByText(/以 2\/3 标准主备开始运行/)).toBeVisible()
    expect(screen.getByRole('button', { name: '查看并确认启用' })).toBeVisible()
    expect(screen.queryByRole('button', { name: /付费验证/ })).not.toBeInTheDocument()
    expect(api.createApifyActorCanaryBatch).not.toHaveBeenCalled()
  })

  it('hides manual Revision configuration until candidate approval is complete', async () => {
    const detail = actorOpsDetail({
      workflow: {
        kind: 'setup_discovery_running',
        goal: 'initial_pool',
        progress: {},
        blockers: [],
      },
      runnable_slots: 0,
      publisher_count: 0,
      slots: [
        { slot: 'primary', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_1', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_2', revision_id: null, runnable: false, revision: null },
      ],
      activation_recommendation: {
        ready: false,
        already_active: false,
        confirmation: '确认启用 Actor 主备',
        problems: ['certified_candidates_incomplete'],
        certified_actor_count: 0,
        backup_2_actor_count: 2,
        runnable_actor_count: 0,
        publisher_count: 2,
        activation_mode: null,
        slots: [],
      },
    })
    renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
    })

    expect(await screen.findByText('正在搜索可用 Actor')).toBeVisible()
    expect(screen.queryByText('替换 Revision')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '保存三槽配置' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Revision 差异与回滚/ })).not.toBeInTheDocument()
  })

  it('activates the server-recommended pool with one explicit confirmation', async () => {
    const browser = userEvent.setup()
    const base = actorOpsDetail()
    const detail = actorOpsDetail({
      workflow: {
        kind: 'setup_activation_approval_required',
        goal: 'initial_pool',
        progress: {},
        blockers: [],
      },
      support_status: 'pending',
      runtime_status: 'blocked',
      runnable_slots: 0,
      publisher_count: 0,
      slots: [
        { slot: 'primary', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_1', revision_id: null, runnable: false, revision: null },
        { slot: 'backup_2', revision_id: null, runnable: false, revision: null },
      ],
      activation_recommendation: {
        ready: true,
        already_active: false,
        confirmation: '确认启用 Actor 主备',
        problems: [],
        certified_actor_count: 2,
        backup_2_actor_count: 3,
        runnable_actor_count: 3,
        publisher_count: 2,
        activation_mode: 'standard_2plus1',
        slots: [
          { slot: 'primary', revision_id: base.revisions[0].revision_id, revision: base.revisions[0] },
          { slot: 'backup_1', revision_id: base.revisions[1].revision_id, revision: base.revisions[1] },
          { slot: 'backup_2', revision_id: base.revisions[2].revision_id, revision: base.revisions[2] },
        ],
      },
    })
    const activate = vi.fn().mockResolvedValue(base)
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      activateApifyActorRouteRecommendedPool: activate,
    })

    expect(await screen.findByText('标准主备验证通过')).toBeVisible()
    expect(screen.queryByText('替换 Revision')).not.toBeInTheDocument()
    await browser.click(screen.getByRole('button', { name: '查看并确认启用' }))
    const dialog = await screen.findByRole('dialog', { name: '确认启用 Actor 主备' })
    await browser.click(within(dialog).getByRole('button', { name: '确认生效' }))

    await waitFor(() => expect(api.activateApifyActorRouteRecommendedPool).toHaveBeenCalledWith(
      detail.route_id,
      {
        expected_generation: detail.generation,
        confirmation: '确认启用 Actor 主备',
      },
    ))
    expect(api.updateApifyActorRouteActivePool).not.toHaveBeenCalled()
  })

  it('renders the current three-slot projection without unsafe targets', async () => {
    renderFeature()
    expect(await screen.findByText('主用')).toBeInTheDocument()
    expect(screen.getByText('备用 1')).toBeInTheDocument()
    expect(screen.getByText('备用 2')).toBeInTheDocument()
    expect(screen.getByText('Publisher A Primary')).toBeInTheDocument()
    expect(screen.getByText('Publisher B Backup')).toBeInTheDocument()
    expect(screen.getByText('Publisher A Probationary')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('not-rendered')
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

    const browser = userEvent.setup()
    await browser.click(await screen.findByRole('tab', { name: /来源启用/ }))
    expect(await screen.findByText('来源 · aque-1')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('@private-target-must-not-render')
    expect(document.body.textContent).not.toContain('source-opaque-1')
  })

  it('updates the route cap from the current advanced settings surface', async () => {
    const browser = userEvent.setup()
    const { api } = renderFeature()
    await browser.click(await screen.findByRole('button', { name: /^高级设置与技术详情/ }))
    await browser.click(screen.getByRole('button', { name: /^Route 单次费用上限/ }))
    const cap = await screen.findByLabelText('单次费用上限（USD）')
    await browser.clear(cap)
    await browser.type(cap, '0.03')
    await browser.click(screen.getByRole('button', { name: '保存费用上限' }))
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

    await browser.click(await screen.findByRole('button', { name: /^高级设置与技术详情/ }))
    await browser.click(screen.getByRole('button', { name: /^Revision 差异与回滚/ }))
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
    const browser = userEvent.setup()
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

    await browser.click(await screen.findByRole('button', { name: /^高级设置与技术详情/ }))
    await browser.click(screen.getByRole('button', { name: /^Revision 差异与回滚/ }))
    expect(await screen.findByText('当前没有可回滚的历史 Revision。')).toBeVisible()
    expect(screen.queryByRole('button', { name: '回滚到此 Revision' })).not.toBeInTheDocument()
  })

  it('uses an independent source Canary cap bounded by remaining source budget', async () => {
    const browser = userEvent.setup()
    const detail = actorOpsDetail({
      source_validations: [{
        source_id: 'source-x-1',
        binding_status: 'pending_validation',
        generation: 3,
        slots: [],
      } as unknown as ApifyActorSourceValidation],
      source_validation_summary: { ready: 0, pending: 1, failed: 0 },
    })
    const support = sourceSupport(detail, { source_id: 'source-x-1' })
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
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      apifyActorSourceSupport: vi.fn().mockResolvedValue(support),
      canaryApifyActorSourceRevision,
    })

    await browser.click(await screen.findByRole('tab', { name: /来源启用/ }))
    await browser.click(await screen.findByRole('button', { name: '继续验证' }))
    expect(await screen.findByText(/剩余 \$0\.015/)).toBeVisible()
    await browser.click(screen.getByRole('button', { name: '查看并确认付费验证' }))
    await browser.click(within(
      screen.getByRole('dialog', { name: '确认来源付费验证' }),
    ).getByRole('button', { name: '确认付费试跑' }))

    await waitFor(() => expect(api.canaryApifyActorSourceRevision).toHaveBeenCalledWith(
      support.source_id,
      detail.revisions[0].revision_id,
      expect.objectContaining({
        expected_generation: support.generation,
        confirmation: '确认付费试跑',
        max_total_charge_usd: 0.015,
      }),
    ))
  })

  it('requires an explicit confirmation before first enabling a validated source', async () => {
    const browser = userEvent.setup()
    const detail = actorOpsDetail({
      source_validations: [{
        source_id: 'source-x-1',
        binding_status: 'pending_activation',
        generation: 3,
        slots: [],
      } as unknown as ApifyActorSourceValidation],
      source_validation_summary: { ready: 0, pending: 1, failed: 0 },
    })
    const support = sourceSupport(detail, {
      source_id: 'source-x-1',
      slots: detail.slots.map((slot) => ({
        slot: slot.slot,
        revision_id: slot.revision_id,
        status: 'passed',
        last_canary_at: '2026-07-29T08:00:00Z',
        last_canary_status: 'valid_nonempty',
        can_canary: false,
      })),
      activation_confirmation: '确认首次启用',
    })
    const activateApifyActorSourceBinding = vi.fn().mockResolvedValue(support)
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      apifyActorSourceSupport: vi.fn().mockResolvedValue(support),
      activateApifyActorSourceBinding,
    })

    await browser.click(await screen.findByRole('tab', { name: /来源启用/ }))
    await browser.click(await screen.findByRole('button', { name: '继续验证' }))
    await browser.click(await screen.findByRole('button', { name: '查看并确认首次启用' }))
    expect(api.activateApifyActorSourceBinding).not.toHaveBeenCalled()
    await browser.click(within(
      screen.getByRole('dialog', { name: '确认首次启用来源' }),
    ).getByRole('button', { name: '确认首次启用' }))

    await waitFor(() => expect(api.activateApifyActorSourceBinding).toHaveBeenCalledWith(
      'source-x-1',
      { expected_generation: 3, confirmation: '确认首次启用' },
    ))
  })

  it('creates one opaque approval id only after the batch Canary confirmation', async () => {
    const browser = userEvent.setup()
    const detail = actorOpsDetail({
      discovery_run_id: 'discovery-run-1',
      workflow: {
        kind: 'setup_canary_approval_required',
        goal: 'initial_pool',
        run_id: 'discovery-run-1',
        progress: {},
        blockers: [],
      },
      activation_recommendation: {
        ready: false,
        already_active: false,
        confirmation: '确认启用 Actor 主备',
        problems: ['canary_successful_candidates_incomplete'],
        certified_actor_count: 0,
        backup_2_actor_count: 1,
        runnable_actor_count: 1,
        publisher_count: 1,
        activation_mode: null,
        slots: [],
      },
    })
    const plan = canaryPlan(detail)
    const createApifyActorCanaryBatch = vi.fn().mockResolvedValue({
      schema_version: 1,
      batch: queuedCanaryBatch(detail),
      job: { id: 'job-canary-batch-1', status: 'queued' },
    })
    const { api } = renderFeature({
      apifyActorRoutes: vi.fn().mockResolvedValue(actorOpsRoutes(detail)),
      apifyActorRoute: vi.fn().mockResolvedValue(detail),
      apifyActorDiscoveryRun: vi.fn().mockResolvedValue(discoveryRun(detail)),
      apifyActorCanaryPlan: vi.fn().mockResolvedValue(plan),
      createApifyActorCanaryBatch,
    })
    const canaryTrigger = await screen.findByRole('button', { name: '查看并确认付费验证' })

    await browser.click(canaryTrigger)
    const dialog = await screen.findByRole('dialog', { name: '验证所选 Actor' })
    expect(api.createApifyActorCanaryBatch).not.toHaveBeenCalled()
    expect(within(dialog).queryByText('not-rendered')).not.toBeInTheDocument()
    expect(within(dialog).getByText('X 用户动态')).toBeVisible()
    expect(within(dialog).getByText(/严格串行，并受总费用上限保护/)).toBeVisible()
    expect(within(dialog).getByText(/本批总费用上限/)).toBeVisible()
    expect(within(dialog).getAllByText(/publisher-c/)).not.toHaveLength(0)

    await browser.click(within(dialog).getByRole('button', { name: /确认验证（最高/ }))

    await waitFor(() => expect(api.createApifyActorCanaryBatch).toHaveBeenCalledWith(
      'discovery-run-1',
      expect.objectContaining({
        expected_generation: 7,
        expected_plan_hash: 'a'.repeat(64),
        approval_id: expect.any(String),
        confirmation: '确认付费验证主备',
        goal: 'initial_pool',
        max_candidates: 3,
        max_total_charge_usd: 0.04,
      }),
    ))
    const request = vi.mocked(
      api.createApifyActorCanaryBatch,
    ).mock.calls[0][1]
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

    await browser.click(await screen.findByRole('button', { name: /^高级设置与技术详情/ }))
    expect(api.apifyActorDiscoverySettings).not.toHaveBeenCalled()
    await browser.click(screen.getByRole('button', { name: /^候选搜索 AI/ }))
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
    const danger = vi.spyOn(actionToast, 'danger').mockReturnValue('route-cap-error')
    renderFeature({
      updateApifyActorRouteActivePool: vi.fn().mockRejectedValue(new ApiError(502, {
        code: 'unexpected_upstream_failure',
        message: 'runId=unsafe-run datasetId=unsafe-dataset',
      })),
    })

    await browser.click(await screen.findByRole('button', { name: /^高级设置与技术详情/ }))
    await browser.click(screen.getByRole('button', { name: /^Route 单次费用上限/ }))
    const cap = await screen.findByLabelText('单次费用上限（USD）')
    await browser.clear(cap)
    await browser.type(cap, '0.03')
    await browser.click(screen.getByRole('button', { name: '保存费用上限' }))
    await waitFor(() => expect(danger).toHaveBeenCalledWith(
      '高级 Route 设置更新失败',
      { description: 'Route 已变化，请刷新后重试。' },
    ))
    expect(document.body.textContent).not.toContain('unsafe-run')
    expect(document.body.textContent).not.toContain('unsafe-dataset')
  })

  it('selects a shared target without repeating target configuration or testing', async () => {
    const browser = userEvent.setup()
    const selected = sharedTarget()
    const updateApifyActorAlertSettings = vi.fn().mockResolvedValue(alertSettings({
      target_ids: [selected.id],
      selected_targets: [selected],
    }))
    const { api } = renderFeature({
      notificationServices: vi.fn().mockResolvedValue({
        schema_version: 1,
        services: [{ ...selected, legacy_private: false, can_validate: true }],
        channel_credentials: {
          email: {
            configured: true,
            ready: true,
            generation: 1,
            provider: 'smtp',
            sender_name: 'Inteliscope',
            region: null,
            sender_email_configured: true,
            smtp_username_configured: true,
            providers: [],
          },
          telegram: { configured: false, ready: false, generation: 0 },
          webhook: { configured: true, ready: true, generation: 0 },
        },
        webhook_provider_options: alertSettings().webhook_provider_options,
        can_manage: true,
      }),
      updateApifyActorAlertSettings,
    })

    await browser.click(await screen.findByRole('button', { name: '编辑告警' }))
    await browser.click(await screen.findByRole('checkbox', { name: selected.name }))
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))

    await waitFor(() => expect(updateApifyActorAlertSettings).toHaveBeenCalledWith({
      enabled: true,
      target_ids: [selected.id],
      events: alertSettings().events,
    }))
    expect(api.testApifyActorAlertSettings).not.toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: /发送.*测试/ })).not.toBeInTheDocument()
  })

  it('loads shared notification services only after opening the alert editor', async () => {
    const browser = userEvent.setup()
    const notificationServices = vi.fn().mockResolvedValue({
      schema_version: 1,
      services: [],
      channel_credentials: {
        email: { configured: false, ready: false, generation: 0, provider: null, sender_name: null, region: null, sender_email_configured: false, smtp_username_configured: false, providers: [] },
        telegram: { configured: false, ready: false, generation: 0 },
        webhook: { configured: false, ready: false, generation: 0 },
      },
      webhook_provider_options: alertSettings().webhook_provider_options,
      can_manage: true,
    })
    renderFeature({ notificationServices })

    const trigger = await screen.findByRole('button', { name: '编辑告警' })
    expect(notificationServices).not.toHaveBeenCalled()
    await browser.click(trigger)
    await waitFor(() => expect(notificationServices).toHaveBeenCalledOnce())
    expect(await screen.findByRole('heading', { name: '编辑运行告警' })).toBeVisible()
  })

  it('shows five recent incidents before the older-record disclosure', async () => {
    const browser = userEvent.setup()
    renderFeature({
      apifyActorAlertIncidents: vi.fn().mockResolvedValue({
        schema_version: 3,
        incidents: Array.from({ length: 7 }, (_, index) => ({
          id: `incident-${index + 1}`,
          route: 'x/profile',
          event_type: 'actor_switched',
          severity: 'warning',
          status: 'open',
          actor_name: `Actor ${index + 1}`,
          active_actor_name: null,
          reason_code: 'placeholder_records',
          opened_at: `2026-07-29T0${index}:00:00Z`,
          last_seen_at: `2026-07-29T0${index}:00:00Z`,
          resolved_at: null,
          deliveries: [],
          delivery_status: 'sent',
          delivery_error_code: null,
        })),
      }),
    })

    expect(await screen.findByText('涉及 Actor 5')).toBeVisible()
    expect(screen.getByText('涉及 Actor 6')).not.toBeVisible()
    await browser.click(screen.getByRole('button', { name: /查看全部事件/ }))
    expect(screen.getByText('涉及 Actor 6')).toBeVisible()
    expect(screen.getByText('涉及 Actor 7')).toBeVisible()
  })
})
