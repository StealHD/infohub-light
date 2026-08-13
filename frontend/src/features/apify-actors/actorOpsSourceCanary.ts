import type {
  ApifyActorRouteDetail,
  ApifyActorSourceSupport,
} from '../../api/types'
import { routeProductNames } from './actorOpsPresentation'
import { actorPricingLabel } from './actorOpsPoolPresentation'
import type { CanaryApprovalTarget } from './HeroActorOpsControlPlane'

type Params = {
  detail: ApifyActorRouteDetail | undefined
  support: ApifyActorSourceSupport | undefined
  selectedProfileId: string
  setError: (value: string) => void
  setTarget: (value: CanaryApprovalTarget) => void
}

export function openActorOpsSourceCanary(
  slot: ApifyActorSourceSupport['slots'][number],
  { detail, support, selectedProfileId, setError, setTarget }: Params,
) {
  if (!detail || !support || !slot.revision_id) return
  const revision = detail.revisions.find((item) => item.revision_id === slot.revision_id)
  if (!revision) return
  setError('')
  setTarget({
    kind: 'source',
    sourceId: support.source_id,
    revision,
    expectedGeneration: support.generation,
    capUsd: Math.min(detail.per_run_cap_usd, support.remaining_budget_usd),
    routeKey: detail.route_key,
    routeLabel: routeProductNames[selectedProfileId]?.label || selectedProfileId,
    routeMode: detail.mode,
    actorPricingLabel: actorPricingLabel(revision),
    buildLabel: revision.build_number || revision.build_id || '未固定',
    approvalId: crypto.randomUUID(),
  })
}
