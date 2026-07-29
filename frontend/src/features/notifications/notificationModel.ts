import { ApiError } from '../../api/client'
import type { NotificationChannel, UserNotificationSettings } from '../../api/types'

export function notificationChannelConfigured(
  settings: Pick<UserNotificationSettings, 'email_configured' | 'webhook_configured'>,
  channel: NotificationChannel,
): boolean {
  return channel === 'email' ? settings.email_configured : settings.webhook_configured
}

export function notificationDestinationError({
  channel,
  destination,
  configured,
  enabled,
}: {
  channel: NotificationChannel
  destination: string
  configured: boolean
  enabled: boolean
}): string {
  const value = destination.trim()
  if (!value) {
    return enabled && !configured
      ? channel === 'email'
        ? '启用邮件通知前，请填写收件邮箱。'
        : '启用 Webhook 通知前，请填写 Webhook 地址。'
      : ''
  }
  if (channel === 'email') {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value) ? '' : '请输入有效的收件邮箱。'
  }
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'https:' ? '' : 'Webhook 地址必须使用 HTTPS。'
  } catch {
    return '请输入有效的 Webhook 地址。'
  }
}

const notificationErrorLabels: Record<string, string> = {
  invalid_notification_channel: '通知方式无效，请重新选择。',
  notification_destination_required: '当前通知方式还没有配置接收地址。',
  invalid_notification_destination: '接收地址格式无效，请检查后重试。',
  notification_channel_unavailable: '当前通知方式暂不可用，请联系管理员。',
  notification_test_failed: '测试通知发送失败，请检查接收端后重试。',
  notification_test_rate_limited: '测试通知发送过于频繁，请稍后再试。',
  invalid_email_transport_provider: '邮件服务商无效，请重新选择。',
  invalid_email_transport_sender: '发件邮箱与所选服务商不匹配。',
  invalid_email_transport_region: 'Amazon SES Region 格式无效。',
  invalid_email_transport_username: 'Amazon SES SMTP 用户名无效。',
  email_transport_test_required: '请先使用当前配置成功发送测试邮件。',
  email_transport_test_rate_limited: '测试邮件发送过于频繁，请等待 60 秒后重试。',
  email_transport_credential_unavailable: '发件凭据缺失或已变化，请重新保存凭据。',
  notification_email_authentication_failed: '邮箱服务拒绝登录，请检查授权码、App Password 或 SMTP 凭据。',
  notification_email_recipient_rejected: '邮箱服务拒绝测试收件人，请检查地址。',
  notification_email_rejected: '邮箱服务拒绝邮件，请检查发件地址和账号验证状态。',
  notification_email_unavailable: '暂时无法连接邮箱服务，请稍后重试。',
}

export function safeNotificationError(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) return notificationErrorLabels[caught.code] ?? fallback
  if (caught instanceof TypeError) return '网络请求失败，请检查连接后重试。'
  return fallback
}

export function notificationTestLabel(status: string | null): string {
  if (!status) return '尚未发送测试通知'
  if (status === 'succeeded' || status === 'success' || status === 'sent') return '最近一次测试请求已发送，请确认接收端'
  if (status === 'failed' || status === 'failure') return '最近一次测试发送失败'
  return '最近一次测试状态未知'
}
