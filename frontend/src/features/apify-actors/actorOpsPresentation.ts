import { ApiError } from '../../api/client'
import type { ApifyActorRouteSummary, ApifyActorSlotName } from '../../api/types'
import { slotWorkflowPresentation } from './actorOpsSlotWorkflowPresentation'

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
  if (['apify_actor_canary_approval_stale', 'apify_actor_canary_plan_conflict', 'apify_actor_route_generation_conflict', 'apify_actor_manual_candidate_stale', 'apify_actor_pool_stage_stale', 'apify_actor_pool_stage_precondition_incomplete', 'apify_actor_active_pool_incomplete'].includes(code)) {
    return { reason: '配置刚刚更新', impact: '本次选择没有应用，也没有启动新的付费验证；现有线路继续运行。', next: '页面会刷新，请重新选择 Actor。', diagnostic: code }
  }
  if (code === 'apify_actor_discovery_active') {
    return { reason: '当前 Actor 的升级检查已在进行', impact: '系统没有重复创建任务，不会启动 Actor 或产生费用；兼容版本继续运行。', next: '等待页面自动刷新；检查完成后，当前 Actor 会排在候选列表最前。', diagnostic: code }
  }
  if (code === 'apify_actor_validation_profile_unchanged') {
    return { reason: '验证参数没有变化', impact: '系统已阻止原样重复启动 Actor，本次费用为 $0；现有配置保持不变。', next: '按页面建议增加等待时间或样本数；若没有有效参数可调，请更换 Actor。', diagnostic: code }
  }
  if (['apify_actor_unexpected_empty', 'apify_actor_suspicious_empty', 'suspicious_empty', 'systemic_empty'].includes(code)) {
    return { reason: '运行已完成，但没有返回内容', impact: '它不会加入主备；现有配置保持不变。若已启动验证，只会保留已终结费用。', next: '若页面允许，扩大验证样本到 3 或 5 条；否则选择另一个 Actor。', diagnostic: code }
  }
  if (code === 'apify_actor_target_identity_mismatch') {
    return {
      reason: 'Actor 返回的内容不属于本次目标',
      impact: '返回结果无法证明来自正在校验的账号或频道；可能是推荐内容、默认账号、旧缓存或字段映射错误。它不会加入主备，现有线路不变。',
      next: '不要原样重复验证。请选择另一个 Actor；只有该 Actor 的 Build、Schema 或字段映射变化后才值得重试。',
      diagnostic: code,
    }
  }
  if (['apify_actor_contract_mismatch', 'apify_actor_metadata_only', 'apify_actor_placeholder', 'apify_actor_identity_mismatch', 'apify_actor_revision_output_incompatible'].includes(code)) {
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
  if (['apify_start_outcome_unknown', 'apify_actor_start_outcome_unknown', 'apify_run_reconcile_required', 'apify_worker_restart_reconcile_required'].includes(code)) {
    return { reason: '无法确认 Actor 是否已启动', impact: '为避免重复扣费，系统已锁定新的验证。', next: '系统会免费核对已知 Run；刷新状态即可，不要重试付费请求。', diagnostic: code }
  }
  if (['apify_run_status_unavailable', 'apify_actor_run_status_unavailable', 'apify_actor_validation_reconcile_required'].includes(code)) {
    return { reason: '原运行结果还没有确认', impact: '系统没有重新启动 Actor，也没有将它加入主备；现有配置保持不变。', next: '免费重新核对同一个 Run 和 Dataset；不要重新发起付费验证。', diagnostic: code }
  }
  if (['apify_actor_validation_failed', 'source_validation_failed', 'source_binding_changed'].includes(code)) {
    return { reason: 'Actor 验证未完成', impact: '系统没有将它加入主备；现有配置保持不变。', next: '刷新状态后选择另一个候选；系统不会自动重试。', diagnostic: code }
  }
  if (code === 'network_error') {
    return { reason: '暂时无法读取 Actor 状态', impact: '系统没有确认任何配置变化；现有运行不受影响。', next: '检查网络后重试读取。' }
  }
  return { reason: '操作未完成', impact: '系统没有确认配置变化；现有线路继续运行。', next: fallbackNext, diagnostic: code === 'unknown_error' ? undefined : code }
}

export type ActorOpsTaskTab = 'pool' | 'sources' | 'operations'

export type GuidedNextAction =
  | 'start_discovery'
  | 'select_candidates'
  | 'approve_canary'
  | 'approve_activation'
  | 'open_sources'
  | 'open_operations'
  | 'refresh'
  | 'none'

export const taskTabs = new Set<ActorOpsTaskTab>(['pool', 'sources', 'operations'])
export const routeProfileOrder = ['x/profile/items', 'instagram/profile/items', 'youtube/channel/items'] as const

export const routeProductNames: Record<string, { label: string; description: string }> = {
  'x/profile/items': { label: 'X 用户动态', description: 'Actor 主抓取' },
  'instagram/profile/items': { label: 'Instagram 主页内容', description: 'Actor 主抓取' },
  'youtube/channel/items': { label: 'YouTube 频道视频', description: 'Actor 主抓取' },
}

