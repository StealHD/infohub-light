import { actorOpsV2CandidateLabel, actorOpsV2PriceLabel, actorOpsV2PublicActorSlug, compactNumber, type ActorOpsV2CandidateView } from './actorOpsV2RouteModel'

export function ActorOpsV2CandidateCard({ candidate, selected, onSelect, disabled = false, disabledReason = null, recommended = false }: {
  candidate: ActorOpsV2CandidateView
  selected: boolean
  onSelect: (candidate: ActorOpsV2CandidateView) => void
  disabled?: boolean
  disabledReason?: string | null
  recommended?: boolean
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
  const missingProofs = Math.max(0, candidate.evidence_progress.required_bindings - candidate.evidence_progress.verified_bindings)
  const stageLabel = candidate.system_usable
    ? '系统可用'
    : candidate.compatibility_stage === 'blocked'
      ? '已阻断'
      : candidate.compatibility_issue_code === 'binding_proof_incomplete' && missingProofs > 0
        ? `还需验证 ${missingProofs} 个来源`
    : candidate.compatibility_stage === 'static_ready'
      ? '可实测（尚未证明可替换）'
      : candidate.compatibility_stage === 'sample_required'
        ? '需要真实样本'
        : null
  return <button
    type="button"
    aria-pressed={selected}
    aria-label={`${disabled ? '不可选择' : '选择'} ${name}`}
    disabled={disabled}
    onClick={() => onSelect(candidate)}
    className={`grid gap-2 rounded-xl border p-3 text-left outline-none transition-colors focus-visible:outline-2 focus-visible:outline-focus disabled:cursor-not-allowed disabled:opacity-70 ${selected ? 'border-focus bg-surface-secondary' : 'border-separator enabled:hover:bg-surface-secondary'}`}
  >
    <div className="min-w-0">
      <span className="flex min-w-0 flex-wrap items-center gap-2 type-control"><span>{name}</span>{recommended && <span className="type-meta text-accent">系统推荐</span>}</span>
      {actorSlug && actorSlug !== name && <span className="mt-1 block truncate type-meta text-muted">{actorSlug}</span>}
    </div>
    {(metrics.length > 0 || creator || metadata?.maintained_by_apify) && <div className="flex flex-wrap gap-x-3 gap-y-1 type-meta text-muted">
      {metrics.map((metric) => <span key={metric}>{metric}</span>)}
      {creator && <span>开发者：{creator}</span>}
      {metadata?.maintained_by_apify && <span>Maintained by Apify</span>}
    </div>}
    <span className="type-meta text-muted">{actorOpsV2PriceLabel(candidate)} · 已核验 {candidate.evidence_progress.verified_bindings}/{candidate.evidence_progress.required_bindings}{stageLabel ? ` · ${stageLabel}` : ''}</span>
    {disabledReason && <span className="type-meta text-danger">不可替换：{disabledReason}</span>}
  </button>
}
