export type NotificationChannel = 'email' | 'webhook' | 'telegram' | 'openclaw'

export type WebhookProvider =
  | 'generic_event'
  | 'generic_text'
  | 'feishu_lark_v2'
  | 'wecom'
  | 'dingtalk'
  | 'slack'
  | 'discord'

export type WebhookProviderOption = {
  provider: WebhookProvider
  label: string
  description: string
  url_hint: string
  signing: 'none' | 'optional'
  verification_mode: 'http_status' | 'provider_response'
}

export type NotificationChannelTestStatus = 'sent' | 'failed' | 'unknown' | null

export type NotificationChannelState = {
  enabled: boolean
  configured: boolean
  available: boolean
  generation: number
  enabled_at: string | null
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
}

export type NotificationWebhookChannelState = NotificationChannelState & {
  provider: WebhookProvider
  provider_explicit: boolean
  signing_secret_configured: boolean
  verification_mode: 'http_status' | 'provider_response'
}

export type NotificationChannelStates = {
  email: NotificationChannelState
  webhook: NotificationWebhookChannelState
  telegram: NotificationChannelState
}

export type NotificationTargetScope = 'private' | 'shared'

export type NotificationTarget = {
  id: string
  name: string
  scope: NotificationTargetScope
  channel: NotificationChannel
  configured: boolean
  enabled: boolean
  available: boolean
  transport_ready: boolean
  config_generation: number
  activation_generation: number
  enabled_at: string | null
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
  can_edit: boolean
  can_test: boolean
  can_enable: boolean
  usage: {
    user_binding_count: number
    alert_binding_count: number
    preferred_active_delivery_count: number
    alert_active_delivery_count: number
  }
  updated_at: string | null
  webhook_provider?: WebhookProvider
  webhook_signing_secret_configured?: boolean
  webhook_verification_mode?: 'http_status' | 'provider_response'
  telegram_topic_configured?: boolean
}

export type NotificationService = NotificationTarget & {
  legacy_private: boolean
  can_validate: boolean
  openclaw_channel?: string
  openclaw_account?: string
}

export type OpenClawChannelAccount = { channel: string; channel_name?: string; account_id: string; account_name?: string; available: boolean }
export type OpenClawServiceCreate = { name: string; openclaw_channel: string; openclaw_account: string; destination: string; telegram_message_thread_id?: number | null }
export type OpenClawServicePatch = Partial<OpenClawServiceCreate> & { enabled?: boolean }

export type NotificationServiceEmailCredentialState = {
  configured: boolean
  ready: boolean
  generation: number
  provider: NotificationEmailProvider | null
  sender_name: string | null
  region: string | null
  sender_email_configured: boolean
  smtp_username_configured: boolean
  providers: NotificationEmailProviderOption[]
}

export type NotificationServices = {
  schema_version: 1
  services: NotificationService[]
  channel_credentials: {
    email: NotificationServiceEmailCredentialState
    telegram: {
      configured: boolean
      ready: boolean
      generation: number
    }
    webhook: {
      configured: true
      ready: true
      generation: 0
    }
  }
  webhook_provider_options: WebhookProviderOption[]
  can_manage: boolean
}

export type NotificationEmailProvider = 'qq' | 'netease' | 'gmail' | 'resend' | 'amazon_ses'

export type NotificationEmailProviderOption = {
  provider: NotificationEmailProvider
  label: string
  credential_label: string
  sender_hint: string
  requires_region: boolean
  requires_smtp_username: boolean
  smtp_port: 465
  security: 'ssl'
}

export type NotificationTargetCreate = {
  name: string
  scope: NotificationTargetScope
  channel: NotificationChannel
  email_address?: string
  webhook_url?: string
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string
  telegram_chat_id?: string
  telegram_message_thread_id?: number | null
}

export type NotificationTargetPatch = {
  name?: string
  enabled?: boolean
  email_address?: string
  webhook_url?: string
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string | null
  telegram_chat_id?: string
  telegram_message_thread_id?: number | null
}

export type NotificationServiceEmailTransportPatch = {
  provider?: NotificationEmailProvider
  sender_email?: string
  sender_name?: string
  credential?: string
  region?: string | null
  smtp_username?: string | null
}

export type NotificationServiceCreate = Omit<NotificationTargetCreate, 'scope'> & {
  scope?: 'shared'
  telegram_bot_token?: string
  email_transport?: NotificationServiceEmailTransportPatch
}

export type NotificationServicePatch = NotificationTargetPatch & {
  telegram_bot_token?: string
  email_transport?: NotificationServiceEmailTransportPatch
}

export type UserNotificationSettings = {
  schema_version: 4
  enabled: boolean
  target_ids: string[]
  selected_targets: NotificationTarget[]
  channels: NotificationChannel[]
  channel: NotificationChannel
  channel_states: NotificationChannelStates
  email_configured: boolean
  email_transport_ready: boolean
  webhook_configured: boolean
  webhook_provider: WebhookProvider
  webhook_provider_explicit: boolean
  webhook_signing_secret_configured: boolean
  webhook_verification_mode: 'http_status' | 'provider_response'
  webhook_provider_options: WebhookProviderOption[]
  telegram_configured: boolean
  telegram_transport_ready: boolean
  last_test_status: NotificationChannelTestStatus
  last_tested_at: string | null
  last_test_error_code: string | null
  updated_at: string | null
}

export type UserNotificationSettingsPatch = {
  enabled?: boolean
  target_ids?: string[]
  channels?: NotificationChannel[]
  channel?: NotificationChannel
  email_address?: string | null
  webhook_url?: string | null
  webhook_provider?: WebhookProvider
  webhook_signing_secret?: string | null
  telegram_chat_id?: string | null
}

export type NotificationTestResult = {
  sent: boolean
  enabled?: boolean
  channel: NotificationChannel
  target_id?: string
  provider?: WebhookProvider
  verification?: 'http_accepted' | 'provider_accepted'
}
