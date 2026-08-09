import { ApiError } from '../../api/client'
import type { ApifyActorAlertEvent } from '../../api/types'

export const APIFY_ACTOR_ROUTE_REFRESH_MS = 30_000

export const actorAlertEventLabels: Record<ApifyActorAlertEvent, string> = {
  actor_switched: '自动切换 Actor',
  route_exhausted: '三个 Actor 全部不可用',
  quota_low: 'Apify 额度偏低',
  budget_blocked: '额度耗尽或费用熔断',
  start_outcome_unknown: 'Actor 启动结果未知',
  recovered: '故障恢复',
}

const actorReasonLabels: Record<string, string> = {
  placeholder_records: '检测到占位或诊断记录',
  placeholder_record: '检测到占位或诊断记录',
  apify_actor_placeholder: '检测到占位或诊断记录',
  apify_actor_error_record: 'Actor 返回了错误控制记录',
  apify_actor_contract_mismatch: 'Actor 返回格式发生严重变化',
  apify_actor_deleted: 'Actor 已删除或不可访问',
  apify_actor_build_unavailable: 'Actor 构建当前不可用',
  apify_actor_unexpected_empty: '多个正常账号出现异常空结果',
  systemic_empty: '多个正常账号同时返回异常空结果',
  actor_unavailable: 'Actor 当前不可用',
  actor_disabled: 'Actor 已由管理员禁用',
  actor_enabled: 'Actor 已由管理员启用',
  admin_reorder: '管理员调整了 Actor 顺序',
  admin_disable: '管理员禁用了 Actor',
  admin_enable: '管理员启用了 Actor',
  initial_policy: '已应用默认 Actor 路由策略',
  all_candidates_unavailable: '三个 Actor 当前均不可用',
  canary_succeeded: '付费试跑通过',
  canary_failed: '付费试跑未通过',
  actor_canary_passed: '付费试跑通过，已进入试运行',
  canary_required: '需要先完成付费试跑',
  probation_passed: '48 小时试运行已达到稳定性要求',
  probation_failed: '48 小时试运行未达到稳定性要求',
  quota_low: 'Apify 可用额度偏低',
  quota_exhausted: 'Apify 可用额度已耗尽',
  failed_spend_limit: '失败调用费用达到保护上限',
  start_outcome_unknown: 'Actor 启动结果未知',
  apify_run_reconcile_required: '已启动任务需要先完成对账',
  run_reconciled: '已完成启动任务对账',
  budget_fuse_released: '费用保护冷却已经结束',
  actor_recovered: 'Actor 已通过连续恢复验证',
  route_recovered: '抓取路线已经恢复',
  recovered: '抓取路线已经恢复',
}

const actorErrorLabels: Record<string, string> = {
  forbidden: '当前账户没有管理 Apify Actor 的权限。',
  invalid_request: '请求内容无效，请刷新后重试。',
  invalid_apify_actor_route: 'Actor 路由配置无效，请刷新后重试。',
  apify_actor_route_conflict: 'Actor 路由刚刚发生变化，已刷新最新状态，请重试。',
  apify_actor_route_generation_conflict: 'Actor 路由刚刚发生变化，已刷新最新状态，请重试。',
  apify_actor_job_active: '同一抓取任务已有 Actor 正在执行，请稍后重试。',
  apify_actor_route_blocked: 'Actor 路由需要人工核对，暂不能执行此操作。',
  apify_actor_route_exhausted: '当前没有可用的 Actor。',
  apify_actor_budget_blocked: '费用保护已生效，暂不能发起付费调用。',
  apify_actor_quota_unknown: 'Apify 额度快照已过期，刷新全部账号额度后才能发起付费调用。',
  apify_actor_candidate_unavailable: '该 Actor 当前不能执行此操作。',
  apify_actor_canary_source_required: '请先选择一个 X 账号进行试跑。',
  apify_actor_source_requires_pool_upgrade: '当前来源仍在使用兼容版本；请先到“主备配置”升级 Actor，再回来启用来源。',
  apify_actor_canary_unavailable: '当前不能发起 Actor 试跑。',
  apify_actor_canary_active: '这个 Actor 已有一项试跑正在等待或执行。',
  apify_actor_revision_output_incompatible: '该固定 Build 已确认只返回元数据或不符合内容合同，不能重复付费试跑。',
  apify_actor_active_pool_uncertified: '快速主备至少需要两个成功试跑的固定 Build；完整 2+1 的前两槽仍需认证。请刷新候选状态后重试。',
  apify_actor_canary_required: '该 Actor 需要先完成付费试跑，才能启用。',
  apify_actor_routing_disabled: 'Apify Actor 路由当前未启用。',
  invalid_apify_actor_alert_settings: '告警设置无效，请检查后重试。',
  invalid_notification_destination: '接收地址格式无效，请检查后重试。',
  invalid_webhook_provider: 'Webhook 类型无效，请重新选择。',
  invalid_webhook_url_for_provider: 'Webhook 地址与所选类型不匹配。',
  webhook_url_required_for_provider_change: '更换 Webhook 类型时，请重新输入对应地址。',
  invalid_webhook_signing_secret: '签名 Secret 格式无效，请重新输入。',
  webhook_signing_not_supported: '所选 Webhook 类型不支持签名校验。',
  notification_destination_required: '当前告警方式还没有配置接收地址。',
  notification_channel_unavailable: '当前告警方式暂不可用，请检查邮件服务或改用 Webhook。',
  apify_actor_alert_test_failed: '测试告警发送失败，请检查接收端后重试。',
  apify_actor_alert_test_outcome_unknown: '测试告警结果未知，请勿重复发送；请先确认接收端。',
  apify_actor_alert_test_rate_limited: '测试告警发送过于频繁，请稍后再试。',
}

export function safeActorActionError(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) return actorErrorLabels[caught.code] ?? fallback
  if (caught instanceof TypeError) return '网络请求失败，请检查连接后重试。'
  return fallback
}

export function actorReasonLabel(code: string | null): string {
  if (!code) return '尚未记录'
  return actorReasonLabels[code] ?? '状态已更新，请查看当前可用路线。'
}

export function formatActorDateTime(value: string | null): string {
  if (!value) return '尚未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function formatActorUsd(value: number | null, precise = false): string {
  if (value === null || !Number.isFinite(value)) return '暂无可信数据'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: precise ? 2 : 2,
    maximumFractionDigits: precise ? 5 : 2,
  }).format(value)
}

export function formatActorPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return '暂无可信数据'
  return new Intl.NumberFormat('zh-CN', {
    style: 'percent',
    maximumFractionDigits: 1,
  }).format(Math.min(1, Math.max(0, value)))
}

export function formatEstimatedDays(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value < 0) return '暂无可信数据'
  if (value < 1) return '不足 1 天'
  return `约 ${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value)} 天`
}
