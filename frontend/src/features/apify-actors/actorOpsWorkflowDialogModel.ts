import type {
  ApifyActorCanaryPlan,
  ApifyActorRevisionSummary,
  ApifyActorRouteDetail,
  ApifyActorSlotName,
} from '../../api/types'
import { routeProductNames, routeProfileId } from './actorOpsPresentation'

export type ActorOpsBatchConfirmationView = {
  compatibility: boolean
  routeLabel: string
  maxTotalChargeUsd: number
  sourceCount: number
  sourceValidationCount: number
  ready: boolean
  items: Array<{
    key: string
    actorLabel: string
    publisher: string
    authorizedCapUsd: number
    alreadyValidated: boolean
    validationProfile: {
      timeoutSeconds: number
      sampleItems: number
      maxChargeUsd: number
    } | null
  }>
}

export type ActorOpsActivationConfirmationView = {
  goal: 'initial_pool' | 'complete_third' | 'upgrade_legacy' | 'compatibility_single' | 'add_slot' | 'replace_slot'
  minimumActors: number
  currentSlotCount: number
}

export type ActorOpsSourceCanaryConfirmationView = {
  actorLabel: string
  buildLabel: string
  capUsd: number
}

export type ActorOpsRollbackConfirmationView = {
  revisionLabel: string
  slot: ApifyActorSlotName
  canConfirm: boolean
}

export function toBatchConfirmationView(
  plan: ApifyActorCanaryPlan | null,
): ActorOpsBatchConfirmationView | null {
  if (!plan) return null
  const routeLabel = routeProductNames[routeProfileId(plan)]?.label
    || `${plan.platform} / ${plan.target_type} / ${plan.capability}`
  return {
    compatibility: plan.goal === 'compatibility_single',
    routeLabel,
    maxTotalChargeUsd: plan.max_total_charge_usd,
    sourceCount: plan.source_count ?? 0,
    sourceValidationCount: plan.source_validation_count ?? 0,
    ready: plan.ready,
    items: plan.items.map((item) => ({
      key: String(item.ordinal),
      actorLabel: item.actor_public_name || `${item.publisher} Actor`,
      publisher: item.publisher,
      authorizedCapUsd: item.authorized_cap_usd,
      alreadyValidated: Boolean(item.already_validated),
      validationProfile: item.validation_profile ? {
        timeoutSeconds: item.validation_profile.timeout_seconds,
        sampleItems: item.validation_profile.sample_items,
        maxChargeUsd: item.validation_profile.max_charge_usd,
      } : null,
    })),
  }
}

export function toActivationConfirmationView(
  route: ApifyActorRouteDetail | null,
): ActorOpsActivationConfirmationView | null {
  if (!route) return null
  const configuredMinimum = route.actual_min_runtime_healthy ?? route.min_runtime_healthy
  return {
    goal: route.workflow?.goal || 'initial_pool',
    minimumActors: Math.min(3, Math.max(1, Math.trunc(configuredMinimum))),
    currentSlotCount: route.slots.filter((slot) => slot.revision_id).length,
  }
}

export function toSourceCanaryConfirmationView(
  target: {
    revision: ApifyActorRevisionSummary
    buildLabel: string
    capUsd: number
  } | null,
): ActorOpsSourceCanaryConfirmationView | null {
  if (!target) return null
  return {
    actorLabel: target.revision.actor_public_name || `${target.revision.publisher} Actor`,
    buildLabel: target.buildLabel,
    capUsd: target.capUsd,
  }
}

export function toRollbackConfirmationView(
  revision: ApifyActorRevisionSummary | null,
  slot: ApifyActorSlotName,
  canConfirm: boolean,
): ActorOpsRollbackConfirmationView | null {
  return revision ? { revisionLabel: revision.revision_id, slot, canConfirm } : null
}
