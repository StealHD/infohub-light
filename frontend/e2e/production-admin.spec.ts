import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const owner = { id: 'owner-1', username: 'owner', display_name: '验收管理员', role: 'owner', enabled: true }
const notificationWebhookProviders = [{
  provider: 'generic_event',
  label: '通用事件 JSON',
  description: 'event/data',
  url_hint: 'https://example.com/webhook',
  signing: 'none',
  verification_mode: 'http_status',
}]

function notificationChannelStates({
  selected = 'webhook',
  emailAvailable = false,
  webhookConfigured = false,
  telegramAvailable = false,
}: {
  selected?: 'email' | 'webhook' | 'telegram'
  emailAvailable?: boolean
  webhookConfigured?: boolean
  telegramAvailable?: boolean
} = {}) {
  const base = {
    generation: 1,
    enabled_at: null,
    last_test_status: null,
    last_tested_at: null,
    last_test_error_code: null,
  }
  return {
    email: { ...base, enabled: selected === 'email', configured: false, available: emailAvailable },
    webhook: {
      ...base,
      enabled: selected === 'webhook',
      configured: webhookConfigured,
      available: true,
      provider: 'generic_event',
      provider_explicit: true,
      signing_secret_configured: false,
      verification_mode: 'http_status',
    },
    telegram: { ...base, enabled: selected === 'telegram', configured: false, available: telegramAvailable },
  }
}

const privateHistoryItems = [1, 2].map((index) => ({
  id: `private-history-${index}`,
  title: `私人研究源历史内容 ${index}`,
  url: `https://example.com/private-history-${index}`,
  source: '私人研究源',
  source_id: 'source-private',
  source_type: 'rss',
  summary_zh: '超过当前信息流窗口、仍保留在本地历史索引中的内容。',
  published_at: `2026-07-${11 - index}T08:00:00Z`,
  channel: 'AI',
  topics: ['研究'],
  user_state: { is_read: true, is_saved: false, is_later: false, dismissed: false },
}))

