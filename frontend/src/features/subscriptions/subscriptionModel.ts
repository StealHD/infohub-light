import type { CatalogSource, Job, SourceHealthItem, SourceHealthStatus, SourceTypeDefinition, Subscription, User } from '../../api/types'
import { newItemCountOf } from '../jobs/jobModel'

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

export function effectiveSubscriptionChannel(subscription: Subscription, source: CatalogSource): string {
  return String(subscription.override_channel || source.default_channel || '').trim() || '其他'
}

const sourceTypeLabels: Record<string, string> = {
  rss: 'RSS / Atom',
  youtube_channel: 'YouTube 频道',
  github_release: 'GitHub 发布',
  github_user: 'GitHub 动态',
  reddit_subreddit: 'Reddit 社区',
  reddit_user: 'Reddit 用户',
  telegram_channel: 'Telegram 频道',
  apify_social: '社交平台',
  hackernews: 'Hacker News',
}

export const sourceTypeLabel = (type: string): string => sourceTypeLabels[type] ?? '其他来源'

export const effectiveSourceType = (
  source: Pick<CatalogSource, 'type' | 'setup_type'>,
): string => source.setup_type || source.type

const jobTypeLabels: Record<string, string> = {
  user_feed_refresh: '更新整个信息流',
  source_fetch: '抓取单个来源',
  source_test: '测试来源连接',
  apify_actor_discovery: '更新 Actor 候选',
  apify_actor_canary_batch: '验证 Actor 主备',
  apify_actor_validation: '验证备用 Actor',
  apify_actor_pool_apply: '启用 Actor 主备',
}

const actorOpsJobTypes = new Set([
  'apify_actor_discovery',
  'apify_actor_canary_batch',
  'apify_actor_validation',
  'apify_actor_pool_apply',
])

export function isActorOpsJob(job: Pick<Job, 'job_type'>): boolean {
  return actorOpsJobTypes.has(job.job_type)
}

export function shouldShowJob(job: Job): boolean {
  return !isActorOpsJob(job) || job.status === 'failed' || job.status === 'partial'
}

export type ActorOpsJobIssue = {
  reason: string
  impact: string
  next: string
}

export function presentActorOpsJobIssue(job: Job): ActorOpsJobIssue {
  const code = String(job.error_code || '')
  if (['apify_actor_canary_approval_stale', 'apify_actor_route_generation_conflict', 'apify_actor_canary_plan_conflict', 'apify_actor_manual_candidate_stale'].includes(code)) {
    return { reason: 'Actor 配置已更新', impact: '这次验证没有启动，不会收费；当前主备没有变化。', next: '返回 ActorOps，重新选择 Actor 并确认。' }
  }
  if (['apify_actor_unexpected_empty', 'apify_actor_suspicious_empty', 'systemic_empty', 'apify_actor_contract_mismatch', 'apify_actor_metadata_only', 'apify_actor_placeholder', 'apify_actor_target_identity_mismatch', 'apify_actor_revision_output_incompatible'].includes(code)) {
    return { reason: '这个 Actor 不适合当前来源', impact: '它没有加入主备；已有线路继续运行。费用只保留已终结部分。', next: '返回 ActorOps，选择另一个候选。' }
  }
  if (['apify_actor_deleted', 'apify_actor_revision_unavailable', 'apify_actor_build_unavailable', 'apify_actor_revision_preflight_unavailable'].includes(code)) {
    return { reason: '这个 Actor 已不可用', impact: '付费验证没有启动，费用为 $0；当前配置没有变化。', next: '返回 ActorOps，选择另一个候选。' }
  }
  if (['apify_actor_run_timed_out', 'apify_actor_canary_timeout'].includes(code)) {
    return { reason: 'Actor 验证超时', impact: '运行已停止且不会自动重试；费用需要先完成对账。', next: '对账完成后返回 ActorOps，重新选择并确认。' }
  }
  if (['apify_start_outcome_unknown', 'apify_actor_start_outcome_unknown', 'apify_run_reconcile_required'].includes(code)) {
    return { reason: '无法确认 Actor 是否已启动', impact: '为避免重复扣费，后续付费验证已锁定。', next: '先在 Apify 控制台核对，再返回 ActorOps 刷新；不要重试。' }
  }
  if (['apify_actor_budget_blocked', 'apify_actor_pool_stage_budget_invalid', 'apify_actor_quota_unknown'].includes(code)) {
    return { reason: '费用条件不满足', impact: '验证未启动或已暂停，系统不会自动放宽上限。', next: '返回 ActorOps 选择更便宜的候选，或查看运行与告警。' }
  }
  return { reason: 'Actor 配置没有完成', impact: '系统没有确认主备变化；现有线路继续运行。', next: '返回 ActorOps 查看当前状态和唯一下一步。' }
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

const jobStatusIcons: Record<Job['status'], 'clock' | 'loader' | 'check' | 'warning' | 'error' | 'stop'> = {
  queued: 'clock',
  running: 'loader',
  succeeded: 'check',
  partial: 'warning',
  failed: 'error',
  cancelled: 'stop',
}

export function presentJob(job: Job, sources: Map<string, CatalogSource>) {
  const result = job.result ?? job.result_json ?? {}
  const message = typeof result.message === 'string' ? result.message : ''
  const newItemCount = newItemCountOf(job)
  const feedJob = job.job_type === 'source_fetch' || job.job_type === 'user_feed_refresh'
  const feedTerminal = feedJob && (job.status === 'succeeded' || job.status === 'partial')
  const changeLabel = result.snapshot_created === true ? '信息流已更新' : '信息流无变化'
  const resultLabel = feedTerminal
    ? newItemCount === undefined
      ? changeLabel
      : newItemCount === 0
        ? `本次没有新增内容，${changeLabel}`
        : `新增 ${newItemCount} 条，${changeLabel}`
    : job.status === 'succeeded' || job.status === 'partial' ? '任务已完成' : '尚未产生结果'
  const actorOpsIssue = isActorOpsJob(job) ? presentActorOpsJobIssue(job) : null
  return {
    title: jobTypeLabels[job.job_type] ?? '后台任务',
    statusLabel: actorOpsIssue ? '需要处理' : jobStatusLabels[job.status],
    tone: jobStatusTones[job.status],
    icon: jobStatusIcons[job.status],
    sourceName: job.source_id ? sources.get(job.source_id)?.display_name : undefined,
    resultLabel: actorOpsIssue ? actorOpsIssue.reason : resultLabel,
    detail: actorOpsIssue ? '' : job.error_message || message || '',
    actorOpsIssue,
    actorOpsHref: actorOpsIssue ? '/settings/actorops?tab=pool' : null,
  }
}

const sourceHealthPresentations: Record<SourceHealthStatus, {
  label: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
  icon: 'empty' | 'check' | 'warning' | 'error'
}> = {
  unknown: { label: '尚未抓取', tone: 'neutral', icon: 'empty' },
  healthy: { label: '正常', tone: 'success', icon: 'check' },
  degraded: { label: '需关注', tone: 'warning', icon: 'warning' },
  failing: { label: '连续失败', tone: 'danger', icon: 'error' },
}

export function presentSourceHealthStatus(status: SourceHealthStatus = 'unknown') {
  return sourceHealthPresentations[status]
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
