import { describe, expect, it } from 'vitest'

import type { CatalogSource, Job, SourceHealthItem, SourceTypeDefinition, User } from '../../api/types'
import * as subscriptionModel from './subscriptionModel'
import { canEditSource, canMutateSubscriptions, formValuesForSource, groupSourcesByScope, healthMatches, isPublicSubscriptionScope, isSourceSubscribed, presentJob, presentSourceHealthIssue, presentSourceHealthStatus, sourceForSubscription, sourceMutationPayload, sourceScopesForUser, sourceTypeLabel, sourceUsesSecret } from './subscriptionModel'

const user = (role: User['role'], id = 'user-1'): User => ({ id, username: role, role, enabled: true })
const source: CatalogSource = { id: 'src-1', type: 'rss', display_name: 'RSS', scope: 'workspace', enabled: true }

describe('subscription model', () => {
  it('enforces source and subscription role boundaries', () => {
    expect(canMutateSubscriptions(user('member'))).toBe(true)
    expect(canMutateSubscriptions(user('viewer'))).toBe(false)
    expect(canEditSource(user('member'), source)).toBe(false)
    expect(canEditSource(user('admin'), source)).toBe(true)
    expect(canEditSource(user('member'), { ...source, scope: 'private', owner_user_id: 'user-1' })).toBe(true)
    expect(canEditSource(user('admin', 'admin-1'), { ...source, scope: 'private', owner_user_id: 'user-1' })).toBe(false)
  })

  it('covers the complete shared and private source ownership matrix', () => {
    const shared = [{ ...source, scope: 'public' as const }, { ...source, scope: 'workspace' as const }]
    const ownPrivate = { ...source, scope: 'private' as const, owner_user_id: 'member-1' }
    const otherPrivate = { ...source, scope: 'private' as const, owner_user_id: 'other-user' }

    for (const candidate of shared) {
      expect(canEditSource(user('owner', 'owner-1'), candidate)).toBe(true)
      expect(canEditSource(user('admin', 'admin-1'), candidate)).toBe(true)
      expect(canEditSource(user('member', 'member-1'), candidate)).toBe(false)
      expect(canEditSource(user('viewer', 'viewer-1'), candidate)).toBe(false)
    }
    expect(canEditSource(user('member', 'member-1'), ownPrivate)).toBe(true)
    expect(canEditSource(user('member', 'member-1'), otherPrivate)).toBe(false)
    expect(canEditSource(user('admin', 'admin-1'), otherPrivate)).toBe(false)
    expect(canEditSource(user('viewer', 'member-1'), ownPrivate)).toBe(false)
  })

  it('prefills registry-driven fields without defining source rules in the UI', () => {
    const definition: SourceTypeDefinition = {
      type: 'rss',
      fields: [
        { name: 'url', label: 'RSS 地址', input_type: 'url', required: true, default: '' },
        { name: 'limit', label: '上限', input_type: 'number', required: false, default: 20 },
      ],
    }
    expect(formValuesForSource(definition, { ...source, config: { url: 'https://example.com/rss.xml' } })).toEqual({
      url: 'https://example.com/rss.xml', limit: 20,
    })
  })

  it('filters both degraded and failing sources as problems', () => {
    const failing: SourceHealthItem = { subscription_id: 'sub-1', source_id: 'src-1', status: 'failing', consecutive_failures: 2 }
    expect(healthMatches(failing, 'problem')).toBe(true)
    expect(healthMatches({ ...failing, status: 'healthy' }, 'problem')).toBe(false)
  })

  it.each([
    ['fetch', 'Unauthorized', false, '来源授权已失效或当前账户没有访问权限。'],
    ['fetch', 'RateLimitError', true, '上游服务限制了当前访问频率。'],
    ['fetch', 'TimeoutError', true, '上游服务暂时不可用或响应超时。'],
    ['fetch', 'InvalidPayload', false, '来源返回的内容格式无法识别。'],
    ['parse', 'UnexpectedFailure', false, '来源返回的内容格式无法识别。'],
    ['fetch', 'UnexpectedFailure', false, '来源最近一次更新未完成。'],
  ])('maps %s/%s to a stable user-facing reason without exposing the raw message', (stage, code, retryable, reason) => {
    const health: SourceHealthItem = {
      subscription_id: 'sub-issue',
      source_id: 'src-issue',
      status: 'degraded',
      consecutive_failures: 1,
      last_issue: { stage, code, retryable, message: 'GET https://upstream.example/feed returned raw diagnostics' },
    }

    expect(presentSourceHealthIssue(health, { canRetry: true, canEdit: true })).toMatchObject({ reason })
    expect(presentSourceHealthIssue(health, { canRetry: true, canEdit: true }).reason).not.toContain('upstream.example')
  })

  it('explains impact and selects a permission-aware recovery action', () => {
    const health: SourceHealthItem = {
      subscription_id: 'sub-failing',
      source_id: 'src-failing',
      status: 'failing',
      consecutive_failures: 3,
      last_issue: { stage: 'fetch', code: 'HTTPError', retryable: true, message: '503' },
    }

    expect(presentSourceHealthIssue(health, { canRetry: true, canEdit: false })).toMatchObject({
      impact: '已连续 3 次更新失败，该来源的新内容暂时不会进入信息流；历史内容不受影响。',
      action: '点击“立即获取”重试；若仍失败，请稍后再试或检查上游状态。',
    })
    expect(presentSourceHealthIssue({ ...health, last_issue: { ...health.last_issue!, retryable: false } }, { canRetry: true, canEdit: true }).action).toBe('打开“编辑来源”检查地址、权限或内容格式后再试。')
    expect(presentSourceHealthIssue(health, { canRetry: false, canEdit: false }).action).toBe('联系管理员检查来源配置或上游状态。')
  })

  it('keeps create-only and admin-only fields out of a member source PATCH', () => {
    const payload = sourceMutationPayload({
      source,
      allowSecret: false,
      metadata: { display_name: 'Updated', scope: 'workspace', secret_env: 'APIFY_TOKEN', enabled: true },
      config: { url: 'https://example.com/rss.xml' },
    })
    expect(payload).toEqual({ display_name: 'Updated', enabled: true, config: { url: 'https://example.com/rss.xml' } })
    expect(payload).not.toHaveProperty('type')
    expect(payload).not.toHaveProperty('scope')
    expect(payload).not.toHaveProperty('secret_env')
  })

  it('derives market subscription state from the user subscriptions response', () => {
    expect(isSourceSubscribed('src-1', [{ id: 'sub-1', user_id: 'u1', source_id: 'src-1', enabled: true }])).toBe(true)
    expect(isSourceSubscribed('src-2', [{ id: 'sub-1', user_id: 'u1', source_id: 'src-1', enabled: true }])).toBe(false)
  })

  it('keeps a disabled catalog source visible through its subscription projection', () => {
    expect(sourceForSubscription({
      id: 'sub-1', user_id: 'u1', source_id: 'disabled-source', source_display_name: 'Disabled RSS', source_type: 'rss', enabled: false,
    })).toMatchObject({ id: 'disabled-source', display_name: 'Disabled RSS', type: 'rss', enabled: false })
  })

  it('offers an Apify key only to the Apify source definition', () => {
    expect(sourceUsesSecret({ type: 'apify_social', fields: [] })).toBe(true)
    expect(sourceUsesSecret({ type: 'apify_social', fields: [], credential_mode: 'source_secret' })).toBe(true)
    expect(sourceUsesSecret({ type: 'apify_social', fields: [], credential_mode: 'workspace_apify_pool' })).toBe(false)
    expect(sourceUsesSecret({ type: 'rss', fields: [] })).toBe(false)
    expect(sourceUsesSecret({ type: 'github_release', fields: [] })).toBe(false)
  })

  it('limits members to creating private sources', () => {
    expect(sourceScopesForUser(user('member'))).toEqual(['private'])
    expect(sourceScopesForUser(user('admin'))).toEqual(['private', 'public'])
  })

  it('folds legacy workspace sources into the public subscription presentation', () => {
    const groups = groupSourcesByScope([
      { ...source, id: 'private', scope: 'private', owner_user_id: 'user-1' },
      { ...source, id: 'workspace', scope: 'workspace' },
      { ...source, id: 'public', scope: 'public' },
    ])

    expect(groups.map((group) => [group.scope, group.label, group.items.map((item) => item.id)])).toEqual([
      ['public', '公共订阅', ['workspace', 'public']],
      ['private', '私人订阅', ['private']],
    ])
    expect(groupSourcesByScope([{ ...source, id: 'public', scope: 'public' }]).map((group) => group.scope)).toEqual(['public'])
    expect(isPublicSubscriptionScope('public')).toBe(true)
    expect(isPublicSubscriptionScope('workspace')).toBe(true)
    expect(isPublicSubscriptionScope('private')).toBe(false)
  })

  it('presents source and job enums as user-facing Chinese copy', () => {
    const queued: Job = { id: 'job-1', user_id: 'user-1', job_type: 'user_feed_refresh', status: 'queued', result: { item_count: 0 } }
    const failed: Job = { id: 'job-2', user_id: 'user-1', job_type: 'source_fetch', source_id: 'src-1', status: 'failed', error_message: '连接超时' }

    expect(sourceTypeLabel('github_release')).toBe('GitHub 发布')
    expect(sourceTypeLabel('youtube_channel')).toBe('YouTube 频道')
    expect(subscriptionModel.effectiveSourceType({
      ...source,
      setup_type: 'youtube_channel',
    })).toBe('youtube_channel')
    expect(subscriptionModel.effectiveSourceType(source)).toBe('rss')
    expect(presentJob(queued, new Map())).toMatchObject({ title: '更新整个信息流', statusLabel: '等待后台处理', resultLabel: '尚未产生结果' })
    expect(presentJob(failed, new Map([['src-1', source]]))).toMatchObject({ title: '抓取单个来源', statusLabel: '失败', sourceName: 'RSS', detail: '连接超时' })
    expect(presentJob(queued, new Map())).not.toHaveProperty('job_type')
  })

  it.each([
    ['queued', '等待后台处理', 'neutral', 'clock'],
    ['running', '正在获取', 'accent', 'loader'],
    ['succeeded', '已完成', 'positive', 'check'],
    ['partial', '部分完成', 'warning', 'warning'],
    ['failed', '失败', 'critical', 'error'],
    ['cancelled', '已取消', 'neutral', 'stop'],
  ] as const)('maps the %s job state to distinct copy, tone and icon semantics', (status, statusLabel, tone, icon) => {
    const job: Job = { id: `job-${status}`, user_id: 'user-1', job_type: 'source_test', status }
    expect(presentJob(job, new Map())).toMatchObject({ statusLabel, tone, icon })
  })

  it.each([
    ['unknown', '尚未抓取', 'neutral', 'empty'],
    ['healthy', '正常', 'success', 'check'],
    ['degraded', '需关注', 'warning', 'warning'],
    ['failing', '连续失败', 'danger', 'error'],
  ] as const)('maps the %s source health state to distinct copy, tone and icon semantics', (status, label, tone, icon) => {
    expect(presentSourceHealthStatus(status)).toEqual({ label, tone, icon })
  })

  it('presents post-deduplication additions without falling back to fetched or total counts', () => {
    const job: Job = {
      id: 'job-source',
      user_id: 'user-1',
      job_type: 'source_fetch',
      source_id: 'src-1',
      status: 'succeeded',
    }
    const sources = new Map([['src-1', source]])

    expect(presentJob({ ...job, result: {
      fetched_count: 8, item_count: 4, new_item_count: 1, snapshot_created: true,
    } }, sources).resultLabel).toBe('新增 1 条，信息流已更新')
    expect(presentJob({ ...job, result: {
      fetched_count: 8, item_count: 4, new_item_count: 0, snapshot_created: false,
    } }, sources).resultLabel).toBe('本次没有新增内容，信息流无变化')
    expect(presentJob({ ...job, result: {
      fetched_count: 8, item_count: 4, snapshot_created: false,
    } }, sources).resultLabel).toBe('信息流无变化')
    expect(presentJob({ ...job, result: {
      fetched_count: 8, item_count: 4, snapshot_created: true,
    } }, sources).resultLabel).toBe('信息流已更新')
  })
})
