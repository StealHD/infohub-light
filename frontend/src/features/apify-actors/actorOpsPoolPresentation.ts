import type {
  ApifyActorPoolCandidate,
  ApifyActorRevisionSummary,
  ApifyActorRouteSummary,
} from '../../api/types'
import { formatActorUsd } from './apifyActorModel'

export function actorPricingLabel(revision: ApifyActorRevisionSummary): string {
  const pricing = revision.pricing
  if (!pricing || pricing.billing_unit === 'unknown') return '定价快照不可用'
  if (pricing.billing_unit === 'free') return '免费 Actor'
  const minimum = pricing.unit_price_min_usd
  const maximum = pricing.unit_price_max_usd
  const price = minimum === null || minimum === undefined
    ? '标价未提供'
    : maximum !== null && maximum !== undefined && Math.abs(maximum - minimum) > 1e-9
      ? `${formatActorUsd(minimum, true)}–${formatActorUsd(maximum, true)}`
      : formatActorUsd(minimum, true)
  const unit = pricing.billing_unit === 'dataset_item' ? '每 Dataset 行' : '每计费事件'
  const cap = pricing.minimum_run_cap_usd
  return `${price} ${unit}${cap !== null && cap !== undefined
    ? ` · Actor 最低 Run 上限 ${formatActorUsd(cap, true)}`
    : ''}`
}

export function poolCandidatePricingLabel(candidate: ApifyActorPoolCandidate): string {
  const pricing = candidate.pricing
  if (!pricing || pricing.billing_unit === 'unknown') return '计费方式待验证计划确认'
  if (pricing.billing_unit === 'free') return 'Actor 标价免费'
  if (pricing.billing_unit === 'dataset_item') return '按结果条目计费'
  return '按 Actor 计费事件计费'
}

export function poolCandidateUnavailableLabel(reason: string | null | undefined): string {
  if (reason === 'actor_already_active') return '已经在当前主备中'
  if (reason === 'candidate_validation_in_progress') return '另一次验证正在进行'
  if (reason === 'candidate_exact_build_missing') return '尚未固定可验证版本'
  if (reason === 'candidate_not_validated') return '基础检查尚未通过'
  if (reason === 'actor_upgrade_inspection_running') return '正在为这个当前 Actor 生成安全新版'
  if (reason === 'actor_upgrade_revision_unavailable') return '尚未通过安全升级检查；当前兼容版本继续运行'
  if (reason === 'actor_validation_sample_limit_reached') return '3 条样本仍未通过，升级已停止'
  if (reason === 'actor_validation_retry_not_permitted') return '上次失败不允许通过提价、换 Actor 或重复付费绕过'
  if (reason === 'compatibility_preflight_required') return '这是旧发现结果，缺少免费 Build、输入和输出合同检查；请先免费更新候选'
  if (reason === 'actor_exact_build_missing') return '没有可固定的成功 Build，不能安全配置'
  if (reason === 'actor_schema_unverifiable') return 'Build 没有可验证的输入或输出 Schema'
  if (reason === 'actor_input_schema_unmappable') return 'Build 的 X 账号输入无法安全生成'
  if (reason === 'build_input_validation_failed' || reason === 'actor_input_validation_rejected') return '官方免费输入校验未通过'
  if (reason === 'actor_output_contract_unverifiable') return '输出 Schema 不能证明会返回真实帖子'
  if (reason === 'actor_x_profile_semantics_mismatch' || reason === 'actor_x_profile_semantics_unverifiable') return 'Actor 不是可验证的 X 账号帖子抓取器'
  if (reason === 'actor_price_above_route_cap') return '官方标价可能超过本次单次费用上限'
  if (reason === 'actor_requires_limited_permissions') return '需要受限权限的公开 Actor'
  if (reason === 'actor_deprecated') return 'Actor 已弃用'
  return '当前不满足安全条件'
}

export function routeMinimumActors(
  route: Pick<ApifyActorRouteSummary, 'min_runtime_healthy'> & {
    actual_min_runtime_healthy?: number
  },
): number {
  const value = route.actual_min_runtime_healthy ?? route.min_runtime_healthy
  return Math.min(3, Math.max(1, Math.trunc(value)))
}