async function mockAdminApi(page: Page, authenticated = true, options: {
  includePrivateSource?: boolean
  includeXProfileSource?: boolean
  historicalTerminalJobs?: number
} = {}) {
  const healthWindowStart = new Date().toISOString()
  const healthFeedStart = new Date(Date.now() - 6 * 24 * 60 * 60 * 1000).toISOString()
  let quotaRequests = 0
  let feedJobsRequests = 0
  let allJobsRequests = 0
  let sourceHealthRequests = 0
  let productSubscribed = false
  let notificationEnabled = false
  let privateShared = false
  const notificationTargets = [{
    id: 'target-private-email',
    name: '我的收件箱',
    scope: 'private',
    channel: 'email',
    configured: true,
    enabled: true,
    available: true,
    transport_ready: true,
    config_generation: 1,
    activation_generation: 1,
    enabled_at: '2026-07-31T08:00:00Z',
    last_test_status: 'sent',
    last_tested_at: '2026-07-31T07:59:00Z',
    last_test_error_code: null,
    can_edit: true,
    can_test: true,
    can_enable: true,
    usage: {
      user_binding_count: 1,
      alert_binding_count: 0,
      preferred_active_delivery_count: 0,
      alert_active_delivery_count: 0,
    },
    updated_at: '2026-07-31T08:00:00Z',
  }, {
    id: 'target-shared-telegram',
    name: '工作区值班群',
    scope: 'shared',
    channel: 'telegram',
    configured: true,
    enabled: true,
    available: true,
    transport_ready: true,
    config_generation: 2,
    activation_generation: 1,
    enabled_at: '2026-07-31T08:00:00Z',
    last_test_status: 'sent',
    last_tested_at: '2026-07-31T07:59:00Z',
    last_test_error_code: null,
    can_edit: true,
    can_test: true,
    can_enable: true,
    usage: {
      user_binding_count: 0,
      alert_binding_count: 1,
      preferred_active_delivery_count: 0,
      alert_active_delivery_count: 0,
    },
    updated_at: '2026-07-31T08:00:00Z',
  }]
  const settingsActions: Array<{ action: string; payload: Record<string, unknown> }> = []
  let quotaRefreshGate: Promise<void> | null = null
  let releaseQuotaRefresh: (() => void) | null = null
  let sourceFetchGate: Promise<void> | null = null
  let releaseSourceFetch: (() => void) | null = null
  let youtubeCreated = false
  let youtubeKeepLatest = true
  const youtubeCreatePayloads: Array<Record<string, unknown>> = []
  const actorCanaryPayloads: Array<Record<string, unknown>> = []
  const actorOpsSupportProfiles = [
    { id: 'x/profile/items', route_key: 'x/profile', platform: 'x', target_type: 'profile', capability: 'items', mode: 'primary', label: 'X Profile' },
    { id: 'youtube/channel/items', route_key: 'youtube/channel/items', platform: 'youtube', target_type: 'channel', capability: 'items', mode: 'fallback', label: 'YouTube Channel' },
    { id: 'instagram/profile/items', route_key: 'instagram/profile/items', platform: 'instagram', target_type: 'profile', capability: 'items', mode: 'primary', label: 'Instagram Profile' },
  ]
  const actorOpsRevisions = [
    {
      revision_id: 'revision-primary',
      actor_id: 'publisher-a/primary',
      actor_public_name: 'Publisher A Primary',
      publisher: 'publisher-a',
      build_id: 'build-primary',
      build_number: '1.0.1',
      manifest_hash: 'a'.repeat(64),
      lifecycle: 'certified',
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
      lifecycle: 'certified',
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
      lifecycle: 'probationary',
      pricing: {
        model: 'PAY_PER_EVENT',
        billing_unit: 'event',
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
  const actorOpsRouteDetail = {
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
      { slot: 'primary', revision_id: actorOpsRevisions[0].revision_id, runnable: true, revision: actorOpsRevisions[0] },
      { slot: 'backup_1', revision_id: actorOpsRevisions[1].revision_id, runnable: true, revision: actorOpsRevisions[1] },
      { slot: 'backup_2', revision_id: actorOpsRevisions[2].revision_id, runnable: true, revision: actorOpsRevisions[2] },
    ],
    revisions: actorOpsRevisions,
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
        { slot: 'primary', revision_id: actorOpsRevisions[0].revision_id, revision: actorOpsRevisions[0] },
        { slot: 'backup_1', revision_id: actorOpsRevisions[1].revision_id, revision: actorOpsRevisions[1] },
        { slot: 'backup_2', revision_id: actorOpsRevisions[2].revision_id, revision: actorOpsRevisions[2] },
      ],
    },
    source_validations: [],
    source_validation_summary: { ready: 0, pending: 0, failed: 0 },
    replacement_needed: false,
  }
  const actorOpsRoutes = {
    schema_version: 1,
    generation: 7,
    support_profiles: actorOpsSupportProfiles,
    routes: [{
      route_id: actorOpsRouteDetail.route_id,
      route_key: actorOpsRouteDetail.route_key,
      platform: actorOpsRouteDetail.platform,
      target_type: actorOpsRouteDetail.target_type,
      capability: actorOpsRouteDetail.capability,
      mode: actorOpsRouteDetail.mode,
      generation: actorOpsRouteDetail.generation,
      support_status: actorOpsRouteDetail.support_status,
      runtime_status: actorOpsRouteDetail.runtime_status,
      runnable_slots: actorOpsRouteDetail.runnable_slots,
      required_slots: actorOpsRouteDetail.required_slots,
      min_runtime_healthy: actorOpsRouteDetail.min_runtime_healthy,
      publisher_count: actorOpsRouteDetail.publisher_count,
      per_run_cap_usd: actorOpsRouteDetail.per_run_cap_usd,
      discovery_run_id: null,
      blocked_reason: null,
      updated_at: actorOpsRouteDetail.updated_at,
    }],
  }
  let actorAlertSettings = {
    schema_version: 4,
    enabled: false,
    target_ids: ['target-shared-telegram'],
    selected_targets: [notificationTargets[1]],
    channels: ['webhook'],
    channel: 'webhook',
    channel_states: notificationChannelStates(),
    events: ['actor_switched', 'route_exhausted', 'quota_low', 'budget_blocked', 'start_outcome_unknown', 'recovered'],
    email_configured: false,
    email_transport_ready: false,
    webhook_configured: false,
    webhook_provider: 'generic_event',
    webhook_provider_explicit: true,
    webhook_signing_secret_configured: false,
    webhook_verification_mode: 'http_status',
    webhook_provider_options: notificationWebhookProviders,
    telegram_configured: false,
    telegram_transport_ready: false,
    last_test_status: null,
    last_tested_at: null,
    last_test_error_code: null,
    last_alert_status: null,
    last_alerted_at: null,
    last_alert_error_code: null,
    updated_at: null,
  }
  const actorRoute = {
    schema_version: 1,
    route: 'x/profile',
    generation: 3,
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
    limits: { per_run_usd: 0.02, per_job_usd: 0.06, failed_spend_6h_usd: 0.08 },
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
  }
  const configResponse = {
    config: {
      ai: { enabled: true, provider: 'gemini', model: 'gemini-3.5-flash', api_key_env: 'GOOGLE_API_KEY', base_url: '', languages: 'zh', analysis_content_chars: 8000, analysis_comments_chars: 4000, summary_max_chars: 240, analysis_max_output_tokens: 800 },
      feed_end_messages: { ai_generation_enabled: true, refresh_days: 7, style_preset: 'restrained', style_prompt: '', list_count: 12 },
      filtering: { ai_score_threshold: 6, homepage_min_score: 7, time_window_hours: 24, rss_initial_fetch_window_hours: 168, recent_item_limit: 200 },
      tags: ['AI Agent'],
    },
    taxonomy: { channels: ['AI', '产品机会', '其他'], topics: ['AI Agent', 'Codex'] },
  }
  await page.route(/^https?:\/\/[^/]+\/api\//, async (route) => {
    const url = new URL(route.request().url())
    let data: unknown

    if (url.pathname === '/api/auth/status') data = { authenticated, user: authenticated ? owner : null }
    else if (url.pathname === '/api/auth/login') data = { authenticated: true, user: owner }
    else if (url.pathname === '/api/catalog/sources/source-2/subscribe' && route.request().method() === 'POST') {
      productSubscribed = true
      data = {
        subscription: {
          id: 'subscription-2',
          user_id: owner.id,
          source_id: 'source-2',
          source_display_name: 'Product Notes',
          source_type: 'rss',
          enabled: true,
          analysis_mode: 'full',
          priority: 0,
        },
      }
    }
    else if (url.pathname === '/api/catalog/sources' && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as Record<string, unknown>
      youtubeCreatePayloads.push(payload)
      const config = payload.config as Record<string, unknown>
      if (config.url === '@Missing') {
        await route.fulfill({
          status: 404,
          contentType: 'application/json',
          body: JSON.stringify({
            ok: false,
            error: {
              code: 'youtube_channel_not_found',
              message: 'unsafe upstream detail',
              retryable: false,
            },
          }),
        })
        return
      }
      youtubeCreated = true
      youtubeKeepLatest = config.keep_latest_item !== false
      data = {
        id: 'source-youtube',
        type: 'rss',
        setup_type: 'youtube_channel',
        display_name: String(payload.display_name || 'Google Developers'),
        description: '',
        scope: 'public',
        default_channel: 'AI',
        default_topics: [],
        config: {
          url: 'https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv',
          keep_latest_item: youtubeKeepLatest,
        },
        enabled: true,
      }
    }
    else if (url.pathname === '/api/catalog/sources/source-youtube' && route.request().method() === 'PATCH') {
      const payload = route.request().postDataJSON() as { config?: Record<string, unknown> }
      youtubeKeepLatest = payload.config?.keep_latest_item !== false
      data = {
        id: 'source-youtube',
        type: 'rss',
        setup_type: 'youtube_channel',
        display_name: 'Google Developers',
        description: '',
        scope: 'public',
        default_channel: 'AI',
        default_topics: [],
        config: {
          url: 'https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv',
          keep_latest_item: youtubeKeepLatest,
        },
        enabled: true,
      }
    }
    else if (url.pathname === '/api/catalog/sources/source-youtube/subscribe' && route.request().method() === 'POST') {
      data = {
        subscription: {
          id: 'subscription-youtube',
          user_id: owner.id,
          source_id: 'source-youtube',
          source_display_name: 'Google Developers',
          source_type: 'rss',
          enabled: true,
          analysis_mode: 'full',
          priority: 0,
        },
      }
    }
    else if (url.pathname === '/api/catalog/sources/source-private/share' && route.request().method() === 'POST') {
      privateShared = true
      data = {
        source: { id: 'source-private', type: 'rss', display_name: '私人研究源', description: '仅本人维护', scope: 'public', owner_user_id: null, default_channel: 'AI', default_topics: ['研究'], enabled: true },
        notice: '管理权已交给工作区管理员。',
      }
    }
    else if (url.pathname === '/api/catalog/sources') data = { sources: [
      { id: 'source-1', type: 'rss', display_name: 'OpenAI Blog', description: '官方产品与研究动态', scope: 'workspace', default_channel: 'AI', default_topics: ['Codex'], enabled: true },
      { id: 'source-2', type: 'rss', display_name: 'Product Notes', description: '产品机会观察', scope: 'public', default_channel: '产品机会', default_topics: ['产品'], enabled: true },
      ...(options.includeXProfileSource ? [{
        id: 'source-x-profile',
        type: 'apify_social',
        display_name: 'X · @thsottiaux',
        description: 'X Profile',
        scope: 'workspace',
        default_channel: '社交动态',
        default_topics: [],
        config: { platform: 'x', kind: 'profile', target: 'not-rendered-by-actor-settings' },
        enabled: true,
      }] : []),
      ...(options.includePrivateSource ? [{ id: 'source-private', type: 'rss', display_name: '私人研究源', description: '仅本人维护', scope: privateShared ? 'public' : 'private', owner_user_id: privateShared ? null : owner.id, default_channel: 'AI', default_topics: ['研究'], enabled: true }] : []),
      ...(youtubeCreated ? [{
        id: 'source-youtube',
        type: 'rss',
        setup_type: 'youtube_channel',
        display_name: 'Google Developers',
        description: '',
        scope: 'public',
        default_channel: 'AI',
        default_topics: [],
        config: {
          url: 'https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv',
          keep_latest_item: youtubeKeepLatest,
        },
        enabled: true,
      }] : []),
    ] }
    else if (url.pathname === '/api/catalog/source-types') data = { source_types: [
      { type: 'rss', catalog_source_type: 'rss', label: 'RSS/Atom', fields: [{ name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '' }] },
      { type: 'youtube_channel', catalog_source_type: 'rss', label: 'YouTube 频道', fields: [
        { name: 'url', label: 'YouTube 频道地址或 @handle', input_type: 'text', required: true, default: null, help: '支持公开频道链接、@handle、频道 ID 或规范 Feed 地址。' },
        { name: 'keep_latest_item', label: '保留最新内容', input_type: 'boolean', required: false, default: true, help: '时间窗口为空时仅保留最近一条。' },
      ] },
    ] }
    else if (url.pathname === '/api/me/subscriptions/subscription-1' && route.request().method() === 'PATCH') {
      const payload = route.request().postDataJSON() as { notify_on_new_items?: boolean }
      if (typeof payload.notify_on_new_items === 'boolean') notificationEnabled = payload.notify_on_new_items
      data = { id: 'subscription-1', user_id: owner.id, source_id: 'source-1', source_display_name: 'OpenAI Blog', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 80, notify_on_new_items: notificationEnabled, schedule: { enabled: false, interval_minutes: 360, allowed_intervals: [60, 180, 360, 720, 1440] } }
    }
    else if (url.pathname === '/api/me/subscriptions') data = { subscriptions: [
      { id: 'subscription-1', user_id: owner.id, source_id: 'source-1', source_display_name: 'OpenAI Blog', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 80, notify_on_new_items: notificationEnabled, schedule: { enabled: false, interval_minutes: 360, allowed_intervals: [60, 180, 360, 720, 1440] } },
      ...(options.includePrivateSource ? [{ id: 'subscription-private', user_id: owner.id, source_id: 'source-private', source_display_name: '私人研究源', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 20, notify_on_new_items: false, schedule: { enabled: true, interval_minutes: 60, allowed_intervals: [30, 60, 180, 360, 720, 1440], next_run_at: '2026-07-17T10:30:00Z' } }] : []),
      ...(productSubscribed ? [{ id: 'subscription-2', user_id: owner.id, source_id: 'source-2', source_display_name: 'Product Notes', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 0 }] : []),
      ...(youtubeCreated ? [{ id: 'subscription-youtube', user_id: owner.id, source_id: 'source-youtube', source_display_name: 'Google Developers', source_type: 'rss', enabled: true, analysis_mode: 'full', priority: 0 }] : []),
    ] }
    else if (url.pathname === '/api/me/source-health') {
      sourceHealthRequests += 1
      data = {
        schema_version: 1,
        scope: 'user',
        window: {
        timezone: 'Asia/Shanghai',
        feed_days: 7,
        today_start: healthWindowStart,
        feed_start: healthFeedStart,
        },
        summary: { total: options.includePrivateSource ? 2 : 1, healthy: options.includePrivateSource ? 2 : 1, degraded: 0, failing: 0, unknown: 0 },
        items: [
          { subscription_id: 'subscription-1', source_id: 'source-1', source_display_name: 'OpenAI Blog', source_type: 'rss', status: 'healthy', consecutive_failures: 0, last_fetched_count: 7, today_item_count: 0, feed_item_count: 0, current_item_count: 0, history_item_count: 7 },
          ...(options.includePrivateSource
            ? [{ subscription_id: 'subscription-private', source_id: 'source-private', source_display_name: '私人研究源', source_type: 'rss', status: 'healthy', consecutive_failures: 0, last_fetched_count: 2, today_item_count: 0, feed_item_count: 0, current_item_count: 0, history_item_count: 2 }]
            : []),
        ],
      }
    }
    else if (url.pathname === '/api/feed/history') data = {
      schema_version: 2,
      scope: 'user',
      items: url.searchParams.get('source_id') === 'source-private' ? privateHistoryItems : [],
      featured_items: [],
      item_count: url.searchParams.get('source_id') === 'source-private' ? 2 : 0,
      total_count: url.searchParams.get('source_id') === 'source-private' ? 2 : 0,
      limit: Number(url.searchParams.get('limit') || '50'),
      offset: Number(url.searchParams.get('offset') || '0'),
      has_more: false,
      snapshots: [],
    }
    else if (url.pathname === '/api/me/feed-schedule') data = { schema_version: 1, enabled: true, interval_minutes: 360, allowed_intervals: [60, 180, 360, 720, 1440], worker_status: 'ready', next_run_at: '2026-07-17T12:00:00Z' }
    else if (url.pathname === '/api/feed/end-messages') data = {
      schema_version: 1,
      source: 'builtin',
      status: 'disabled',
      generation: 0,
      generated_at: null,
      last_attempt_at: null,
      next_refresh_at: null,
      retry_at: null,
      last_error_code: null,
      scenes: { empty: ['这里暂时很安静。'], first_end: ['这一轮内容先到这里。'], repeat_end: ['又到末尾了。'] },
    }
    else if (url.pathname === '/api/feed/ignored') data = {
      schema_version: 1,
      scope: 'user',
      items: [],
      item_count: 0,
      limit: 200,
      offset: 0,
    }
    else if (url.pathname === '/api/me/notification-settings') data = {
      schema_version: 4,
      enabled: false,
      target_ids: ['target-private-email'],
      selected_targets: [notificationTargets[0]],
      channels: ['webhook'],
      channel: 'webhook',
      channel_states: notificationChannelStates(),
      email_configured: false,
      email_transport_ready: false,
      webhook_configured: false,
      webhook_provider: 'generic_event',
      webhook_provider_explicit: true,
      webhook_signing_secret_configured: false,
      webhook_verification_mode: 'http_status',
      webhook_provider_options: notificationWebhookProviders,
      telegram_configured: false,
      telegram_transport_ready: false,
      last_test_status: null,
      last_tested_at: null,
      last_test_error_code: null,
      updated_at: null,
    }
    else if (url.pathname === '/api/notification-targets') data = {
      schema_version: 1,
      targets: notificationTargets,
      webhook_provider_options: notificationWebhookProviders,
    }
    else if (url.pathname === '/api/notification-services') data = {
      schema_version: 1,
      services: notificationTargets.map((target) => ({
        ...target,
        legacy_private: target.scope === 'private',
        can_validate: target.scope === 'shared',
      })),
      channel_credentials: {
        email: {
          configured: false,
          ready: false,
          generation: 0,
          provider: null,
          sender_name: 'Inteliscope',
          region: null,
          sender_email_configured: false,
          smtp_username_configured: false,
          providers: [
            { provider: 'qq', label: 'QQ 邮箱', credential_label: 'SMTP 授权码', sender_hint: '填写完整 QQ 邮箱地址', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
            { provider: 'netease', label: '网易邮箱', credential_label: 'SMTP 授权码', sender_hint: '支持 163、126 与 yeah.net', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
            { provider: 'gmail', label: 'Gmail', credential_label: 'App Password', sender_hint: '填写完整邮箱地址', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
            { provider: 'resend', label: 'Resend', credential_label: 'API Key', sender_hint: '使用已验证域名', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
            { provider: 'amazon_ses', label: 'Amazon SES', credential_label: 'SES SMTP Password', sender_hint: '使用已验证地址', requires_region: true, requires_smtp_username: true, smtp_port: 465, security: 'ssl' },
          ],
        },
        telegram: { configured: false, ready: false, generation: 0 },
        webhook: { configured: true, ready: true, generation: 0 },
      },
      webhook_provider_options: notificationWebhookProviders,
      can_manage: true,
    }
    else if (url.pathname === '/api/me/notification-settings/test') {
      const payload = route.request().postDataJSON() as { channel?: string }
      data = { sent: true, channel: payload.channel ?? 'webhook' }
    }
    else if (url.pathname === '/api/jobs/source-fetch' && route.request().method() === 'POST') {
      if (sourceFetchGate) {
        await sourceFetchGate
        sourceFetchGate = null
        releaseSourceFetch = null
      }
      data = { id: 'job-source-pending', user_id: owner.id, job_type: 'source_fetch', source_id: 'source-1', subscription_id: 'subscription-1', status: 'queued', created_at: '2026-07-17T08:10:00Z' }
    }
    else if (url.pathname === '/api/jobs/job-1') data = {
      id: 'job-1',
      user_id: owner.id,
      job_type: 'source_fetch',
      source_id: 'source-1',
      subscription_id: 'subscription-1',
      status: 'succeeded',
      created_at: '2026-07-17T08:00:00Z',
      finished_at: '2026-07-17T08:00:02Z',
      payload: { source_id: 'source-1', subscription_id: 'subscription-1' },
      result: {
        item_count: 7,
        response_schemas: [{
          source_id: 'source-1',
          catalog_type: 'rss',
          capture_status: 'captured',
          upstream: { root_type: 'object', fields: [], truncated: false },
          normalized: { root_type: 'array', fields: [], truncated: false },
        }],
      },
    }
    else if (url.pathname === '/api/jobs') {
      const requestedJobTypes = url.searchParams.getAll('job_type').sort()
      const feedActivityRequest = (
        url.searchParams.get('limit') === '20'
        && requestedJobTypes.join(',') === 'source_fetch,user_feed_refresh'
      )
      if (feedActivityRequest) feedJobsRequests += 1
      else allJobsRequests += 1
      const terminalJobs = options.historicalTerminalJobs
        ? Array.from({ length: options.historicalTerminalJobs }, (_, index) => ({
          id: `historical-job-${index + 1}`,
          user_id: owner.id,
          job_type: 'source_fetch',
          source_id: 'source-1',
          subscription_id: 'subscription-1',
          status: 'succeeded',
          created_at: `2026-07-17T07:${String(59 - (index % 60)).padStart(2, '0')}:00Z`,
          finished_at: `2026-07-17T08:${String(index % 60).padStart(2, '0')}:02Z`,
          result: { item_count: index % 3 },
        }))
        : [{ id: 'job-1', user_id: owner.id, job_type: 'source_fetch', source_id: 'source-1', subscription_id: 'subscription-1', status: 'succeeded', created_at: '2026-07-17T08:00:00Z', finished_at: '2026-07-17T08:00:02Z', result: { item_count: 7 } }]
      data = {
        jobs: terminalJobs.slice(0, Number(url.searchParams.get('limit') || terminalJobs.length)),
      }
    }
    else if (url.pathname === '/api/me/agent-delegations') data = {
      enabled: true,
      mcp_url: 'https://example.test/mcp',
      subscription_writes_enabled: false,
      openclaw_chat: { enabled: false, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.7.1' },
      token_ttl_days: 90,
      max_active: 5,
      connections: [{ id: 'agent-1', name: '本机 OpenClaw', client_type: 'openclaw', access: 'read', scopes: ['inteliscope:read'], token_prefix: 'ih_mcp_v1_demo', created_at: '2026-07-01T00:00:00Z', expires_at: '2026-10-01T00:00:00Z', last_used_at: null, revoked_at: null, status: 'active' }],
    }
    else if (url.pathname === '/api/admin/storage/summary') data = {
      schema_version: 1,
      policy: { feed_snapshot_days: 30, feed_snapshot_per_user: 20, source_snapshot_days: 7, completed_job_days: 14, analysis_cache_days: 30, usage_event_days: 90, archive_after_days: 90, automatic_permanent_delete: false },
      bytes: { database: 1024, media: 0, archives: 0 },
      counts: { content_total: 0, content_online: 0, content_archived: 0, feed_snapshots: 0, source_snapshots: 0, media_assets: 0, archive_batches: 0 },
      readiness: { feed_storage_v3: true, content_timeline_v11: true, ready: true },
      last_cleanup_at: null,
    }
    else if (url.pathname === '/api/admin/storage/archives') data = { schema_version: 1, archives: [] }
    else if (url.pathname === '/api/config/action' && route.request().method() === 'POST') {
      settingsActions.push(route.request().postDataJSON() as { action: string; payload: Record<string, unknown> })
      data = configResponse
    }
    else if (url.pathname === '/api/config') data = configResponse
    else if (url.pathname === '/api/admin/secrets' && route.request().method() === 'POST') data = {
      id: 'secret-created',
      name: 'DeepSeek Primary',
      kind: 'ai',
      provider: 'deepseek',
      env_name: 'DEEPSEEK_API_KEY',
      is_set: true,
      used_by: [],
    }
    else if (url.pathname === '/api/admin/secrets') data = { secrets: [
      { id: 'secret-1', name: 'Gemini Primary', kind: 'ai', provider: 'gemini', env_name: 'GOOGLE_API_KEY', is_set: true, used_by: [{ type: 'ai', id: 'primary', name: 'AI 分析' }] },
      { id: 'secret-apify', name: 'Apify Primary', kind: 'apify', provider: 'apify', env_name: 'APIFY_PRIMARY_WORKSPACE_TOKEN', is_set: true, used_by: [] },
    ] }
    else if (url.pathname === '/api/admin/notification-email-transport') data = {
      schema_version: 1,
      configured: false,
      provider: null,
      sender_email: null,
      sender_name: 'Inteliscope',
      region: null,
      smtp_username: null,
      enabled: false,
      credential_configured: false,
      generation: 0,
      last_test_status: null,
      last_test_generation: null,
      last_tested_at: null,
      last_test_error_code: null,
      can_enable: false,
      ready: false,
      connection: null,
      providers: [
        { provider: 'qq', label: 'QQ 邮箱', credential_label: 'SMTP 授权码', sender_hint: '填写完整 QQ 邮箱地址', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
        { provider: 'netease', label: '网易邮箱', credential_label: 'SMTP 授权码', sender_hint: '支持 163、126 与 yeah.net', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
        { provider: 'gmail', label: 'Gmail', credential_label: 'App Password', sender_hint: '填写完整邮箱地址', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
        { provider: 'resend', label: 'Resend', credential_label: 'API Key', sender_hint: '使用已验证域名', requires_region: false, requires_smtp_username: false, smtp_port: 465, security: 'ssl' },
        { provider: 'amazon_ses', label: 'Amazon SES', credential_label: 'SES SMTP Password', sender_hint: '使用已验证地址', requires_region: true, requires_smtp_username: true, smtp_port: 465, security: 'ssl' },
      ],
      updated_at: null,
    }
    else if (url.pathname === '/api/admin/notification-telegram-transport/test') data = {
      sent: true,
      generation: 1,
    }
    else if (url.pathname === '/api/admin/notification-telegram-transport') data = {
      schema_version: 1,
      configured: false,
      enabled: false,
      token_configured: false,
      generation: 0,
      last_test_status: null,
      last_test_generation: null,
      last_tested_at: null,
      last_test_error_code: null,
      can_enable: false,
      ready: false,
      updated_at: null,
    }
    else if (url.pathname === '/api/catalog/source-capabilities') data = {
      schema_version: 1,
      generation: 7,
      support_profiles: actorOpsSupportProfiles,
      capabilities: [],
    }
    else if (url.pathname === '/api/admin/apify-routes') data = actorOpsRoutes
    else if (url.pathname === '/api/admin/apify-routes/route-x-profile') data = actorOpsRouteDetail
    else if (url.pathname === '/api/admin/apify-discovery-settings') data = {
      schema_version: 4,
      generation: 1,
      enabled: false,
      ai_config_id: 'global-ai-gemini-secondary',
      ai_options: [{
        id: 'global-ai-gemini-secondary',
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
    }
    else if (url.pathname === '/api/admin/apify-actor-routes/x/profile/order' && route.request().method() === 'PUT') {
      data = actorRoute
    }
    else if (
      url.pathname.startsWith('/api/admin/apify-actor-routes/x/profile/candidates/')
      && route.request().method() === 'POST'
    ) {
      if (url.pathname.endsWith('/canary')) {
        actorCanaryPayloads.push(route.request().postDataJSON() as Record<string, unknown>)
      }
      data = actorRoute
    }
    else if (url.pathname === '/api/admin/apify-actor-routes/x/profile') data = actorRoute
    else if (url.pathname === '/api/admin/apify-actor-alert-settings/test' && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON() as { channel?: string }
      data = { sent: true, channel: payload.channel ?? actorAlertSettings.channel }
    }
    else if (url.pathname === '/api/admin/apify-actor-alert-settings' && route.request().method() === 'PATCH') {
      const patch = route.request().postDataJSON() as Record<string, unknown>
      actorAlertSettings = {
        ...actorAlertSettings,
        enabled: typeof patch.enabled === 'boolean' ? patch.enabled : actorAlertSettings.enabled,
        target_ids: Array.isArray(patch.target_ids) ? patch.target_ids as string[] : actorAlertSettings.target_ids,
        selected_targets: Array.isArray(patch.target_ids)
          ? notificationTargets.filter((target) => (patch.target_ids as string[]).includes(target.id))
          : actorAlertSettings.selected_targets,
        channels: Array.isArray(patch.channels) ? patch.channels as string[] : actorAlertSettings.channels,
        events: Array.isArray(patch.events) ? patch.events as string[] : actorAlertSettings.events,
        email_configured: typeof patch.email_address === 'string' || actorAlertSettings.email_configured,
        webhook_configured: typeof patch.webhook_url === 'string' || actorAlertSettings.webhook_configured,
      }
      data = actorAlertSettings
    }
    else if (url.pathname === '/api/admin/apify-actor-alert-settings') data = actorAlertSettings
    else if (url.pathname === '/api/admin/apify-actor-alert-incidents') data = {
      schema_version: 3,
      incidents: [{
        id: 'actor-incident-1',
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
        deliveries: [{
          event_type: 'actor_switched',
          target_id: 'target-shared-telegram',
          target_name: '工作区值班群',
          channel: 'telegram',
          status: 'sent',
          error_code: null,
          created_at: '2026-07-29T08:00:01Z',
          started_at: '2026-07-29T08:00:01Z',
          sent_at: '2026-07-29T08:00:02Z',
          updated_at: '2026-07-29T08:00:02Z',
        }],
        delivery_status: 'sent',
        delivery_error_code: null,
      }],
    }
    else if (url.pathname === '/api/admin/apify-key-pool') data = {
      schema_version: 1,
      enabled: false,
      generation: 1,
      status: 'ready',
      active_secret_id: 'secret-apify',
      draining_secret_id: null,
      blocked_reason: null,
      retry_at: null,
      members: [{
        secret_id: 'secret-apify',
        position: 0,
        status: 'active',
        blocked_until: null,
        cycle_end_at: '2026-07-31T23:59:59.999Z',
        last_checked_at: '2026-07-23T08:30:00+00:00',
        last_error_code: null,
        active_run_count: 0,
      }],
    }
    else if (url.pathname === '/api/admin/secrets/secret-apify/quota') {
      quotaRequests += 1
      if (quotaRequests > 1 && quotaRefreshGate) {
        await quotaRefreshGate
        quotaRefreshGate = null
        releaseQuotaRefresh = null
      }
      data = {
        secret_id: 'secret-apify',
        provider: 'apify',
        currency: 'USD',
        cycle_start_at: '2026-07-01T00:00:00.000Z',
        cycle_end_at: '2026-07-31T23:59:59.999Z',
        checked_at: '2026-07-23T08:30:00+00:00',
        monthly_included_credits_usd: 49,
        monthly_usage_usd: 12.5,
        remaining_included_credits_usd: 36.5,
        max_monthly_usage_usd: 100,
        remaining_hard_limit_usd: 87.5,
      }
    }
    else if (url.pathname === '/api/users') data = { users: [owner] }
    else {
      await route.fulfill({ status: 404, contentType: 'application/json', body: JSON.stringify({ ok: false, error: { code: 'not_found', message: url.pathname } }) })
      return
    }

    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, data }) })
  })
  return {
    quotaRequests: () => quotaRequests,
    requestCounts: () => ({
      feedJobs: feedJobsRequests,
      allJobs: allJobsRequests,
      sourceHealth: sourceHealthRequests,
    }),
    settingsActions: () => settingsActions,
    deferQuotaRefresh: () => {
      quotaRefreshGate ??= new Promise<void>((resolve) => {
        releaseQuotaRefresh = resolve
      })
    },
    releaseQuotaRefresh: () => releaseQuotaRefresh?.(),
    deferSourceFetch: () => {
      sourceFetchGate ??= new Promise<void>((resolve) => {
        releaseSourceFetch = resolve
      })
    },
    releaseSourceFetch: () => releaseSourceFetch?.(),
    youtubeCreatePayloads: () => youtubeCreatePayloads,
    actorCanaryPayloads: () => actorCanaryPayloads,
  }
}

async function expectHeroAdminPage(page: Page, heading: string, { agentAvailable = false } = {}) {
  await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
  await expect(page.locator('h1')).toHaveCount(1)
  await expect(page.locator('[data-page-frame="admin"]')).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByRole('complementary', { name: 'OpenClaw 上下文' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /Agent 面板/ })).toHaveCount(agentAvailable ? 1 : 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
}

test('production administration routes use the adaptive Quiet Studio page pattern at every acceptance viewport', async ({ page }) => {
  test.setTimeout(60_000)
  await mockAdminApi(page)

  await page.goto('/subscriptions')
  await expectHeroAdminPage(page, '订阅与来源', { agentAvailable: true })
  await expect(page.getByRole('tab')).toHaveCount(3)

  await page.goto('/agents')
  await expectHeroAdminPage(page, '助手连接')
  await expect(page.getByText('本机 OpenClaw')).toBeVisible()
  const connectionMore = page.getByRole('button', { name: '更多操作：本机 OpenClaw' })
  await expect(connectionMore).toBeVisible()
  await expect(page.getByRole('button', { name: '吊销 本机 OpenClaw' })).toHaveCount(0)
  await connectionMore.click()
  const connectionActions = page.getByRole('dialog', { name: '本机 OpenClaw 连接操作' })
  await expect(connectionActions.getByRole('button', { name: '复制配置' })).toBeVisible()
  await expect(connectionActions.getByRole('button', { name: '重命名' })).toBeVisible()
  const revokeAction = connectionActions.getByRole('button', { name: '吊销连接' })
  await expect(revokeAction).toBeVisible()
  await expect(revokeAction).not.toHaveClass(/bg-danger/)
  await revokeAction.click()
  const revokeDialog = page.getByRole('dialog', { name: '吊销助手连接' })
  await expect(revokeDialog.getByRole('button', { name: '确认吊销' })).toBeVisible()
  await revokeDialog.getByRole('button', { name: '取消' }).click()
  await expect(connectionMore).toBeFocused()
  const openClawConfigurations = page.locator('pre[aria-label$="OpenClaw 配置命令"]')
  await expect(openClawConfigurations).toHaveCount(2)
  const configurationMetrics = await openClawConfigurations.evaluateAll((blocks) => blocks.map((block) => ({
    top: block.getBoundingClientRect().top,
    clientWidth: block.clientWidth,
    scrollWidth: block.scrollWidth,
    overflowX: getComputedStyle(block).overflowX,
  })))
  if ((page.viewportSize()?.width ?? 0) >= 900) {
    expect(Math.abs(configurationMetrics[0].top - configurationMetrics[1].top)).toBeLessThanOrEqual(1)
  } else {
    expect(configurationMetrics[1].top).toBeGreaterThan(configurationMetrics[0].top)
  }
  expect(configurationMetrics.every(({ clientWidth, scrollWidth }) => scrollWidth <= clientWidth)).toBe(true)
  expect(configurationMetrics.every(({ overflowX }) => overflowX === 'hidden')).toBe(true)

  await page.goto('/settings#settings-notifications')
  await expect(page.getByRole('heading', { name: '通知', exact: true, level: 1 })).toBeVisible()
  await expect(page.locator('[data-settings-workspace]')).toBeVisible()
  await expect(page.locator('[data-page-frame="settings"]')).toBeVisible()
  await expect(page.getByTestId('live-workbench-shell')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '通知服务', exact: true })).toBeVisible()
  await expect(page.getByRole('grid', { name: '通知服务列表' })).toBeVisible()
  await expect(page.getByRole('grid', { name: '通知服务列表' }).getByText('我的收件箱', { exact: true })).toBeVisible()
  await expect(page.getByRole('grid', { name: '通知服务列表' }).getByText('工作区值班群', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '新增通知服务' })).toBeVisible()
  await expect(page.getByText('发送基础服务', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: /发送.*测试/ })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '助手与 AI' })).toHaveCount(0)

  await page.goto('/settings#settings-ai')
  await expect(page).toHaveURL(/\/settings\/ai$/)
  await expect(page.getByRole('heading', { name: 'AI', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: '助手连接', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '工作区 AI', exact: true })).toBeVisible()
  const aiDisclosure = page.getByRole('button', { name: /高级配置/ })
  await expect(aiDisclosure).toHaveAttribute('aria-expanded', 'false')
  await expect(page.getByLabel('Base URL')).toBeHidden()
  await aiDisclosure.click()
  await expect(page.getByLabel('Base URL')).toBeVisible()
  await page.getByLabel('Base URL').fill('https://ai.example.test/v1')
  await aiDisclosure.click()
  await aiDisclosure.click()
  await expect(page.getByLabel('Base URL')).toHaveValue('https://ai.example.test/v1')
  await expect(page.getByTestId('live-workbench-shell')).toHaveCount(0)

  await page.goto('/settings#settings-ignored')
  await expect(page).toHaveURL(/\/settings\/ignored$/)
  await expect(page.getByRole('heading', { name: '已忽略内容', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByText('暂无已忽略内容', { exact: true })).toBeVisible()
  await page.goto('/settings#settings-fetching')
  await expect(page).toHaveURL(/\/settings\/fetching$/)
  await expect(page.getByRole('heading', { name: '获取与主题' })).toBeVisible()
  await expect(page.getByLabel('日常抓取窗口（小时）')).toHaveValue('24')
  const initialRssWindow = page.getByRole('button', { name: /RSS 首次抓取窗口/ })
  await expect(initialRssWindow).toContainText('7 天')
  await initialRssWindow.click()
  await expect(page.getByRole('option', { name: '7 天' })).toBeVisible()
  await expect(page.getByRole('option', { name: '30 天' })).toBeVisible()
  await page.getByRole('option', { name: '30 天' }).click()
  await expect(initialRssWindow).toContainText('30 天')
  const settingsNavigationButton = page.getByRole('button', { name: '打开设置导航' })
  if ((page.viewportSize()?.width ?? 0) < 768) {
    await expect(settingsNavigationButton).toBeVisible()
    await settingsNavigationButton.click()
    await expect(page.getByRole('link', { name: '密钥' })).toBeVisible()
  } else {
    await expect(page.getByRole('link', { name: '密钥' })).toBeVisible()
    await expect(settingsNavigationButton).toBeHidden()
    await expect(page.getByRole('navigation', { name: '设置导航' })).toBeVisible()
    await expect(page.getByRole('link', { name: '获取与主题' })).toHaveAttribute('aria-current', 'page')
  }

  await page.goto('/users')
  await expectHeroAdminPage(page, '账户与成员')
  await expect(page.getByRole('heading', { name: '账户安全' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '成员管理' })).toBeVisible()

  await page.goto('/manual')
  await expectHeroAdminPage(page, '操作手册')
  await expect(page.getByRole('heading', { name: '快速开始' })).toBeVisible()
  await expect(page.getByText(/每次产品代码合并都由 Test Gate 检查/)).toBeVisible()
})

test('settings landing defers hidden section requests and a direct hash loads only that section', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One real browser project is enough for request activation coverage.')
  const requests: Array<{ method: string; pathname: string }> = []
  page.on('request', (request) => {
    const url = new URL(request.url())
    if (url.pathname.startsWith('/api/')) {
      requests.push({ method: request.method(), pathname: url.pathname })
    }
  })
  await mockAdminApi(page)

  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '概览', level: 1 })).toBeVisible()
  await expect(page.getByText('操作手册', { exact: true })).toBeVisible()
  await page.waitForTimeout(250)

  const sectionQueryPaths = new Set([
    '/api/config',
    '/api/feed/end-messages',
    '/api/feed/ignored',
    '/api/me/notification-settings',
    '/api/notification-targets',
    '/api/notification-services',
    '/api/admin/notification-email-transport',
    '/api/admin/notification-telegram-transport',
    '/api/admin/storage/summary',
    '/api/admin/storage/archives',
    '/api/admin/secrets',
    '/api/admin/apify-key-pool',
    '/api/admin/apify-actor-routes/x/profile',
    '/api/admin/apify-actor-alert-settings',
    '/api/admin/apify-actor-alert-incidents',
  ])
  expect(requests.filter(({ method, pathname }) => (
    method === 'GET'
    && (sectionQueryPaths.has(pathname) || pathname.endsWith('/quota'))
  ))).toEqual([])

  const directAiStart = requests.length
  await page.goto('/settings#settings-ai')
  await expect(page).toHaveURL(/\/settings\/ai$/)
  await expect(page.getByRole('heading', { name: '工作区 AI', exact: true })).toBeVisible()
  const directAiRequests = requests.slice(directAiStart)
    .filter(({ method }) => method === 'GET')
    .map(({ pathname }) => pathname)
  expect(directAiRequests).toEqual(expect.arrayContaining([
    '/api/config',
    '/api/admin/secrets',
    '/api/feed/end-messages',
  ]))
  expect(directAiRequests.filter((pathname) => (
    sectionQueryPaths.has(pathname)
    && !['/api/config', '/api/admin/secrets', '/api/feed/end-messages'].includes(pathname)
  ))).toEqual([])

  const directHashStart = requests.length
  await page.goto('/settings#settings-secrets')
  await expect(page.getByText('套餐剩余 $36.50')).toBeVisible()
  const directHashRequests = requests.slice(directHashStart)
    .filter(({ method }) => method === 'GET')
    .map(({ pathname }) => pathname)
  const secretsRequestCount = directHashRequests.filter((pathname) => pathname === '/api/admin/secrets').length
  expect(secretsRequestCount).toBeGreaterThanOrEqual(1)
  expect(secretsRequestCount).toBeLessThanOrEqual(2)
  const poolRequestCount = directHashRequests.filter((pathname) => pathname === '/api/admin/apify-key-pool').length
  expect(poolRequestCount).toBeGreaterThanOrEqual(1)
  expect(poolRequestCount).toBeLessThanOrEqual(2)
  expect(directHashRequests.filter((pathname) => pathname.endsWith('/quota'))).toHaveLength(1)
  expect(directHashRequests.filter((pathname) => (
    sectionQueryPaths.has(pathname)
    && ![
      '/api/admin/secrets',
      '/api/admin/apify-key-pool',
    ].includes(pathname)
  ))).toEqual([])

  const storageHashStart = requests.length
  await page.goto('/settings/legacy#settings-storage')
  await expect(page).toHaveURL(/\/settings\/storage$/)
  await expect(page.locator('[data-settings-page="storage"]')).toBeVisible()
  await expect(page.getByRole('heading', { name: '存储与归档', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByRole('heading', { name: '存储概览', exact: true })).toBeVisible()
  await expect(page.getByText('尚无归档批次。', { exact: true })).toBeVisible()
  const storageRequests = requests.slice(storageHashStart)
    .filter(({ method }) => method === 'GET')
    .map(({ pathname }) => pathname)
  expect(storageRequests).toEqual(expect.arrayContaining([
    '/api/admin/storage/summary',
    '/api/admin/storage/archives',
  ]))
  expect(storageRequests.filter((pathname) => (
    sectionQueryPaths.has(pathname)
    && !['/api/admin/storage/summary', '/api/admin/storage/archives'].includes(pathname)
  ))).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const storageAccessibility = await new AxeBuilder({ page }).analyze()
  expect(storageAccessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('settings mobile drawer navigates native pages and keeps the workspace bounded', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', 'The full-height settings drawer is specific to mobile.')
  await mockAdminApi(page)
  await page.goto('/settings')

  await expect(page.getByRole('heading', { name: '概览', level: 1 })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '设置导航' })).toBeHidden()
  await page.getByRole('button', { name: '打开设置导航' }).click()
  const drawer = page.getByRole('dialog', { name: '设置导航' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByRole('link', { name: '已忽略内容' })).toBeVisible()
  await drawer.getByRole('link', { name: '外观' }).click()
  await expect(page).toHaveURL(/\/settings\/appearance$/)
  await expect(page.getByRole('heading', { name: '外观', level: 1 })).toBeVisible()
  await expect(drawer).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
})

test('settings workspace stays responsive and theme-safe at acceptance widths', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One browser can cover the explicit Settings workspace widths.')
  await mockAdminApi(page)

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 580, height: 844 },
    { width: 768, height: 900 },
    { width: 1024, height: 768 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: '概览', level: 1 })).toBeVisible()
    await expect(page.locator('[data-settings-workspace]')).toBeVisible()
    await expect(page.getByTestId('live-workbench-shell')).toHaveCount(0)
    if (viewport.width < 768) {
      await expect(page.getByRole('button', { name: '打开设置导航' })).toBeVisible()
      await expect(page.getByRole('navigation', { name: '设置导航' })).toBeHidden()
    } else {
      await expect(page.getByRole('navigation', { name: '设置导航' })).toBeVisible()
      const sidebarBounds = await page.getByRole('complementary', { name: '设置侧栏' }).boundingBox()
      expect(Math.round(sidebarBounds?.width ?? 0)).toBe(232)
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }

  await page.getByRole('button', { name: '切换到白天模式' }).click()
  await expect(page.locator('[data-ui-system="heroui"]')).toHaveAttribute('data-theme', 'light')
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('settings saves all dirty core sections in one bundle request', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'The atomic settings coordinator only needs one browser project.')
  const apiState = await mockAdminApi(page)
  await page.goto('/settings/fetching')

  const initialWindow = page.getByRole('button', { name: /RSS 首次抓取窗口/ })
  await initialWindow.click()
  await page.getByRole('option', { name: '30 天' }).click()
  const rsshub = page.getByRole('textbox', { name: 'RSSHub Base URL' })
  await rsshub.fill('https://rsshub.example.com/private')

  await expect(page.getByText(/2 项设置待保存/)).toBeVisible()
  const bundleRequest = page.waitForRequest((request) => {
    const url = new URL(request.url())
    return url.pathname === '/api/config/action' && request.method() === 'POST'
  })
  await page.getByRole('button', { name: '保存全部配置' }).click()
  const request = await bundleRequest
  expect(request.postDataJSON()).toEqual({
    action: 'set_settings_bundle',
    payload: {
      rsshub: { base_url: 'https://rsshub.example.com/private' },
      filtering: expect.objectContaining({
        time_window_hours: 24,
        rss_initial_fetch_window_hours: 720,
        recent_item_limit: 200,
      }),
    },
  })
  await expect(page.getByText('全部配置已保存', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存全部配置' })).toHaveCount(0)
  expect(apiState.settingsActions()).toHaveLength(1)

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('unified notification services stay bounded at 390, 580, 768 and 1440 pixels', async ({ page }) => {
  await mockAdminApi(page)

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 580, height: 844 },
    { width: 768, height: 900 },
    { width: 1440, height: 900 },
  ]) {
    await page.setViewportSize(viewport)
    await page.goto('/settings#settings-notifications')

    await expect(page.getByRole('heading', { name: '通知服务', exact: true })).toBeVisible()
    await expect(page.getByRole('grid', { name: '通知服务列表' })).toBeVisible()
    await page.getByRole('button', { name: '新增通知服务' }).click()
    await expect(page.getByRole('dialog', { name: '新增通知服务' })).toBeVisible()
    await expect(page.getByText('发送基础服务', { exact: true })).toHaveCount(0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

    await page.getByRole('combobox', { name: '发送方式' }).selectOption('email')
    await page.getByRole('combobox', { name: '邮件服务商' }).selectOption('amazon_ses')
    await expect(page.getByLabel('Amazon SES Region')).toBeVisible()
    await expect(page.getByLabel('SES SMTP 用户名')).toBeVisible()
    await expect(page.getByLabel('SES SMTP Password')).toHaveAttribute('type', 'password')
    await page.getByRole('combobox', { name: '发送方式' }).selectOption('telegram')
    await expect(page.getByLabel('群组或会话 Chat ID')).toHaveAttribute('type', 'password')
    await expect(page.getByLabel('Bot Token')).toHaveAttribute('type', 'password')
    await expect(page.getByRole('button', { name: '保存并测试' })).toBeDisabled()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  }
})

