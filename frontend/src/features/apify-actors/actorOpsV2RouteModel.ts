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
    runtime_mode: route.runtime_mode === 'active' ? 'active' : 'disabled',
    normalized_retired_mode: normalizedRetiredMode,
    degraded_reason: normalizedRetiredMode
      ? 'actorops_v2_route_migration_required'
      : route.degraded_reason,
  }
}

export function actorOpsV2CandidateLabel(candidate: ActorOpsV2CandidateView | null) {
  if (!candidate) return '未配置'
  return candidate.store_metadata?.display_name || '待更新商城信息'
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
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value)
}

function numberValue(value: unknown) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function stringValue(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}
