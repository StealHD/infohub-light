import { describe, expect, it } from 'vitest'

import type { CatalogSource, Job, SourceHealthItem, SourceTypeDefinition, User } from '../../api/types'
import * as subscriptionModel from './subscriptionModel'
import { canEditSource, canMutateSubscriptions, formValuesForSource, groupSourcesByScope, healthMatches, isSourceSubscribed, presentJob, sourceForSubscription, sourceMutationPayload, sourceScopesForUser, sourceTypeLabel, sourceUsesSecret } from './subscriptionModel'

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
    expect(sourceUsesSecret({ type: 'rss', fields: [] })).toBe(false)
    expect(sourceUsesSecret({ type: 'github_release', fields: [] })).toBe(false)
  })

  it('limits members to creating private sources', () => {
    expect(sourceScopesForUser(user('member'))).toEqual(['private'])
    expect(sourceScopesForUser(user('admin'))).toEqual(['private', 'workspace', 'public'])
  })

  it('groups visible sources by permission scope and hides empty groups', () => {
    const groups = groupSourcesByScope([
      { ...source, id: 'private', scope: 'private', owner_user_id: 'user-1' },
      { ...source, id: 'workspace', scope: 'workspace' },
      { ...source, id: 'public', scope: 'public' },
    ])

    expect(groups.map((group) => [group.scope, group.label, group.items.map((item) => item.id)])).toEqual([
      ['public', '公共来源', ['public']],
      ['workspace', '团队来源', ['workspace']],
      ['private', '我的私有来源', ['private']],
    ])
    expect(groupSourcesByScope([{ ...source, id: 'public', scope: 'public' }]).map((group) => group.scope)).toEqual(['public'])
  })

  it('groups subscriptions by effective channel with a stable uncategorized fallback', () => {
    const groupSourcesByChannel = (subscriptionModel as unknown as {
      groupSourcesByChannel?: <T>(items: T[], channel: (item: T) => string | null | undefined, order?: string[]) => Array<{ channel: string; items: T[] }>
    }).groupSourcesByChannel
    expect(groupSourcesByChannel).toBeTypeOf('function')
    const groups = groupSourcesByChannel!([
      { id: 'x', channel: '朋友动态' },
      { id: 'openai', channel: 'AI' },
      { id: 'unknown', channel: '' },
      { id: 'apple', channel: '工作/项目' },
    ], (item) => item.channel, ['AI', '工作/项目', '朋友动态', '其他'])

    expect(groups.map((group) => [group.channel, group.items.map((item) => item.id)])).toEqual([
      ['AI', ['openai']],
      ['工作/项目', ['apple']],
      ['朋友动态', ['x']],
      ['其他', ['unknown']],
    ])
  })

  it('presents source and job enums as user-facing Chinese copy', () => {
    const queued: Job = { id: 'job-1', user_id: 'user-1', job_type: 'user_feed_refresh', status: 'queued', result: { item_count: 0 } }
    const failed: Job = { id: 'job-2', user_id: 'user-1', job_type: 'source_fetch', source_id: 'src-1', status: 'failed', error_message: '连接超时' }

    expect(sourceTypeLabel('github_release')).toBe('GitHub 发布')
    expect(presentJob(queued, new Map())).toMatchObject({ title: '更新整个信息流', statusLabel: '等待后台处理', resultLabel: '尚未产生结果' })
    expect(presentJob(failed, new Map([['src-1', source]]))).toMatchObject({ title: '抓取单个来源', statusLabel: '失败', sourceName: 'RSS', detail: '连接超时' })
    expect(presentJob(queued, new Map())).not.toHaveProperty('job_type')
  })

  it('separates fetched source items from final feed totals in run records', () => {
    const job: Job = {
      id: 'job-source',
      user_id: 'user-1',
      job_type: 'source_fetch',
      source_id: 'src-1',
      status: 'succeeded',
    }
    const sources = new Map([['src-1', source]])

    expect(presentJob({ ...job, result: {
      fetched_count: 1, item_count: 4, snapshot_created: true,
    } }, sources).resultLabel).toBe('本次抓取 1 条，信息流已更新')
    expect(presentJob({ ...job, result: {
      fetched_count: 1, item_count: 4, snapshot_created: false,
    } }, sources).resultLabel).toBe('本次抓取 1 条，信息流无变化')
    expect(presentJob({ ...job, result: {
      item_count: 4, snapshot_created: false,
    } }, sources).resultLabel).toBe('信息流无变化')
    expect(presentJob({ ...job, result: {
      item_count: 4, snapshot_created: true,
    } }, sources).resultLabel).toBe('信息流已更新')
  })
})
