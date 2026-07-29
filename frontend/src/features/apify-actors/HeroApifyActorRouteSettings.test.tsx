import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../../api/client'
import type { ServiceApi } from '../../api/service'
import type {
  ApifyActorAlertSettings,
  ApifyActorRoute,
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

const alertSettings = (
  overrides: Partial<ApifyActorAlertSettings> = {},
): ApifyActorAlertSettings => ({
  schema_version: 1,
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
  const api = {
    apifyActorXProfileRoute: vi.fn().mockResolvedValue(route()),
    reorderApifyActorXProfileRoute: vi.fn().mockResolvedValue(route({ generation: 8 })),
    enableApifyActorXProfileCandidate: vi.fn().mockResolvedValue(route({ generation: 8 })),
    disableApifyActorXProfileCandidate: vi.fn().mockResolvedValue(route({ generation: 8 })),
    canaryApifyActorXProfileCandidate: vi.fn().mockResolvedValue(route({ generation: 8 })),
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
      expect(api.apifyActorXProfileRoute).not.toHaveBeenCalled()
      expect(api.apifyActorAlertSettings).not.toHaveBeenCalled()
      expect(api.apifyActorAlertIncidents).not.toHaveBeenCalled()

      await act(async () => {
        setQueryEnabled(true)
        await vi.advanceTimersByTimeAsync(0)
      })
      expect(api.apifyActorXProfileRoute).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertSettings).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertIncidents).toHaveBeenCalledOnce()

      await act(async () => {
        setQueryEnabled(false)
        await vi.advanceTimersByTimeAsync(APIFY_ACTOR_ROUTE_REFRESH_MS * 2)
      })
      expect(api.apifyActorXProfileRoute).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertSettings).toHaveBeenCalledOnce()
      expect(api.apifyActorAlertIncidents).toHaveBeenCalledOnce()
    } finally {
      vi.useRealTimers()
    }
  })

  it('renders only safe route projections and submits one complete generation-checked order', async () => {
    const browser = userEvent.setup()
    const { api } = renderFeature()

    expect(await screen.findByText('当前使用：ScrapeBadger')).toBeInTheDocument()
    expect(screen.getByText('可以抓取')).toBeInTheDocument()
    expect(screen.getByRole('grid', { name: 'X 抓取主备 Actor' })).toBeInTheDocument()
    expect(screen.getByText('scrape.badger/twitter-tweets-scraper')).toBeInTheDocument()
    expect(screen.getByText('Apify Free 约 $15.00 / 千条')).toBeInTheDocument()
    expect(screen.getByText('Apify 付费计划约 $0.15 / 千条')).toBeInTheDocument()
    expect(screen.getAllByText('费用判断以实际账单为准')).toHaveLength(3)
    expect(screen.queryByText('最近一次运行告警发送成功', { exact: false })).not.toBeInTheDocument()
    expect(screen.getAllByText('自动切换 Actor').length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toContain('not-rendered')

    const primaryRow = screen.getByRole('row', { name: /ScrapeBadger/ })
    await browser.click(within(primaryRow).getByRole('button', { name: '下移 ScrapeBadger' }))
    await waitFor(() => expect(api.reorderApifyActorXProfileRoute).toHaveBeenCalledWith(
      ['dami', 'scrape-badger', 'xquik'],
      7,
    ))
  })

  it('requires an explicit X source and a second confirmation before paid canary', async () => {
    const browser = userEvent.setup()
    const { api } = renderFeature()
    const primaryRow = await screen.findByRole('row', { name: /ScrapeBadger/ })
    const canaryTrigger = within(primaryRow).getByRole('button', { name: '付费试跑' })

    await browser.click(canaryTrigger)
    const dialog = screen.getByRole('dialog', { name: '付费试跑 ScrapeBadger' })
    expect(api.canaryApifyActorXProfileCandidate).not.toHaveBeenCalled()
    expect(within(dialog).getByRole('button', { name: '确认付费试跑' })).toBeDisabled()
    expect(within(dialog).queryByText('not-rendered')).not.toBeInTheDocument()

    await browser.click(await within(dialog).findByRole('button', { name: /试跑 X 来源/ }))
    await browser.click(await screen.findByRole('option', { name: 'X · @thsottiaux' }))
    await browser.click(within(dialog).getByRole('button', { name: '确认付费试跑' }))

    await waitFor(() => expect(api.canaryApifyActorXProfileCandidate).toHaveBeenCalledWith(
      'scrape-badger',
      'source-x-1',
      7,
      '确认付费试跑',
    ))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: '付费试跑 ScrapeBadger' })).not.toBeInTheDocument())
    await waitFor(() => expect(canaryTrigger).toHaveFocus())
  })

  it('keeps unsafe server details out of route action feedback', async () => {
    const browser = userEvent.setup()
    renderFeature({
      reorderApifyActorXProfileRoute: vi.fn().mockRejectedValue(new ApiError(502, {
        code: 'unexpected_upstream_failure',
        message: 'runId=unsafe-run datasetId=unsafe-dataset',
      })),
    })

    const primaryRow = await screen.findByRole('row', { name: /ScrapeBadger/ })
    await browser.click(within(primaryRow).getByRole('button', { name: '下移 ScrapeBadger' }))
    expect(await screen.findByText('Actor 顺序更新失败')).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('unsafe-run')
    expect(document.body.textContent).not.toContain('unsafe-dataset')
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
        settings={alertSettings()}
        onSave={onSave}
        onTest={vi.fn().mockResolvedValue({ sent: true, channel: 'webhook' })}
      />
    </DesignSystemProvider></MemoryRouter>)

    const destination = screen.getByLabelText('告警 Webhook 地址')
    expect(destination).toHaveAttribute('type', 'password')
    await browser.type(destination, 'https://example.invalid/actor-alert')
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))

    expect(onSave).toHaveBeenCalledWith({
      enabled: true,
      channel: 'webhook',
      events: alertSettings().events,
      webhook_url: 'https://example.invalid/actor-alert',
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

    await browser.click(screen.getByRole('checkbox', { name: '自动切换 Actor' }))
    await browser.click(screen.getByRole('button', { name: '保存运行告警' }))
    expect((await screen.findAllByText('Apify 运行告警设置保存失败，请稍后重试。')).length).toBeGreaterThan(0)
    expect(document.body.textContent).not.toContain('secret.invalid')
    expect(document.body.textContent).not.toContain('never-render')
  })
})
