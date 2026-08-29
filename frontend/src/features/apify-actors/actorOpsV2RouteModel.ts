import type {
  ActorOpsV2Candidate,
  ActorOpsV2RouteTransport,
  ActorOpsV2StoreMetadata,
} from '../../api/actorOpsV2Types'

export type ActorOpsV2CandidateView = ActorOpsV2Candidate
export type { ActorOpsV2StoreMetadata }

export type ActorOpsV2RouteView = Omit<ActorOpsV2RouteTransport, 'runtime_mode'> & {
  runtime_mode: 'active' | 'disabled'
  normalized_retired_mode: boolean
}

export function actorOpsV2RouteView(route: ActorOpsV2RouteTransport): ActorOpsV2RouteView {
  const normalizedRetiredMode = route.runtime_mode !== 'active' && route.runtime_mode !== 'disabled'
  return {
    ...route,
    standby_candidates: orderedActorOpsV2StandbyCandidates(route.standby_candidates),
    runtime_mode: route.runtime_mode === 'active' ? 'active' : 'disabled',
    normalized_retired_mode: normalizedRetiredMode,
    degraded_reason: normalizedRetiredMode
      ? 'actorops_v2_route_migration_required'
      : route.degraded_reason,
  }
}

export function orderedActorOpsV2StandbyCandidates(candidates: ActorOpsV2CandidateView[]) {
  return [...candidates].sort((left, right) => {
    const priorityDifference = (left.priority ?? Number.MAX_SAFE_INTEGER) - (right.priority ?? Number.MAX_SAFE_INTEGER)
    return priorityDifference || left.candidate_id.localeCompare(right.candidate_id)
  })
}

export function actorOpsV2CandidateLabel(candidate: ActorOpsV2CandidateView | null) {
  if (!candidate) return '未配置'
  const displayName = stringValue(candidate.store_metadata?.display_name)
  if (displayName && !isOpaqueActorIdentity(displayName)) return displayName
  return actorOpsV2PublicActorSlug(candidate) || '商城信息待更新'
}

/** Only return an Apify storefront slug when it is a human-readable public identity. */
export function actorOpsV2PublicActorSlug(candidate: ActorOpsV2CandidateView | null) {
  const actorSlug = stringValue(candidate?.store_metadata?.actor_slug)
  return actorSlug && !isOpaqueActorIdentity(actorSlug) ? actorSlug : null
}

export function actorOpsV2CandidateHasPublicIdentity(candidate: ActorOpsV2CandidateView) {
  return actorOpsV2CandidateLabel(candidate) !== '商城信息待更新'
}

export function actorOpsV2CandidateIssueLabel(candidate: ActorOpsV2CandidateView) {
  const labels: Record<NonNullable<ActorOpsV2CandidateView['issue_code']>, string> = {
    actor_deleted: 'Actor 已下架',
    build_unavailable: '固定 Build 不可用',
    contract_invalid: '输出结构不兼容',
    repeated_start_rejection: '连续未能启动',
    stale_regression: '返回内容早于来源水位',
    candidate_failure: '最近一次运行失败',
  }
  return candidate.issue_code ? labels[candidate.issue_code] : null
}

