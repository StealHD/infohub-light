import type { InformationRuleConfig } from '../../api/informationAutomationService'

export const emptyInformationRule = (): InformationRuleConfig => ({
  schema_version: 2, name: '新的自动化', source_ids: [], target_id: null, requirement: '', model: null,
  trigger: { kind: 'each', count: 5, max_wait_seconds: 3600, interval_seconds: 3600,
    time: '08:00', weekdays: [], timezone: 'Asia/Shanghai' },
})
export function triggerLabel(trigger: InformationRuleConfig['trigger']): string {
  if (trigger.kind === 'each') return '每条到达时分析'
  if (trigger.kind === 'count') return `累计 ${trigger.count} 条${trigger.max_wait_seconds ? `，最长等待 ${trigger.max_wait_seconds / 60} 分钟` : ''}`
  if (trigger.kind === 'interval') return `每 ${trigger.interval_seconds / 60} 分钟`
  return `${trigger.weekdays.length ? '每周' + trigger.weekdays.map((day) => '一二三四五六日'[day]).join('、') : '每天'} ${trigger.time} · ${trigger.timezone}`
}
export const ruleStateLabels = { draft: '草稿', active: '已启用', paused: '已暂停', archived: '已归档' }
export const judgmentLabels = {
  pending: '等待判断', judging: '正在判断', matched: '命中', not_matched: '未命中',
  insufficient: '证据不足', failed: '判断失败', cancelled: '已取消', quota_wait: '等待判断额度',
}
export const notificationLabels = {
  not_required: '无需通知', pending: '等待发送', sending: '正在发送', sent: '已发送',
  failed: '发送失败', unknown: '发送结果未知 · 不自动重发', cancelled: '已取消发送', quota_wait: '等待通知额度',
}
export const reminderReasonLabels: Record<string, string> = {
  analysis_model_unavailable: '所选 OpenClaw 模型暂不可用，队列已保留。请刷新模型目录。',
  analysis_thinking_unavailable: '所选模型不支持当前推理强度，请重新选择。',
  configuration_upgraded: '已升级为统一分析，请选择模型并重新确认。',
  semantic_model_unavailable: '独立模型服务不可用，本次未通知。请检查 connector 配置。',
  semantic_lease_expired: '判断连接中断，正在按重试上限恢复；超过上限将停止本次判断。',
  invalid_model_output: '模型返回不符合要求或文章依据无效，本次未通知。',
  connector_revoked: '独立判断授权已撤销，请修复后重新确认。',
  daily_notification_limit: '今日通知额度已用完，队列保留至明日。',
  daily_semantic_limit: '今日语义判断额度已用完，队列保留至明日。',
  agent_binding_changed: '个人 Agent 接入已变化，请重新确认。',
  agent_binding_required: '个人 Agent 接入失效，请先修复接入。',
  notification_target_changed: '通知目标配置已变化，请重新确认。',
  notification_transport_changed: '通知发送服务已变化，请重新确认。',
  notification_target_unavailable: '通知服务暂不可用，请检查通知设置。',
  subscription_required: '订阅已停用或不可用，请检查来源。',
  delivery_interrupted: '发送过程被中断，结果无法确认，不自动重发。',
  unverified_receipt: '没有可验证的发送回执，不自动重发。',
  input_incomplete: '输入内容不完整，无法作出完整判断。',
  literal_keywords: '根据已保存的关键词条件判断。',
}
export function completeRule(config: InformationRuleConfig): boolean {
  return Boolean(config.name.trim() && config.source_ids.length && config.target_id && config.requirement.trim() && config.model)
}
export function linesToTerms(value: string): string[] {
  return value.split('\n').map((line) => line.trim()).filter(Boolean)
}
export { informationDraftReferences } from './informationDraftReferences'