export type WorkflowPresentation = {
  title: string
  description: string
  status: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
  action: GuidedNextAction
  cta?: string
}

const workflowPresentation: Record<string, WorkflowPresentation> = {
  setup_discovery_required: {
    title: '尚未建立 Actor 主备',
    description: '系统会先免费搜索并检查候选，不会启动 Actor 或产生费用。',
    status: '未建立', tone: 'neutral', action: 'start_discovery', cta: '开始建立主备',
  },
  setup_discovery_running: {
    title: '正在搜索可用 Actor',
    description: '系统正在检查商城候选、固定 Build 和输出结构；无需停留本页。',
    status: '建立中', tone: 'warning', action: 'none',
  },
  setup_candidate_selection_required: {
    title: '选择 2 个 Actor 建立标准主备',
    description: '候选已经完成免费检查。选择 2 个不同发布者的 Actor；第三路可在运行后主动补充。',
    status: '待选择', tone: 'warning', action: 'select_candidates', cta: '选择 Actor',
  },
  setup_canary_approval_required: {
    title: '候选已选择，下一步验证标准主备',
    description: '系统会严格按你的选择串行验证 2 个 Actor；验证期间不会提前启用。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认付费验证',
  },
  setup_canary_running: {
    title: '正在验证完整主备',
    description: '系统正在按计划串行执行；没有成功确认前不会切换线路。',
    status: '待付费验证', tone: 'warning', action: 'none',
  },
  setup_activation_approval_required: {
    title: '标准主备验证通过',
    description: '确认后以 2/3 标准主备开始运行；第三路可后续由管理员主动补充。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认启用',
  },
  backup_2_discovery_required: {
    title: '可选：补充第三路备用',
    description: '当前两路已达到标准模式并可自动切换。只有管理员点击后才会免费搜索第三路。',
    status: '标准可用', tone: 'neutral', action: 'start_discovery', cta: '主动补充备用 2',
  },
  backup_2_discovery_running: {
    title: '正在寻找第三路备用',
    description: '现有两路继续运行，不受补位影响。',
    status: '补位中', tone: 'warning', action: 'none',
  },
  backup_2_candidate_selection_required: {
    title: '选择第三个备用 Actor',
    description: '选择 1 个不与现有主备重复的候选。确认生效前，现有两路始终继续运行。',
    status: '两路可用', tone: 'warning', action: 'select_candidates', cta: '补充备用 Actor',
  },
  backup_2_canary_approval_required: {
    title: '第三路候选已就绪',
    description: '第一步：确认一次限额付费验证；现有两路继续运行。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认第三路验证',
  },
  backup_2_canary_running: {
    title: '正在验证第三路备用',
    description: 'Route 和已批准来源正在串行预验证；现有两路继续服务。',
    status: '补位中', tone: 'warning', action: 'none',
  },
  backup_2_activation_approval_required: {
    title: '第三路验证通过',
    description: '第二步：确认加入备用 2；下一任务热加载，现有两路不变。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认补位生效',
  },
  legacy_discovery_required: {
    title: '升级当前 3 个 Actor',
    description: '只检查上面正在使用的 3 个 Actor，为它们固定新版 Build 并旁路验证。任一 Actor 无法安全升级就停止，不选择替补。',
    status: '兼容模式', tone: 'warning', action: 'start_discovery', cta: '开始升级当前 3 个 Actor',
  },
  legacy_discovery_running: {
    title: '正在升级当前 3 个 Actor',
    description: '系统正在为上面的 Actor 生成固定 Build；当前兼容线路继续运行，不会重复创建搜索任务。',
    status: '兼容模式', tone: 'warning', action: 'none',
  },
  legacy_candidate_selection_required: {
    title: '确认当前 Actor 升级',
    description: '只允许上面的 3 个当前 Actor 进入新版方案；三者必须全部通过，并覆盖至少两个发布者。',
    status: '兼容模式', tone: 'warning', action: 'select_candidates', cta: '继续升级当前 Actor',
  },
  legacy_canary_approval_required: {
    title: '新版主备候选已就绪',
    description: '第一步：确认新版方案和现有来源的串行付费验证；兼容线路继续运行。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认新版验证',
  },
  legacy_canary_running: {
    title: '正在验证新版主备',
    description: '旁路方案正在完成 Route 与来源预验证；当前兼容池始终可见。',
    status: '兼容模式', tone: 'warning', action: 'none',
  },
  legacy_activation_approval_required: {
    title: '新版主备验证通过',
    description: '第二步：确认后原子切换到固定 Build；运行中的任务仍使用旧 generation。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看并确认切换',
  },
  compatibility_candidate_selection_available: {
    title: '严格配置不足，可降低要求继续',
    description: '功能优先兼容模式只启用 1 路实测可用 Actor。Actor 数量、发布者分散和 Canary 前元数据要求会降低；身份、真实非空内容、受控输入和 $0.02 费用上限仍保留。',
    status: '可兼容启用', tone: 'warning', action: 'select_candidates', cta: '降低要求继续',
  },
  compatibility_discovery_required: {
    title: '兼容候选仍不足',
    description: '可继续免费扩大候选召回；不会自动启动 Actor 或产生费用。',
    status: '兼容检查', tone: 'warning', action: 'start_discovery', cta: '更新兼容候选',
  },
  compatibility_discovery_running: {
    title: '正在检查兼容候选',
    description: '当前线路保持不变；免费检查不会启动 Actor。',
    status: '兼容检查', tone: 'warning', action: 'none',
  },
  compatibility_candidate_selection_required: {
    title: '选择 1 个兼容 Actor',
    description: '选择一个候选进入真实非空 Canary。系统仍执行身份、发布时间、正文、占位内容与费用边界检查。',
    status: '待选择', tone: 'warning', action: 'select_candidates', cta: '选择兼容 Actor',
  },
  compatibility_canary_approval_required: {
    title: '兼容候选已就绪',
    description: '确认后只串行试跑所选 Actor；必须返回参考账号的真实非空内容才能继续。',
    status: '待付费验证', tone: 'warning', action: 'approve_canary', cta: '查看并确认兼容试跑',
  },
  compatibility_canary_running: {
    title: '正在验证兼容 Actor',
    description: '验证期间不会切换现有线路，也不会自动换候选或重试。',
    status: '兼容验证中', tone: 'warning', action: 'none',
  },
  compatibility_activation_approval_required: {
    title: '单路兼容验证通过',
    description: '再次确认后启用 1/3 兼容池；后续仍可不停机补充主备并升级回标准模式。',
    status: '待生效', tone: 'success', action: 'approve_activation', cta: '查看兼容风险并确认启用',
  },
  compatibility_operational: {
    title: 'X 已以单路兼容模式运行',
    description: '功能已经可用，但当前没有主备冗余。可在不中断现有抓取的情况下继续免费寻找标准双路候选。',
    status: '兼容启用（1/3）', tone: 'warning', action: 'start_discovery', cta: '升级为标准主备',
  },
  compatibility_standard_discovery_running: {
    title: '正在旁路准备标准主备',
    description: '单路兼容 Actor 继续运行；免费检查不会切换线路或产生 Actor 费用。',
    status: '兼容启用（1/3）', tone: 'warning', action: 'none',
  },
  compatibility_standard_candidate_selection_required: {
    title: '标准主备候选已就绪',
    description: '选择 2 个不同发布者的 Actor 旁路验证；最终确认前单路兼容配置保持不变。',
    status: '兼容启用（1/3）', tone: 'warning', action: 'select_candidates', cta: '选择标准主备',
  },
  probation_observing: {
    title: '主备配置完成',
    description: '所选 Actor 已验证并可运行；稳定性认证会在后台继续，不会阻塞配置，也无需手动转正。',
    status: '配置完成', tone: 'success', action: 'none',
  },
  source_validation_required: {
    title: '有来源等待启用',
    description: '主备已可运行，下一步只需验证具体来源。',
    status: '配置完成', tone: 'success', action: 'open_sources', cta: '前往来源启用',
  },
  runtime_degraded_monitoring: {
    title: '正在使用备用线路',
    description: '系统已自动切换并持续观察恢复；无需手动换路。',
    status: '已切换备用', tone: 'warning', action: 'none',
  },
  blocked_unknown_start: {
    title: '需要先核对 Apify 运行',
    description: '启动结果不确定，系统已阻止继续付费。请先核对状态；不要重复提交。',
    status: '需要核对', tone: 'danger', action: 'refresh', cta: '刷新核对结果',
  },
  budget_blocked: {
    title: '费用保护已暂停',
    description: '系统已停止新的付费启动；可在运行与告警中查看当前状态。',
    status: '费用已暂停', tone: 'danger', action: 'open_operations', cta: '查看运行与费用',
  },
  complete: {
    title: '主备配置完成',
    description: '三路可用，故障时系统自动串行切换。',
    status: '配置完成', tone: 'success', action: 'none',
  },
}

const unknownWorkflowPresentation: WorkflowPresentation = {
  title: '状态需要刷新',
  description: '当前没有可安全执行的操作。刷新后仍会以服务端状态为准。',
  status: '需要核对',
  tone: 'warning',
  action: 'refresh',
  cta: '刷新状态',
}

export function routeWorkflowPresentation(
  kind: string,
  minimumActors: number,
  operationSlot?: ApifyActorSlotName | null,
): WorkflowPresentation {
  void minimumActors
  const slotWorkflow = slotWorkflowPresentation(kind, operationSlot)
  if (slotWorkflow) return slotWorkflow
  const standard = workflowPresentation[kind] ?? unknownWorkflowPresentation
  return standard
}

export function routeProfileId(
  route: Pick<ApifyActorRouteSummary, 'platform' | 'target_type' | 'capability'>,
): string {
  return `${route.platform}/${route.target_type}/${route.capability}`
}