export function actorOpsV2MappingIssueLabel(candidate: ActorOpsV2CandidateView) {
  const labels: Record<NonNullable<ActorOpsV2CandidateView['mapping_issue_code']>, string> = {
    missing_post_author_handle: '缺少帖子作者用户名字段',
    output_not_content_items: 'Actor 输出不是帖子列表，可能只返回用户资料或关注关系',
    missing_target_input: '缺少可注入订阅账号的输入字段',
    missing_required_input_value: 'Actor 有必填输入，但公开 Schema 未提供可验证的默认值或枚举',
    missing_post_id: '缺少帖子 ID 字段',
    missing_post_url: '缺少帖子 URL 字段',
    missing_post_published_at: '缺少帖子发布时间字段',
    missing_post_text: '缺少帖子正文内容字段',
    missing_source_identity: '缺少可核验的来源身份字段',
    ambiguous_output: '输出字段含义不明确，无法安全映射',
    wrong_actor_type: 'Actor 可用，但用途不是此来源的新发布内容',
    nested_content_items: '发布内容位于嵌套列表，等待系统展开适配',
    named_dataset_required: '视频写入独立 Dataset，等待系统选择对应数据集',
    output_schema_incomplete: '公开输出 Schema 不完整，需要样本验证字段',
    target_identity_derivable: '来源身份可由订阅目标补齐，等待系统适配',
    relative_published_at: '发布时间为相对时间，等待稳定时间转换适配',
    nested_extraction_failed: '未能从 Dataset 的嵌套列表安全展开发布内容',
    mixed_rows_unclassified: 'Dataset 同时包含多种记录，仍有发布型记录无法安全分类',
    dataset_run_unbound: 'Dataset 无法与本次 Actor Run 精确绑定，系统不会读取历史同名数据集',
    dataset_expansion_overflow: 'Dataset 展开后超过 100 条安全验证上限',
    observed_mapping_failed: '真实 Dataset 已读取，但两轮字段重映射仍无法完成严格证明',
    output_sample_required: '公开输出 Schema 缺失，需要一次真实样本完成字段映射',
    input_plan_invalid: '输入 Schema 无法生成安全、可渲染的实测输入',
    route_type_uncertain: '无法确认 Actor 是否输出此来源的新发布内容',
    sample_dataset_empty: '实测 Dataset 为空，无法证明发布字段合同',
  }
  return candidate.mapping_issue_code ? labels[candidate.mapping_issue_code] : null
}

export function actorOpsV2CandidateStatusLabel(candidate: ActorOpsV2CandidateView) {
  if (candidate.operational_status === 'confirmed_failure') return '已确认故障'
  if (candidate.operational_status === 'recent_failure') return '最近失败'
  return null
}

export function compareActorOpsV2ReplacementCandidates(left: ActorOpsV2CandidateView, right: ActorOpsV2CandidateView) {
  const qualityFields = ['total_users', 'monthly_active_users', 'rating', 'review_count', 'bookmark_count'] as const
  for (const field of qualityFields) {
    const difference = (right.store_metadata?.[field] ?? -1) - (left.store_metadata?.[field] ?? -1)
    if (difference !== 0) return difference
  }
  const maintainedDifference = Number(Boolean(right.store_metadata?.maintained_by_apify)) - Number(Boolean(left.store_metadata?.maintained_by_apify))
  if (maintainedDifference !== 0) return maintainedDifference
  const leftReady = left.evidence_progress.verified_bindings >= left.evidence_progress.required_bindings ? 0 : 1
  const rightReady = right.evidence_progress.verified_bindings >= right.evidence_progress.required_bindings ? 0 : 1
  return leftReady - rightReady || actorOpsV2CandidateLabel(left).localeCompare(actorOpsV2CandidateLabel(right), 'zh-CN')
}

export function actorOpsV2PriceLabel(candidate: ActorOpsV2CandidateView | null) {
  const pricing = candidate?.store_metadata?.pricing?.[0]
  if (!pricing) return '商城价格待更新'
  const price = numberValue(pricing.minimumChargeUsd) ?? numberValue(pricing.pricePerRunUsd) ?? numberValue(pricing.pricePerUnitUsd)
  const unit = stringValue(pricing.unitName)
  const estimated = stringValue(pricing.pricingPeriod) === 'estimated'
  return price === null ? '商城价格以 Apify 为准' : `$${price.toFixed(2)}${estimated ? ' / 单次估算' : unit ? ` / ${unit}` : ''}`
}

export function compactNumber(value: number | null) {
  if (value === null) return '—'
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function isOpaqueActorIdentity(value: string) {
  return /^[A-Za-z0-9]{12,}$/.test(value)
}
