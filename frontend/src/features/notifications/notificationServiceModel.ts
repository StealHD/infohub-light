import type { NotificationChannel, NotificationEmailProvider, NotificationService, NotificationServiceEmailTransportPatch } from '../../api/types'
import type { StatusBadgeTone } from '../../components/settings'

export const channelLabels: Record<NotificationChannel, string> = {
  telegram: 'Telegram',
  openclaw: 'OpenClaw',
  email: '邮箱',
  webhook: 'Webhook',
}

export const botTokenPattern = /^\d{5,20}:[A-Za-z0-9_-]{30,100}$/
export const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
export const validTopic = (value: string) => /^\d+$/u.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0

export function destinationLabel(channel: NotificationChannel): string {
  if (channel === 'email') return '收件邮箱'
  if (channel === 'telegram') return '群组或会话 Chat ID'
  if (channel === 'openclaw') return '收件目标'
  return 'Webhook 地址'
}

export function serviceStatus(service: NotificationService): string {
  if (!service.configured) return '未配置'
  if (!service.transport_ready && service.channel !== 'webhook') return '共享凭据待验证'
  if (service.last_test_status === 'failed') return '测试失败'
  if (service.last_test_status === 'unknown') return '结果未知'
  if (service.last_test_status !== 'sent') return '待验证'
  if (!service.enabled) return '已暂停'
  return service.available ? '可用' : '暂不可用'
}

export function serviceStatusTone(service: NotificationService): StatusBadgeTone {
  if (service.available && service.enabled) return 'success'
  if (service.last_test_status === 'failed' || !service.configured) return 'danger'
  if (!service.enabled || service.last_test_status !== 'sent') return 'warning'
  return 'neutral'
}

export function serviceUnavailableReason(service: NotificationService): string {
  if (!service.configured) return '接收地址尚未保存'
  if (!service.transport_ready && service.channel !== 'webhook') {
    if (service.channel === 'openclaw') return 'OpenClaw Gateway 渠道尚未就绪'
    return service.channel === 'telegram'
      ? '共享 Bot Token 尚未通过验证'
      : '共享邮件凭据尚未通过验证'
  }
  if (service.last_test_status === 'unknown') return '上次测试结果未知，请确认接收端后再手动测试'
  if (service.last_test_status === 'failed') return '上次测试失败，请编辑后重试'
  if (service.last_test_status !== 'sent') return '当前配置尚未测试'
  if (!service.enabled) return '服务已暂停'
  return '服务暂不可用'
}

export type EmailDraft = {
  provider: NotificationEmailProvider
  senderEmail: string
  senderName: string
  credential: string
  region: string
  smtpUsername: string
}

export const emptyEmailDraft: EmailDraft = {
  provider: 'qq',
  senderEmail: '',
  senderName: 'Inscope',
  credential: '',
  region: '',
  smtpUsername: '',
}

export function emailTransportPayload(draft: EmailDraft): NotificationServiceEmailTransportPatch {
  const usesSes = draft.provider === 'amazon_ses'
  return {
    provider: draft.provider,
    sender_email: draft.senderEmail.trim(),
    sender_name: draft.senderName.trim(),
    region: usesSes ? draft.region.trim() : null,
    smtp_username: usesSes ? draft.smtpUsername.trim() : null,
    ...(draft.credential ? { credential: draft.credential } : {}),
  }
}
