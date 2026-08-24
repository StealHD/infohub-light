import type { ApifyActorAlertEvent, Job } from '../../api/types'

export type ActorOpsIssueActionTarget = 'apify-runs' | 'route' | 'route-cost' | 'secrets' | 'logs'

export type ActorOpsIssuePresentation = {
  reason: string
  impact: string
  next: string
  action?: { label: string; target: ActorOpsIssueActionTarget }
}

const actorOpsIssues: Record<ApifyActorAlertEvent, ActorOpsIssuePresentation> = {
  actor_switched: {
    reason: '系统已切换到已验证的备用 Actor。',
    impact: '当前来源会继续更新；主备用量需要管理员确认。',
    next: '查看对应 Route 的主备和最近运行详情。',
    action: { label: '查看相关 Route', target: 'route' },
  },
  route_exhausted: {
    reason: '当前 Route 没有可安全运行的 Candidate。',
    impact: '该 Route 的新内容会延迟；系统不会回退到旧线路。',
    next: '检查已核验 Binding 和主备，再按现有流程恢复。',
    action: { label: '查看相关 Route', target: 'route' },
  },
  quota_low: {
    reason: '用于 ActorOps 的额度接近保护阈值。',
    impact: '后续验证或维护可能暂停，系统不会自动扩大额度。',
    next: '确认工作区 Key 的额度与轮换状态。',
    action: { label: '查看密钥额度', target: 'secrets' },
  },
  budget_blocked: {
    reason: '当前费用条件不满足安全上限。',
    impact: '验证或替换没有继续执行，系统不会自动放宽费用。',
    next: '在对应 Route 中检查单次费用上限和候选方案。',
    action: { label: '查看 Route 费用设置', target: 'route-cost' },
  },
  start_outcome_unknown: {
    reason: '无法确认 Actor 是否已启动。',
    impact: '为避免重复扣费，后续付费验证已锁定。',
    next: '先核对 Apify 运行记录，再刷新安全执行轨迹；不要重试。',
    action: { label: '打开 Apify 运行记录', target: 'apify-runs' },
  },
  recovered: {
    reason: '系统已确认 Route 恢复。',
    impact: '当前获取已恢复，历史记录保持不变。',
    next: '无需人工处理；后续告警会继续记录。',
  },
}

export function presentActorOpsIncidentIssue(event: ApifyActorAlertEvent): ActorOpsIssuePresentation {
  return actorOpsIssues[event]
}

export function presentActorOpsJobIssue(job: Pick<Job, 'error_code'>): ActorOpsIssuePresentation {
  const code = String(job.error_code || '')
  if (['apify_start_outcome_unknown', 'apify_run_reconcile_required'].includes(code)) return actorOpsIssues.start_outcome_unknown
  if (['actorops_v2_budget_blocked', 'apify_actor_quota_unknown'].includes(code)) return actorOpsIssues.budget_blocked
  if (code === 'actorops_route_disabled') return actorOpsIssues.route_exhausted
  if (['actorops_v2_migration_required', 'actorops_v2_unavailable'].includes(code)) {
    return { reason: 'ActorOps 暂不可用', impact: '此任务没有启动远端 Actor，也不会产生新费用。', next: '恢复服务或完成迁移后，再查看安全执行轨迹。', action: { label: '查看 ActorOps 日志', target: 'logs' } }
  }
  if (['apify_run_status_unavailable', 'actorops_v2_attempt_unrecoverable'].includes(code)) {
    return { reason: '原运行结果还没有确认', impact: '系统不会重新启动 Actor；当前主备没有变化。', next: '返回 ActorOps 免费核对同一个安全执行轨迹。', action: { label: '查看 ActorOps 日志', target: 'logs' } }
  }
  return { reason: 'Actor 配置没有完成', impact: '系统没有确认主备变化；现有线路继续运行。', next: '返回 ActorOps 查看当前状态和唯一下一步。', action: { label: '查看 ActorOps 日志', target: 'logs' } }
}
