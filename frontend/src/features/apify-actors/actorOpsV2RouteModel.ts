export type ActorOpsV2CandidateView = {
  candidate_id: string
  build_number: string | null
  lifecycle: string
  assignment: string
  priority: number | null
  generation: number
  store_metadata: ActorOpsV2StoreMetadata | null
  evidence_progress: { verified_bindings: number; required_bindings: number }
}

export type ActorOpsV2StoreMetadata = {
  actor_slug: string
  display_name: string
  short_description: string | null
  developer_name: string | null
  maintained_by_apify: boolean
  rating: number | null
  review_count: number | null
  bookmark_count: number | null
  total_users: number | null
  monthly_active_users: number | null
  pricing: Array<Record<string, unknown>>
  last_modified_at: string | null
  observed_at: string
  generation: number
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
  return price === null ? '商城价格以 Apify 为准' : `$${price.toFixed(2)}${unit ? ` / ${unit}` : ''}`
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
