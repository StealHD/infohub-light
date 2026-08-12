import { ApiError } from '../../api/client'

const notificationErrorLabels: Record<string, string> = {
  invalid_notification_channel: '通知方式无效，请重新选择。',
  notification_destination_required: '当前通知方式还没有配置接收地址。',
  invalid_notification_destination: '接收地址格式无效，请检查后重试。',
  invalid_webhook_provider: 'Webhook 类型无效，请重新选择。',
  invalid_webhook_url_for_provider: 'Webhook 地址与所选类型不匹配。',
  webhook_url_required_for_provider_change: '更换 Webhook 类型时，请重新输入对应地址。',
  invalid_webhook_signing_secret: '签名 Secret 格式无效，请重新输入。',
  webhook_signing_not_supported: '所选 Webhook 类型不支持签名校验。',
  notification_channel_unavailable: '当前通知方式暂不可用，请联系管理员。',
  notification_test_failed: '测试通知发送失败，请检查接收端后重试。',
  notification_test_outcome_unknown: '测试通知结果未知，请勿重复发送；请先确认接收端。',
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
  invalid_telegram_bot_token: 'Telegram Bot Token 格式无效，请重新输入。',
  invalid_telegram_chat_id: 'Telegram Chat ID 无效，请输入有符号整数或 @channel。',
  telegram_transport_test_required: '请先使用当前配置成功发送 Telegram 测试消息。',
  telegram_transport_test_rate_limited: 'Telegram 测试消息发送过于频繁，请稍后再试。',
  telegram_transport_token_unavailable: 'Bot Token 缺失或已变化，请重新保存。',
  telegram_transport_not_configured: '请先保存 Telegram Bot Token。',
  telegram_transport_changed: 'Telegram Bot 配置已变化，请重新发送测试消息。',
  notification_telegram_authentication_failed: 'Telegram 拒绝 Bot Token，请检查配置。',
  notification_telegram_destination_rejected: 'Telegram 拒绝目标会话，请确认 Bot 已加入并有发送权限。',
  notification_telegram_provider_rejected: 'Telegram 拒绝消息，请检查目标会话和 Bot 权限。',
  notification_telegram_rate_limited: 'Telegram 发送过于频繁，请稍后再试。',
  notification_telegram_response_invalid: 'Telegram 返回无法验证，结果未知；请先检查目标会话。',
  notification_telegram_unavailable: 'Telegram 服务暂时不可用，请稍后重试。',
  notification_telegram_outcome_unknown: 'Telegram 发送结果未知，不会自动重发；请先检查目标会话。',
}

export function safeNotificationError(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError) return notificationErrorLabels[caught.code] ?? fallback
  if (caught instanceof TypeError) return '网络请求失败，请检查连接后重试。'
  return fallback
}
