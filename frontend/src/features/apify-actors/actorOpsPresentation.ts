import { ApiError } from '../../api/client'

export type HumanActorError = {
  reason: string
  impact: string
  next: string
  diagnostic?: string
}

export function humanActorError(
  caught: unknown,
  fallbackNext = '刷新状态后重新操作。',
): HumanActorError {
  const code = caught instanceof ApiError
    ? caught.code
    : caught instanceof TypeError
      ? 'network_error'
      : 'unknown_error'
  if (['apify_actor_canary_approval_stale', 'apify_actor_canary_plan_conflict', 'apify_actor_route_generation_conflict', 'apify_actor_manual_candidate_stale', 'apify_actor_pool_stage_stale'].includes(code)) {
    return { reason: '配置刚刚更新', impact: '本次选择没有应用，也没有启动新的付费验证；现有线路继续运行。', next: '页面会刷新，请重新选择 Actor。', diagnostic: code }
  }
  if (['apify_actor_unexpected_empty', 'apify_actor_suspicious_empty', 'systemic_empty', 'apify_actor_contract_mismatch', 'apify_actor_metadata_only', 'apify_actor_placeholder', 'apify_actor_target_identity_mismatch', 'apify_actor_revision_output_incompatible'].includes(code)) {
    return { reason: '这个 Actor 不适合当前来源', impact: '它不会加入主备；现有配置保持不变。若已启动验证，只会保留已终结费用。', next: '返回候选列表，选择另一个 Actor。', diagnostic: code }
  }
  if (['apify_actor_deleted', 'apify_actor_build_unavailable', 'apify_actor_revision_unavailable', 'apify_actor_revision_preflight_unavailable', 'apify_actor_manual_candidate_unavailable'].includes(code)) {
    return { reason: '这个 Actor 已不可用', impact: '验证未启动，费用为 $0；现有配置保持不变。', next: '返回候选列表，选择另一个 Actor。', diagnostic: code }
  }
  if (['apify_actor_budget_blocked', 'apify_actor_pool_stage_budget_invalid', 'apify_actor_canary_plan_budget_exceeded', 'apify_actor_quota_unknown'].includes(code)) {
    return { reason: '费用条件不满足', impact: '验证未启动或已暂停，系统不会自动放宽费用上限。', next: '选择更便宜的候选，或到“运行与告警”查看额度。', diagnostic: code }
  }
  if (['apify_actor_run_timed_out', 'apify_actor_canary_timeout'].includes(code)) {
    return { reason: 'Actor 验证超时', impact: '运行已停止且不会自动重试；费用以页面最终对账结果为准。', next: '费用完成对账后，重新选择并再次确认。', diagnostic: code }
  }
  if (['apify_start_outcome_unknown', 'apify_actor_start_outcome_unknown', 'apify_run_reconcile_required'].includes(code)) {
    return { reason: '无法确认 Actor 是否已启动', impact: '为避免重复扣费，系统已锁定新的验证。', next: '先在 Apify 控制台核对，再返回本页刷新状态；不要重试付费请求。', diagnostic: code }
  }
  if (code === 'network_error') {
    return { reason: '暂时无法读取 Actor 状态', impact: '系统没有确认任何配置变化；现有运行不受影响。', next: '检查网络后重试读取。' }
  }
  return { reason: '操作未完成', impact: '系统没有确认配置变化；现有线路继续运行。', next: fallbackNext, diagnostic: code === 'unknown_error' ? undefined : code }
}
