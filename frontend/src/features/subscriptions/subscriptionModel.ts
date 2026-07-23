import type { CatalogSource, Job, SourceHealthItem, SourceHealthStatus, SourceTypeDefinition, Subscription, User } from '../../api/types'

export type HealthFilter = SourceHealthStatus | 'all' | 'problem'

export const canMutateSubscriptions = (user: User) => user.role !== 'viewer'

export const sourceUsesSecret = (definition: SourceTypeDefinition) => (
  definition.credential_mode
    ? definition.credential_mode === 'source_secret'
    : definition.type === 'apify_social'
)

export const sourceScopesForUser = (user: User): CatalogSource['scope'][] => (
  user.role === 'owner' || user.role === 'admin'
    ? ['private', 'public']
    : ['private']
)

export type SubscriptionVisibility = 'public' | 'private'

export function isPublicSubscriptionScope(scope: CatalogSource['scope']): boolean {
  return scope === 'public' || scope === 'workspace'
}

export function sourceMatchesSubscriptionVisibility(
  source: Pick<CatalogSource, 'scope'>,
  visibility: SubscriptionVisibility,
): boolean {
  return visibility === 'public' ? isPublicSubscriptionScope(source.scope) : source.scope === 'private'
}

export function canEditSource(user: User, source: CatalogSource): boolean {
  if (user.role === 'viewer') return false
  if (source.scope === 'private') return source.owner_user_id === user.id
  return user.role === 'owner' || user.role === 'admin'
}

const scopeMetadata = {
  public: { label: '公共订阅', description: '由管理员维护，所有成员都可以订阅。' },
  workspace: { label: '公共订阅', description: '由管理员维护，所有成员都可以订阅。' },
  private: { label: '私人订阅', description: '仅创建者可见和编辑。' },
} as const

export function sourceScopeLabel(scope: CatalogSource['scope']): string {
  return scopeMetadata[scope].label
}

export function sourceScopeDescription(scope: CatalogSource['scope']): string {
  return scopeMetadata[scope].description
}

export function groupSourcesByScope<T extends Pick<CatalogSource, 'scope'>>(items: T[]) {
  return (['public', 'private'] as const).map((scope) => ({
    scope,
    label: sourceScopeLabel(scope),
    description: sourceScopeDescription(scope),
    items: items.filter((item) => sourceMatchesSubscriptionVisibility(item, scope)),
  })).filter((group) => group.items.length > 0)
}

export function groupSourcesByChannel<T>(
  items: T[],
  channelFor: (item: T) => string | null | undefined,
  channelOrder: string[] = [],
) {
  const groups = new Map<string, T[]>()
  for (const item of items) {
    const channel = String(channelFor(item) || '').trim() || '其他'
    groups.set(channel, [...(groups.get(channel) ?? []), item])
  }
  const order = new Map(channelOrder.map((channel, index) => [channel, index]))
  return Array.from(groups, ([channel, groupedItems]) => ({ channel, items: groupedItems })).sort((left, right) => {
    const leftOrder = order.get(left.channel) ?? Number.MAX_SAFE_INTEGER
    const rightOrder = order.get(right.channel) ?? Number.MAX_SAFE_INTEGER
    if (leftOrder !== rightOrder) return leftOrder - rightOrder
    if (left.channel === '其他') return 1
    if (right.channel === '其他') return -1
    return left.channel.localeCompare(right.channel, 'zh-CN')
  })
}

export function effectiveSubscriptionChannel(subscription: Subscription, source: CatalogSource): string {
  return String(subscription.override_channel || source.default_channel || '').trim() || '其他'
}

const sourceTypeLabels: Record<string, string> = {
  rss: 'RSS / Atom',
  github_release: 'GitHub 发布',
  github_user: 'GitHub 动态',
  reddit_subreddit: 'Reddit 社区',
  reddit_user: 'Reddit 用户',
  telegram_channel: 'Telegram 频道',
  apify_social: '社交平台',
  hackernews: 'Hacker News',
}

export const sourceTypeLabel = (type: string): string => sourceTypeLabels[type] ?? '其他来源'

const jobTypeLabels: Record<string, string> = {
  user_feed_refresh: '更新整个信息流',
  source_fetch: '抓取单个来源',
  source_test: '测试来源连接',
}

const jobStatusLabels: Record<Job['status'], string> = {
  queued: '等待后台处理',
  running: '正在获取',
  succeeded: '已完成',
  partial: '部分完成',
  failed: '失败',
  cancelled: '已取消',
}

const jobStatusTones: Record<Job['status'], 'neutral' | 'positive' | 'warning' | 'critical' | 'accent'> = {
  queued: 'neutral',
  running: 'accent',
  succeeded: 'positive',
  partial: 'warning',
  failed: 'critical',
  cancelled: 'neutral',
}

