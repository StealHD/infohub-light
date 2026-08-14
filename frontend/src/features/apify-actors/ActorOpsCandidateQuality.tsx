import type { ApifyActorPoolCandidate } from '../../api/types'

export function ActorStoreQuality({ quality }: { quality: ApifyActorPoolCandidate['store_quality'] | undefined }) {
  if (!quality || (quality.rating === null && quality.rating_count === null && quality.user_count === null)) return null
  const users = quality.user_count === null ? null : quality.user_count >= 1000 ? `${Number((quality.user_count / 1000).toFixed(1))}K` : String(quality.user_count)
  return <span className="mt-1 block type-meta text-muted">商城质量：{quality.rating === null ? '评分未提供' : `${quality.rating.toFixed(1)} 分`}{quality.rating_count === null ? '' : `（${quality.rating_count} 条评分）`}{users === null ? '' : ` · ${users} 使用人数`}</span>
}