test('ActorOps route control plane stays safe and bounded across settings layouts', async ({ page }, testInfo) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockAdminApi(page, true, { includeXProfileSource: true })
  await page.goto('/settings/legacy#settings-actorops')

  await expect(page).toHaveURL(/\/settings\/actorops$/)
  await expect(page.getByRole('heading', { name: 'ActorOps', exact: true, level: 1 })).toBeVisible()
  await expect(page.getByText('ActorOps 路由控制面', { exact: true })).toBeVisible()
  if (testInfo.project.name === 'mobile') {
    await expect(page.getByLabel('ActorOps 路由列表（移动端）')).toBeVisible()
  } else {
    await expect(page.getByRole('grid', { name: 'ActorOps 路由列表' })).toBeVisible()
  }
  await expect(page.getByRole('list', { name: '当前 Actor 主备方案' })).toBeVisible()
  await expect(page.getByText('Actor Discovery AI 设置', { exact: true })).toBeVisible()
  await expect(page.getByText('故障告警', { exact: true })).toBeVisible()
  await expect(page.getByRole('switch', { name: '启用 Apify 运行告警' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

  if (testInfo.project.name !== 'mobile') {
    const actorTableScroll = page.getByTestId('actor-ops-route-scroll')
    expect(await actorTableScroll.evaluate((element) => getComputedStyle(element).overflowX)).toMatch(/auto|scroll/)
  } else {
    await expect(page.getByTestId('actor-ops-route-scroll')).toBeHidden()
  }
  expect(await page.locator('body').innerText()).not.toContain('not-rendered-by-actor-settings')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('account and documentation menus open upward and expose manual, changelog, and Release destinations', async ({ page }, testInfo) => {
  await mockAdminApi(page)

  if (testInfo.project.name === 'mobile') {
    await page.goto('/subscriptions')
    const mobileNavigation = page.getByRole('navigation', { name: '移动端主导航' })
    await expect(mobileNavigation).toBeVisible()
    const navigationBounds = await mobileNavigation.boundingBox()
    expect(navigationBounds).not.toBeNull()
    expect(Math.abs((navigationBounds!.y + navigationBounds!.height) - (page.viewportSize()?.height ?? 0))).toBeLessThanOrEqual(1)
    await page.getByRole('button', { name: '更多与账户' }).click()
    const mobileMore = page.getByRole('dialog', { name: '更多与账户' })
    await expect(mobileMore.getByRole('button', { name: '账户与成员' })).toBeVisible()
    await expect(mobileMore.getByRole('button', { name: '设置' })).toBeVisible()
    await expect(mobileMore.getByRole('button', { name: '操作手册' })).toBeVisible()
    await expect(mobileMore.getByRole('button', { name: '退出登录' })).toBeVisible()
    await mobileMore.getByRole('button', { name: '设置' }).click()
    await expect(page).toHaveURL(/\/settings$/)
    await expect(mobileMore).toHaveCount(0)
    await page.goto('/settings')
    await expect(page.getByText('操作手册', { exact: true })).toBeVisible()
    await expect(page.getByText('更新日志', { exact: true })).toBeVisible()
    await expect(page.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('href', 'https://github.com/StealHD/infohub-light/releases')
    return
  }

  await page.goto('/subscriptions')
  const accountTrigger = page.getByRole('button', { name: '打开账户菜单' })
  await accountTrigger.click()
  const accountMenu = page.getByRole('dialog', { name: '账户菜单' })
  await expect(accountMenu).toBeVisible()
  await expect(accountMenu.getByRole('button', { name: '操作手册' })).toBeVisible()
  await expect(accountMenu.getByRole('button', { name: '更新日志' })).toBeVisible()
  await expect(accountMenu.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('target', '_blank')
  const accountTriggerBounds = await accountTrigger.boundingBox()
  const accountSurfaceBounds = await page.locator('[data-account-menu-surface]').boundingBox()
  expect(accountTriggerBounds).not.toBeNull()
  expect(accountSurfaceBounds).not.toBeNull()
  expect(accountSurfaceBounds!.y + accountSurfaceBounds!.height).toBeLessThanOrEqual(accountTriggerBounds!.y)

  await accountMenu.getByRole('button', { name: '操作手册' }).click()
  await expect(page).toHaveURL(/\/manual$/)
  await expect(page.getByRole('heading', { name: '操作手册' })).toBeVisible()

  if (testInfo.project.name === 'desktop') {
    await page.goto('/subscriptions')
    await page.getByRole('button', { name: '展开侧栏' }).click()
    const documentationTrigger = page.getByRole('button', { name: '打开文档与发布菜单' })
    await documentationTrigger.click()
    const documentationMenu = page.getByRole('dialog', { name: '文档与发布菜单' })
    await expect(documentationMenu.getByRole('button', { name: '操作手册' })).toBeVisible()
    await expect(documentationMenu.getByRole('button', { name: '更新日志' })).toBeVisible()
    await expect(documentationMenu.getByRole('link', { name: /Release 发布页/ })).toHaveAttribute('rel', 'noopener noreferrer')
    const documentationTriggerBounds = await documentationTrigger.boundingBox()
    const documentationSurfaceBounds = await page.locator('[data-documentation-menu-surface]').boundingBox()
    expect(documentationTriggerBounds).not.toBeNull()
    expect(documentationSurfaceBounds).not.toBeNull()
    expect(documentationSurfaceBounds!.y + documentationSurfaceBounds!.height).toBeLessThanOrEqual(documentationTriggerBounds!.y)
  }
})

test('settings key groups retain quota, refresh, safety locks and accessible modal behavior', async ({ page }) => {
  const apiState = await mockAdminApi(page)
  await page.goto('/settings/secrets')

  await expect(page.getByRole('heading', { name: '密钥' })).toBeVisible()
  const apifyGroup = page.locator('[data-settings-group][aria-label="Apify Key 池"]')
  const aiGroup = page.locator('[data-settings-group][aria-label="已配置 AI Key"]')
  await expect(apifyGroup).toBeVisible()
  await expect(aiGroup).toBeVisible()
  await expect(apifyGroup.getByText('Apify Primary', { exact: true })).toBeVisible()
  await expect(aiGroup.getByText('Gemini Primary', { exact: true })).toBeVisible()
  await expect(page.getByText('套餐剩余 $36.50')).toBeVisible()
  await expect.poll(apiState.quotaRequests).toBe(1)
  const refreshQuota = page.getByRole('button', { name: '刷新 Apify Primary 额度' })
  apiState.deferQuotaRefresh()
  await refreshQuota.click()
  await expect.poll(apiState.quotaRequests).toBe(2)
  const refreshingQuota = page.getByRole('button', { name: '正在刷新 Apify Primary 额度' })
  await expect(refreshingQuota).toBeDisabled()
  await expect(refreshingQuota.locator('svg')).toHaveClass(/animate-spin/)
  await expect(refreshingQuota.locator('xpath=ancestor::*[@aria-busy][1]')).toHaveAttribute('aria-busy', 'true')
  await expect(page.getByText('套餐剩余 $36.50')).toBeVisible()
  apiState.releaseQuotaRefresh()
  await expect(refreshQuota).toBeEnabled()
  const apifyPrimaryItem = apifyGroup.getByText('Apify Primary', { exact: true }).locator('xpath=ancestor::*[@data-settings-item][1]')
  await apifyPrimaryItem.getByRole('button', { name: /运行详情/ }).click()
  const rotateTrigger = apifyPrimaryItem.getByRole('button', { name: '轮换 Apify Primary' })
  await rotateTrigger.click()
  await expect(page.getByRole('dialog', { name: '轮换 Apify Primary' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: '轮换 Apify Primary' })).toHaveCount(0)
  await expect(rotateTrigger).toBeFocused()
  await expect(page.getByRole('button', { name: '删除 Gemini Primary' })).toBeDisabled()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('successful Key creation uses a top overlay without moving settings content', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await mockAdminApi(page)
  await page.goto('/settings/secrets')
  await expect(page.getByRole('heading', { name: '密钥' })).toBeVisible()
  await page.evaluate(async () => {
    await document.fonts.ready
  })
  await expect(page.getByText('套餐剩余 $36.50')).toBeVisible()

  const settingsFrame = page.locator('[data-page-frame="settings"]')
  const positionWithinPage = () => settingsFrame.evaluate((element) => {
    const workspace = element.closest('[data-settings-workspace]')
    if (!workspace) throw new Error('Settings workspace is missing.')
    const frameBounds = element.getBoundingClientRect()
    const workspaceBounds = workspace.getBoundingClientRect()
    return {
      x: frameBounds.x - workspaceBounds.x,
      y: frameBounds.y - workspaceBounds.y,
    }
  })
  const stablePositionWithinPage = async () => {
    let previous = await positionWithinPage()
    let stableFrames = 0
    for (let frame = 0; frame < 20 && stableFrames < 3; frame += 1) {
      await page.waitForTimeout(50)
      const current = await positionWithinPage()
      stableFrames = Math.abs(current.x - previous.x) <= 0.5 && Math.abs(current.y - previous.y) <= 0.5
        ? stableFrames + 1
        : 0
      previous = current
    }
    expect(stableFrames).toBe(3)
    return previous
  }
  const before = await stablePositionWithinPage()

  await page.getByRole('button', { name: '新增 Key' }).click()
  const createDialog = page.getByRole('dialog', { name: '新增 Key' })
  await createDialog.getByRole('textbox', { name: 'Key 名称' }).fill('DeepSeek Primary')
  await createDialog.getByRole('textbox', { name: 'Key provider' }).fill('deepseek')
  await createDialog.getByRole('textbox', { name: '环境变量名' }).fill('DEEPSEEK_API_KEY')
  await createDialog.getByLabel('Key 值').fill('write-only-e2e-value')
  await createDialog.getByRole('button', { name: '安全保存 Key' }).click()
  const toastTitle = page.getByText('Key 已安全保存', { exact: true })
  await expect(toastTitle).toBeVisible()
  const after = await positionWithinPage()
  expect(Math.abs(after.x - before.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(after.y - before.y)).toBeLessThanOrEqual(1)
  await expect(page.locator('[data-page-frame="settings"]').getByText('Key 已安全保存', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Key 已保存，页面不会回显真实值。')).toHaveCount(0)

  const toastBounds = await toastTitle.boundingBox()
  const viewport = page.viewportSize()!
  expect(toastBounds).not.toBeNull()
  expect(toastBounds!.x).toBeGreaterThanOrEqual(0)
  expect(toastBounds!.x + toastBounds!.width).toBeLessThanOrEqual(viewport.width)
  expect(toastBounds!.y).toBeGreaterThanOrEqual(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('historical terminal jobs do not trigger subscription request storms or eager run-history loading', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'network request regression is covered once at the desktop viewport')
  const failedApiRequests: string[] = []
  page.on('requestfailed', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) {
      failedApiRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText ?? ''}`)
    }
  })
  const apiState = await mockAdminApi(page, true, { historicalTerminalJobs: 100 })

  await page.goto('/subscriptions')
  await expect(page.getByRole('tablist', { name: '订阅与来源页面' })).toBeVisible()
  await expect(page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ })).toBeVisible()
  await page.waitForTimeout(300)
  const initialCounts = apiState.requestCounts()
  expect(initialCounts.allJobs).toBe(0)
  expect(initialCounts.feedJobs).toBeGreaterThanOrEqual(1)
  expect(initialCounts.feedJobs).toBeLessThanOrEqual(2)
  expect(initialCounts.sourceHealth).toBeGreaterThanOrEqual(1)
  expect(initialCounts.sourceHealth).toBeLessThanOrEqual(2)
  failedApiRequests.length = 0

  await page.getByRole('tab', { name: '运行记录' }).click()
  await expect(page.locator('[data-compact-job-card]').first()).toBeVisible()
  await expect.poll(() => apiState.requestCounts()).toEqual({
    feedJobs: initialCounts.feedJobs,
    allJobs: 1,
    sourceHealth: initialCounts.sourceHealth,
  })
  await page.waitForTimeout(300)
  expect(apiState.requestCounts()).toEqual({
    feedJobs: initialCounts.feedJobs,
    allJobs: 1,
    sourceHealth: initialCounts.sourceHealth,
  })

  await page.getByRole('link', { name: '助手连接', exact: true }).click()
  await expect(page.getByRole('heading', { name: '助手连接', exact: true })).toBeVisible()
  await page.getByRole('link', { name: '订阅', exact: true }).click()
  await expect(page.getByRole('tablist', { name: '订阅与来源页面' })).toBeVisible()
  await page.getByRole('tab', { name: '运行记录' }).click()
  await expect(page.locator('[data-compact-job-card]').first()).toBeVisible()
  await page.waitForTimeout(300)
  expect(apiState.requestCounts()).toEqual({
    feedJobs: initialCounts.feedJobs,
    allJobs: 1,
    sourceHealth: initialCounts.sourceHealth,
  })
  expect(failedApiRequests).toEqual([])
})

test('subscription channels stay compact, actionable and accessible at every acceptance viewport', async ({ page }, testInfo) => {
  const consoleErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => consoleErrors.push(error.message))
  const apiState = await mockAdminApi(page)
  await page.goto('/subscriptions')
  await expect(page.getByRole('tablist', { name: '订阅与来源页面' })).toBeVisible()

  const viewportWidth = page.viewportSize()?.width ?? 0
  const tabWidths: number[] = []
  for (const tab of await page.getByRole('tab').all()) {
    const bounds = await tab.boundingBox()
    expect(bounds).not.toBeNull()
    expect(bounds!.x).toBeGreaterThanOrEqual(0)
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(viewportWidth)
    tabWidths.push(bounds!.width)
  }

  const scheduleCard = page.locator('[data-feed-schedule]')
  const scheduleSwitch = scheduleCard.getByRole('switch', { name: '全局自动更新' })
  const scheduleSelect = scheduleCard.getByRole('button', { name: /更新周期/ })
  await expect(scheduleSwitch).toBeChecked()
  await expect(scheduleSelect).toBeVisible()
  await expect(scheduleCard.getByText('覆盖 1 个订阅')).toBeVisible()
  await expect(scheduleCard.getByText('自动更新', { exact: true })).toHaveCount(0)
  await expect(scheduleCard.getByRole('button', { name: '管理自动更新' })).toHaveCount(0)
  const scheduleBounds = await scheduleCard.boundingBox()
  const switchBounds = await scheduleSwitch.boundingBox()
  const selectBounds = await scheduleSelect.boundingBox()
  expect(scheduleBounds).not.toBeNull()
  expect(switchBounds).not.toBeNull()
  expect(selectBounds).not.toBeNull()
  expect(switchBounds!.x).toBeGreaterThan(scheduleBounds!.x + scheduleBounds!.width / 2)
  expect(switchBounds!.y).toBeLessThan(selectBounds!.y)
  expect(Math.abs((selectBounds!.x + selectBounds!.width) - (scheduleBounds!.x + scheduleBounds!.width - 16))).toBeLessThanOrEqual(8)

  await expect(page.getByRole('heading', { name: '全部', level: 2 })).toBeVisible()
  if (testInfo.project.name === 'desktop') {
    const subscriptionNavigation = page.getByRole('navigation', { name: '我的订阅频道' })
    await expect(subscriptionNavigation.getByRole('button', { name: /^全部，/ })).toBeVisible()
    await expect(subscriptionNavigation.getByRole('button', { name: /^异常，/ })).toBeVisible()
    await subscriptionNavigation.getByRole('button', { name: /^异常，/ }).click()
    await expect(page.getByRole('heading', { name: '异常', level: 2 })).toBeVisible()
    await expect(page.getByText('当前没有异常来源')).toBeVisible()
    await subscriptionNavigation.getByRole('button', { name: /^全部，/ }).click()
  } else {
    const viewSelector = page.locator('[data-compact-channel-controls]').getByRole('button', { name: /订阅视图/ })
    await viewSelector.click()
    await page.getByRole('option', { name: /异常 · 0/ }).click()
    await expect(page.getByRole('heading', { name: '异常', level: 2 })).toBeVisible()
    await expect(page.getByText('当前没有异常来源')).toBeVisible()
    await viewSelector.click()
    await page.getByRole('option', { name: /全部 · 1/ }).click()
  }

  const subscriptionCard = page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ })
  await expect(subscriptionCard.getByText('更新：全局')).toBeVisible()
  await expect(subscriptionCard.getByText('每 6 小时')).toBeVisible()
  const cardHeader = subscriptionCard.locator('[data-source-card-header]')
  const healthChip = cardHeader.locator('[data-source-health-chip]')
  const editSource = subscriptionCard.getByRole('button', { name: '编辑来源：OpenAI Blog' })
  const [headerBounds, healthBounds] = await Promise.all([
    cardHeader.boundingBox(),
    healthChip.boundingBox(),
  ])
  expect(headerBounds).not.toBeNull()
  expect(healthBounds).not.toBeNull()
  const headerCenter = headerBounds!.y + headerBounds!.height / 2
  expect(Math.abs((healthBounds!.y + healthBounds!.height / 2) - headerCenter)).toBeLessThanOrEqual(1)
  expect(await editSource.evaluate((element) => element.closest('[data-source-card-controls]') !== null)).toBe(true)
  const healthyStatus = subscriptionCard.getByRole('button', { name: '正常' })
  await healthyStatus.hover()
  const healthTooltip = page.getByRole('tooltip')
  await expect(healthTooltip).toHaveText('正常')
  const [healthyStatusBounds, healthTooltipBounds] = await Promise.all([
    healthyStatus.boundingBox(),
    healthTooltip.boundingBox(),
  ])
  expect(healthyStatusBounds).not.toBeNull()
  expect(healthTooltipBounds).not.toBeNull()
  expect(healthTooltipBounds!.y + healthTooltipBounds!.height).toBeLessThanOrEqual(healthyStatusBounds!.y + 1)
  await page.mouse.move(0, 0)

  await expect(subscriptionCard.getByRole('button', { name: '更多操作：OpenAI Blog' })).toHaveCount(0)
  const notificationSwitch = subscriptionCard.getByRole('switch', { name: '新内容通知：OpenAI Blog' })
  await notificationSwitch.focus()
  await expect(notificationSwitch).toBeFocused()
  const notificationUpdate = page.waitForResponse((response) => {
    const request = response.request()
    return (
      new URL(response.url()).pathname === '/api/me/subscriptions/subscription-1'
      && request.method() === 'PATCH'
      && response.ok()
    )
  })
  if (testInfo.project.name === 'mobile') {
    await notificationSwitch.click()
  } else {
    await page.keyboard.press('Space')
  }
  await notificationUpdate
  await expect(notificationSwitch).toBeChecked()

  await editSource.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'OpenAI Blog · 来源设置' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: 'OpenAI Blog · 来源设置' })).toHaveCount(0)
  await expect(editSource).toBeFocused()

  await subscriptionCard.getByRole('button', { name: '配置 OpenAI Blog 订阅' }).click()
  const subscriptionDialog = page.getByRole('dialog', { name: 'OpenAI Blog · 订阅设置' })
  await expect(subscriptionDialog.getByRole('switch', { name: /新内容通知/ })).toHaveCount(0)
  const globalMode = subscriptionDialog.getByRole('radio', { name: '跟随全局（默认）' })
  const sourceMode = subscriptionDialog.getByRole('radio', { name: '单源独立周期' })
  await expect(globalMode).toBeChecked()
  await expect(subscriptionDialog.getByRole('button', { name: /单源更新周期/ })).toHaveCount(0)
  await sourceMode.focus()
  await page.keyboard.press('Space')
  await expect(sourceMode).toBeChecked()
  await expect(subscriptionDialog.getByRole('button', { name: /单源更新周期/ })).toBeVisible()
  await page.keyboard.press('Escape')

  const idleFetch = subscriptionCard.getByRole('button', { name: '立即获取 OpenAI Blog' })
  const idleFetchBounds = await idleFetch.boundingBox()
  apiState.deferSourceFetch()
  await idleFetch.click()
  const pendingFetch = subscriptionCard.getByRole('button', { name: '提交中 OpenAI Blog' })
  await expect(pendingFetch).toBeDisabled()
  await expect(pendingFetch).toHaveText('立即获取')
  await expect(pendingFetch.locator('svg')).toHaveClass(/animate-spin/)
  await expect(pendingFetch.locator('xpath=..')).toHaveAttribute('aria-busy', 'true')
  const pendingFetchBounds = await pendingFetch.boundingBox()
  expect(idleFetchBounds).not.toBeNull()
  expect(pendingFetchBounds).not.toBeNull()
  expect(Math.abs(pendingFetchBounds!.width - idleFetchBounds!.width)).toBeLessThanOrEqual(1)
  apiState.releaseSourceFetch()
  await expect(subscriptionCard.getByRole('button', { name: '已排队 OpenAI Blog' })).toBeDisabled()

  if (testInfo.project.name === 'mobile') {
    expect(Math.max(...tabWidths) - Math.min(...tabWidths)).toBeGreaterThan(1)
    expect(tabWidths.every((width) => width < viewportWidth / 2)).toBe(true)
    await expect(page.locator('[data-channel-rail]')).toBeHidden()
    await expect(page.locator('[data-compact-channel-controls]')).toBeVisible()
    await expect(page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ })).toBeInViewport()

    await expect(page.getByRole('searchbox', { name: '搜索来源' })).toBeVisible()
    await page.getByRole('button', { name: '筛选来源，已启用 0 项' }).click()
    const filterDialog = page.getByRole('dialog', { name: '筛选来源' })
    await expect(filterDialog).toBeVisible()
    await expect(filterDialog.getByText('来源类型', { exact: true })).toBeVisible()
    await expect(filterDialog.getByText('健康状态', { exact: true })).toBeVisible()
    await expect(filterDialog.getByText('可见范围', { exact: true })).toBeVisible()
    const clearFilters = filterDialog.getByRole('button', { name: '清除筛选' })
    await expect(clearFilters).toBeDisabled()
    await filterDialog.getByRole('button', { name: '来源类型' }).click()
    await page.getByRole('option', { name: 'RSS/Atom' }).click()
    await expect(clearFilters).toBeEnabled()
    await filterDialog.getByRole('button', { name: '完成' }).click()
    await expect(filterDialog).toHaveCount(0)
    await expect(page.getByRole('button', { name: '筛选来源，已启用 1 项' })).toBeVisible()
    await page.getByRole('button', { name: '筛选来源，已启用 1 项' }).click()
    await page.getByRole('dialog', { name: '筛选来源' }).getByRole('button', { name: '清除筛选' }).click()
    await expect(page.getByRole('button', { name: '筛选来源，已启用 0 项' })).toBeVisible()
    await page.getByRole('dialog', { name: '筛选来源' }).getByRole('button', { name: '完成' }).click()
    await expect(page.getByRole('dialog', { name: '筛选来源' })).toHaveCount(0)

    const originalViewport = page.viewportSize()
    await page.setViewportSize({ width: 320, height: 700 })
    await expect(scheduleSwitch).toBeVisible()
    await expect(scheduleSelect).toBeVisible()
    const narrowScheduleBounds = await scheduleCard.boundingBox()
    const narrowSourceBounds = await page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ }).boundingBox()
    expect(narrowScheduleBounds).not.toBeNull()
    expect(narrowSourceBounds).not.toBeNull()
    expect(narrowScheduleBounds!.x).toBeGreaterThanOrEqual(0)
    expect(narrowScheduleBounds!.x + narrowScheduleBounds!.width).toBeLessThanOrEqual(320)
    expect(narrowSourceBounds!.x).toBeGreaterThanOrEqual(0)
    expect(narrowSourceBounds!.x + narrowSourceBounds!.width).toBeLessThanOrEqual(320)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
    if (originalViewport) await page.setViewportSize(originalViewport)
  } else {
    await expect(page.getByRole('list', { name: '当前频道订阅' })).toBeVisible()
    if (testInfo.project.name === 'desktop') {
      const channelRail = page.locator('[data-channel-rail]')
      await expect(channelRail).toBeVisible()
      await expect(page.locator('[data-compact-channel-controls]')).toBeHidden()
      const railBounds = await channelRail.boundingBox()
      expect(railBounds).not.toBeNull()
      expect(Math.abs(railBounds!.width - 236)).toBeLessThanOrEqual(1)
    } else {
      await expect(page.locator('[data-channel-rail]')).toBeHidden()
      await expect(page.locator('[data-compact-channel-controls]')).toBeVisible()
    }
  }

  await expect(healthChip).toHaveText('正常')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)

  await page.getByRole('tab', { name: '来源库' }).click()
  await expect(page).toHaveURL(/\/subscriptions\?tab=library$/)
  if (testInfo.project.name === 'desktop') {
    await page.getByRole('navigation', { name: '来源库频道' }).getByRole('button', { name: /产品机会/ }).click()
  } else {
    const compactControls = page.locator('[data-compact-channel-controls]')
    await compactControls.getByRole('button', { name: /频道/ }).click()
    await page.getByRole('option', { name: /产品机会/ }).click()
  }
  await expect(page.getByRole('listitem', { name: /Product Notes 来源/ })).toBeVisible()
  await page.getByRole('button', { name: '订阅 Product Notes' }).click()
  await expect(page.getByText('Product Notes 订阅成功', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '取消订阅 Product Notes' })).toBeVisible()

  const productEdit = page.getByRole('button', { name: '编辑来源：Product Notes' })
  await expect(productEdit).toBeVisible()
  await expect(page.getByRole('button', { name: '更多操作：Product Notes' })).toHaveCount(0)
  await productEdit.click()
  const productDialog = page.getByRole('dialog', { name: 'Product Notes · 来源设置' })
  await expect(productDialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(productDialog).toHaveCount(0)
  await expect(productEdit).toBeFocused()

  await page.getByRole('tab', { name: '运行记录' }).click()
  await expect(page).toHaveURL(/\/subscriptions\?tab=jobs$/)
  const runCard = page.locator('[data-compact-job-card]').first()
  await expect(runCard).toBeVisible()
  const runBounds = await runCard.boundingBox()
  expect(runBounds).not.toBeNull()
  expect(runBounds!.height).toBeLessThanOrEqual(190)
  if (testInfo.project.name === 'mobile') {
    const technicalDisclosure = runCard.getByRole('button', { name: '技术详情' })
    const schemaDisclosure = runCard.getByRole('button', { name: '响应结构' })
    await expect(technicalDisclosure).toHaveAttribute('aria-expanded', 'false')
    await expect(schemaDisclosure).toHaveAttribute('aria-expanded', 'false')
    await technicalDisclosure.click()
    await schemaDisclosure.click()
    await expect(technicalDisclosure).toHaveAttribute('aria-expanded', 'true')
    await expect(schemaDisclosure).toHaveAttribute('aria-expanded', 'true')
    await expect(runCard.locator('[data-disclosure-state="open"]')).toHaveCount(2)
  }

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
  expect(consoleErrors).toEqual([])
})

test('YouTube channel creation, errors, filtering and editing work at every acceptance viewport', async ({ page }) => {
  const apiState = await mockAdminApi(page)
  await page.goto('/subscriptions')

  const addSource = page.getByRole('button', { name: '新增来源' })
  await addSource.focus()
  await page.keyboard.press('Enter')
  const createDialog = page.getByRole('dialog', { name: '新增来源' })
  await createDialog.getByRole('button', { name: '来源类型' }).click()
  await page.getByRole('option', { name: 'YouTube 频道' }).click()

  const latestItem = createDialog.getByRole('checkbox', { name: '保留最新内容' })
  await expect(latestItem).toBeChecked()
  await expect(createDialog.getByText(/时间窗口为空时仅保留最近一条/)).toBeVisible()
  await expect(createDialog.getByText(/API Key|Cookie/)).toHaveCount(0)
  await createDialog.getByRole('textbox', { name: '来源名称' }).fill('Google Developers')
  const channelInput = createDialog.getByRole('textbox', { name: 'YouTube 频道地址或 @handle' })
  await channelInput.fill('@Missing')
  await createDialog.getByRole('button', { name: '创建并订阅' }).click()
  await expect(createDialog.getByText('未找到这个 YouTube 频道，请检查链接或改用频道 ID。')).toBeVisible()
  await expect(createDialog.getByText('unsafe upstream detail')).toHaveCount(0)

  await channelInput.fill('@GoogleDevelopers')
  await createDialog.getByRole('button', { name: '创建并订阅' }).click()
  await expect(createDialog).toHaveCount(0)
  await expect(page.getByText('来源已创建并订阅', { exact: true })).toBeVisible()
  expect(apiState.youtubeCreatePayloads()).toHaveLength(2)
  expect(apiState.youtubeCreatePayloads()[1]).toMatchObject({
    type: 'youtube_channel',
    display_name: 'Google Developers',
    config: {
      url: '@GoogleDevelopers',
      keep_latest_item: true,
    },
  })

  const youtubeCard = page.getByRole('listitem', { name: /Google Developers 订阅来源/ })
  await expect(youtubeCard).toBeVisible()
  await expect(youtubeCard.getByText(/YouTube 频道/)).toBeVisible()

  await page.getByRole('button', { name: /筛选来源，已启用 0 项/ }).click()
  const filterDialog = page.getByRole('dialog', { name: '筛选来源' })
  await filterDialog.getByRole('button', { name: '来源类型' }).click()
  await page.getByRole('option', { name: 'YouTube 频道' }).click()
  await filterDialog.getByRole('button', { name: '完成' }).click()
  await expect(youtubeCard).toBeVisible()
  await expect(page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ })).toHaveCount(0)

  await youtubeCard.getByRole('button', { name: '编辑来源：Google Developers' }).click()
  const editDialog = page.getByRole('dialog', { name: 'Google Developers · 来源设置' })
  await expect(editDialog.getByRole('textbox', { name: 'YouTube 频道地址或 @handle' })).toHaveValue(
    'https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv',
  )
  const editLatest = editDialog.getByRole('checkbox', { name: '保留最新内容' })
  await expect(editLatest).toBeChecked()
  await editLatest.focus()
  await page.keyboard.press('Space')
  await expect(editLatest).not.toBeChecked()
  await editDialog.getByRole('button', { name: '保存来源' }).click()
  await expect(editDialog).toHaveCount(0)
  await expect(page.getByRole('dialog')).toHaveCount(0)

  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})

test('public/private subscription views and direct share stay usable at 693, 645 and 320 pixels', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop', 'One browser project resizes through the additional acceptance widths.')
  await mockAdminApi(page, true, { includePrivateSource: true })
  await page.setViewportSize({ width: 693, height: 762 })
  await page.goto('/subscriptions')

  await expect(page.locator('[data-feed-schedule]').getByText(
    '覆盖 1 个订阅 · 1 个使用单源周期',
  )).toBeVisible()
  const viewSelector = page.locator('[data-compact-channel-controls]').getByRole('button', { name: /订阅视图/ })
  await viewSelector.click()
  await expect(page.getByRole('option', { name: /公共订阅 · 1/ })).toBeVisible()
  await expect(page.getByRole('option', { name: /私人订阅 · 1/ })).toBeVisible()
  await page.getByRole('option', { name: /公共订阅 · 1/ }).click()
  await expect(page.getByRole('heading', { name: '公共订阅', level: 2 })).toBeVisible()
  await expect(page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ })).toBeVisible()
  await expect(page.getByRole('listitem', { name: /私人研究源 订阅来源/ })).toHaveCount(0)

  await viewSelector.click()
  await page.getByRole('option', { name: /私人订阅 · 1/ }).click()
  await expect(page.getByRole('heading', { name: '私人订阅', level: 2 })).toBeVisible()
  const privateCard = page.getByRole('listitem', { name: /私人研究源 订阅来源/ })
  const share = privateCard.getByRole('button', { name: '分享来源：私人研究源' })
  const history = privateCard.getByRole('link', { name: '查看 私人研究源 的 2 条历史内容' })
  await expect(share).toBeVisible()
  await expect(privateCard.locator('[data-source-counts]')).toHaveText(/今日\s*0\s*近7天\s*0\s*历史\s*2/)
  await expect(privateCard.getByLabel('最近更新 尚未完成，上次抓取 2 条')).toBeVisible()
  await expect(history).toHaveText('2')
  await expect(history).toHaveAttribute('href', '/history?source_id=source-private')
  await expect(privateCard.getByRole('button', { name: '更多操作：私人研究源' })).toHaveCount(0)

  await page.setViewportSize({ width: 645, height: 762 })
  await expect.poll(
    () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
  ).toBe(true)
  await share.click()
  const shareDialog = page.getByRole('dialog', { name: '分享 私人研究源' })
  await expect(shareDialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(shareDialog).toHaveCount(0)
  await expect(share).toBeFocused()

  await page.setViewportSize({ width: 320, height: 700 })
  await expect(privateCard).toBeVisible()
  const cardBounds = await privateCard.boundingBox()
  expect(cardBounds).not.toBeNull()
  expect(cardBounds!.x).toBeGreaterThanOrEqual(0)
  expect(cardBounds!.x + cardBounds!.width).toBeLessThanOrEqual(320)
  await expect.poll(
    () => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
  ).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])

  await history.click()
  await expect(page).toHaveURL('/history?source_id=source-private')
  await expect(page.getByText('来源：私人研究源', { exact: true })).toBeVisible()
  await expect(page.getByRole('article', { name: privateHistoryItems[0].title })).toBeVisible()
  await expect(page.getByRole('article', { name: privateHistoryItems[1].title })).toBeVisible()
})

test('subscription semantic UI matches light and dark visual baselines at every acceptance viewport', async ({ page }) => {
  await mockAdminApi(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/subscriptions')
  const sourceCard = page.getByRole('listitem', { name: /OpenAI Blog 订阅来源/ })
  await expect(sourceCard.locator('[data-source-counts]')).toHaveText(/今日\s*0\s*近7天\s*0\s*历史\s*7/)
  await expect(sourceCard.getByRole('button', { name: /立即获取 OpenAI Blog；上次抓取 7 条/ })).toBeVisible()

  for (const colorMode of ['light', 'dark'] as const) {
    await page.evaluate((mode) => {
      window.localStorage.setItem('inteliscope.ui.theme.v1', JSON.stringify({
        themeName: 'graphite-purple',
        colorMode: mode,
      }))
    }, colorMode)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', colorMode)
    await expect(sourceCard).toBeVisible()
    await expect(sourceCard.locator('[data-source-counts]')).toHaveText(/今日\s*0\s*近7天\s*0\s*历史\s*7/)
    await page.evaluate(async () => {
      await document.fonts.ready
    })
    await expect(page).toHaveScreenshot(`subscriptions-semantic-${colorMode}.png`, {
      animations: 'disabled',
      caret: 'hide',
    })
  }
})

test('production login is a standalone HeroUI page at every acceptance viewport', async ({ page }) => {
  await mockAdminApi(page, false)
  await page.goto('/login')
  await expect(page.getByRole('heading', { name: '登录私人信息雷达' })).toBeVisible()
  await expect(page.locator('h1')).toHaveCount(1)
  await expect(page.locator('[data-page-frame="auth"]')).toBeVisible()
  await expect(page.locator('[data-ui-system="heroui"]')).toBeVisible()
  await expect(page.locator('[class*="Mui"]')).toHaveCount(0)
  await expect(page.getByRole('navigation')).toHaveCount(0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  const accessibility = await new AxeBuilder({ page }).analyze()
  expect(accessibility.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([])
})