export function presentJob(job: Job, sources: Map<string, CatalogSource>) {
  const result = job.result ?? job.result_json ?? {}
  const message = typeof result.message === 'string' ? result.message : ''
  const fetchedCount = typeof result.fetched_count === 'number' && Number.isFinite(result.fetched_count)
    ? Math.max(0, Math.trunc(result.fetched_count))
    : undefined
  const feedJob = job.job_type === 'source_fetch' || job.job_type === 'user_feed_refresh'
  const feedTerminal = feedJob && (job.status === 'succeeded' || job.status === 'partial')
  const changeLabel = result.snapshot_created === true ? '信息流已更新' : '信息流无变化'
  const resultLabel = feedTerminal
    ? fetchedCount === undefined ? changeLabel : `本次抓取 ${fetchedCount} 条，${changeLabel}`
    : job.status === 'succeeded' || job.status === 'partial' ? '任务已完成' : '尚未产生结果'
  return {
    title: jobTypeLabels[job.job_type] ?? '后台任务',
    statusLabel: jobStatusLabels[job.status],
    tone: jobStatusTones[job.status],
    sourceName: job.source_id ? sources.get(job.source_id)?.display_name : undefined,
    resultLabel,
    detail: job.error_message || message || '',
  }
}

export function formValuesForSource(definition: SourceTypeDefinition, source?: CatalogSource): Record<string, unknown> {
  return Object.fromEntries(definition.fields.map((field) => [
    field.name,
    source?.config && field.name in source.config ? source.config[field.name] : field.default,
  ]))
}

export function healthMatches(item: SourceHealthItem | undefined, filter: HealthFilter): boolean {
  const status = item?.status ?? 'unknown'
  if (filter === 'all') return true
  if (filter === 'problem') return status === 'degraded' || status === 'failing'
  return status === filter
}

export type SourceHealthIssuePresentation = {
  reason: string
  impact: string
  action: string
}

export function presentSourceHealthIssue(
  health: SourceHealthItem,
  permissions: { canRetry: boolean; canEdit: boolean },
): SourceHealthIssuePresentation {
  const issueKind = `${health.last_issue?.stage ?? ''} ${health.last_issue?.code ?? ''}`.toLocaleLowerCase()
  const retryable = health.last_issue?.retryable === true
  const reason = /unauthorized|forbidden|auth|permission|401|403/.test(issueKind)
    ? '来源授权已失效或当前账户没有访问权限。'
    : /rate|too.?many|429/.test(issueKind)
      ? '上游服务限制了当前访问频率。'
      : /timeout|http|network|connection|unavailable|502|503|504/.test(issueKind) || retryable
        ? '上游服务暂时不可用或响应超时。'
        : /parse|decode|invalid|payload|schema|xml|json/.test(issueKind)
          ? '来源返回的内容格式无法识别。'
          : '来源最近一次更新未完成。'
  const impact = health.status === 'failing'
    ? health.consecutive_failures > 1
      ? `已连续 ${health.consecutive_failures} 次更新失败，该来源的新内容暂时不会进入信息流；历史内容不受影响。`
      : '该来源已连续更新失败，新内容暂时不会进入信息流；历史内容不受影响。'
    : '最近一次更新失败，新内容可能延迟；历史内容不受影响。'
  const action = retryable && permissions.canRetry
    ? '点击“立即获取”重试；若仍失败，请稍后再试或检查上游状态。'
    : permissions.canEdit
      ? '打开“编辑来源”检查地址、权限或内容格式后再试。'
      : '联系管理员检查来源配置或上游状态。'
  return { reason, impact, action }
}

export function sourceMutationPayload({ source, allowSecret, metadata, config }: {
  source?: CatalogSource
  allowSecret: boolean
  metadata: Record<string, unknown>
  config: Record<string, unknown>
}): Record<string, unknown> {
  const keys = ['display_name', 'description', 'default_channel', 'default_topics', 'enabled'] as const
  const payload: Record<string, unknown> = { config }
  for (const key of keys) if (metadata[key] !== undefined) payload[key] = metadata[key]
  if (!source) {
    payload.type = metadata.type
    payload.scope = metadata.scope
  }
  if (allowSecret && metadata.secret_env !== undefined) payload.secret_env = metadata.secret_env
  return payload
}

export const isSourceSubscribed = (sourceId: string, subscriptions: Subscription[]) => subscriptions.some((item) => item.source_id === sourceId)

export function sourceForSubscription(subscription: Subscription, source?: CatalogSource): CatalogSource {
  return source ?? {
    id: subscription.source_id,
    type: subscription.source_type ?? 'unknown',
    display_name: subscription.source_display_name ?? '已停用来源',
    scope: 'private',
    enabled: false,
  }
}
