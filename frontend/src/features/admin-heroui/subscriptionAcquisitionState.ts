import type { CatalogSource, FeedSchedule, Subscription } from '../../api/types'

export function sourceAcquisitionIssue(source: CatalogSource) {
  const state = source.acquisition
  if (!state || state.allowed) return null
  if (state.status === 'disabled' || state.reason === 'source_disabled') {
    return { label: '来源已停用', detail: '请检查来源和订阅设置，再由管理员确认 Bilibili 主备状态。' }
  }
  if (state.status === 'unavailable') {
    return { label: 'ActorOps 暂不可用', detail: '请联系管理员恢复 ActorOps 后再获取。' }
  }
  if (state.status === 'ready') {
    return { label: '等待主备启用', detail: '请由管理员在 ActorOps 启用已验证的 Bilibili 主备路线。' }
  }
  return { label: '等待 Actor 验证', detail: 'Bilibili 主备尚未就绪，请由管理员在 ActorOps 完成验证后再获取。' }
}

const intervalLabel = (minutes?: number) => {
  if (!minutes) return '周期未知'
  return minutes < 60 ? `每 ${minutes} 分钟` : `每 ${minutes / 60} 小时`
}

export function subscriptionUpdateDetails(source: CatalogSource, subscription: Subscription, globalSchedule?: FeedSchedule) {
  if (!subscription.enabled) return ['更新：订阅已停用']
  const issue = sourceAcquisitionIssue(source)
  if (issue) return [`更新：${issue.label}`]
  if (!source.enabled) return ['更新：订阅已停用']
  const schedule = subscription.schedule
  const usesSourceSchedule = Boolean(schedule?.enabled)
  const details = usesSourceSchedule
    ? ['更新：单源', intervalLabel(schedule?.interval_minutes)]
    : globalSchedule?.enabled
      ? ['更新：全局', intervalLabel(globalSchedule.interval_minutes)]
      : globalSchedule ? ['更新：跟随全局', '全局已关闭'] : ['更新：跟随全局']
  const nextRunAt = usesSourceSchedule ? schedule?.next_run_at : globalSchedule?.enabled ? globalSchedule.next_run_at : null
  const parsed = nextRunAt ? new Date(nextRunAt) : null
  if (parsed && !Number.isNaN(parsed.getTime())) {
    details.push(`下次 ${parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`)
  }
  return details
}
