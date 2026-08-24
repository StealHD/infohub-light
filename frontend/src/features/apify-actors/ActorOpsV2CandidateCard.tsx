import { actorOpsV2CandidateLabel, actorOpsV2PriceLabel, actorOpsV2PublicActorSlug, compactNumber, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

export function ActorOpsV2CandidateCard({ candidate, selected, onSelect }: {
  candidate: ActorOpsV2CandidateView
  selected: boolean
  onSelect: (candidate: ActorOpsV2CandidateView) => void
}) {
  const metadata = candidate.store_metadata
  const name = actorOpsV2CandidateLabel(candidate)
  const actorSlug = actorOpsV2PublicActorSlug(candidate)
  const metrics = [
    metadata?.rating === null || metadata?.rating === undefined ? null : `评分 ${metadata.rating}（${compactNumber(metadata.review_count ?? null)}）`,
    metadata?.bookmark_count === null || metadata?.bookmark_count === undefined ? null : `收藏 ${compactNumber(metadata.bookmark_count)}`,
    metadata?.total_users === null || metadata?.total_users === undefined ? null : `用户 ${compactNumber(metadata.total_users)}`,
  ].filter((value): value is string => Boolean(value))
  const creator = metadata?.developer_name?.trim()
  return <button
    type="button"
    aria-pressed={selected}
    aria-label={`选择 ${name}`}
    onClick={() => onSelect(candidate)}
    className={`grid gap-2 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:outline-2 focus-visible:outline-focus ${selected ? 'border-focus bg-surface-secondary' : 'border-separator hover:bg-surface-secondary'}`}
  >
    <div className="min-w-0">
      <span className="block type-control">{name}</span>
      {actorSlug && actorSlug !== name && <span className="mt-1 block truncate type-meta text-muted">{actorSlug}</span>}
    </div>
    {(metrics.length > 0 || creator || metadata?.maintained_by_apify) && <div className="flex flex-wrap gap-x-3 gap-y-1 type-meta text-muted">
      {metrics.map((metric) => <span key={metric}>{metric}</span>)}
      {creator && <span>开发者：{creator}</span>}
      {metadata?.maintained_by_apify && <span>Maintained by Apify</span>}
    </div>}
    <span className="type-meta text-muted">{actorOpsV2PriceLabel(candidate)} · 已核验 {candidate.evidence_progress.verified_bindings}/{candidate.evidence_progress.required_bindings}</span>
  </button>
}
