import type {
  NotificationChannel,
  NotificationChannelStates,
  WebhookProvider,
  WebhookProviderOption,
} from '../../api/types'
import {
  Button,
  Card,
  Checkbox,
  Description,
  FieldError,
  Input,
  Label,
  StatusIndicator,
  TextField,
} from '../../design-system'
import { notificationTestLabel } from './notificationModel'
import { WebhookProviderFields } from './WebhookProviderFields'

export type NotificationDestinationDrafts = Record<NotificationChannel, string>
export type NotificationDestinationErrors = Partial<Record<NotificationChannel | 'signing', string>>

type ChannelSettingsView = {
  channel_states: NotificationChannelStates
  webhook_provider_options: WebhookProviderOption[]
}

const labels: Record<NotificationChannel, string> = {
  email: '邮箱',
  webhook: 'Webhook',
  telegram: 'Telegram',
}

function formatLastTest(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function NotificationChannelCards({
  idPrefix,
  settings,
  selectedChannels,
  destinations,
  webhookProvider,
  providerTouched,
  signingEnabled,
  signingSecret,
  errors,
  readOnly,
  busy,
  testingChannel,
  channelDirty,
  destinationNoun = '通知',
  onChannelChange,
  onDestinationChange,
  onProviderChange,
  onSigningEnabledChange,
  onSigningSecretChange,
  onTest,
}: {
  idPrefix: string
  settings: ChannelSettingsView
  selectedChannels: NotificationChannel[]
  destinations: NotificationDestinationDrafts
  webhookProvider: WebhookProvider
  providerTouched: boolean
  signingEnabled: boolean
  signingSecret: string
  errors: NotificationDestinationErrors
  readOnly: boolean
  busy: boolean
  testingChannel: NotificationChannel | null
  channelDirty: (channel: NotificationChannel) => boolean
  destinationNoun?: string
  onChannelChange: (channel: NotificationChannel, selected: boolean) => void
  onDestinationChange: (channel: NotificationChannel, value: string) => void
  onProviderChange: (provider: WebhookProvider) => void
  onSigningEnabledChange: (selected: boolean) => void
  onSigningSecretChange: (value: string) => void
  onTest: (channel: NotificationChannel) => void
}) {
  const webhookState = settings.channel_states.webhook
  const signingConfigured = webhookState.signing_secret_configured
    && webhookProvider === webhookState.provider
    && !providerTouched

  return <div className="grid min-w-0 gap-4 min-[900px]:grid-cols-3">
    {(['email', 'webhook', 'telegram'] as const).map((channel) => {
      const state = settings.channel_states[channel]
      const selected = selectedChannels.includes(channel)
      const lastTestTime = formatLastTest(state.last_tested_at)
      const testReady = (
        !readOnly
        && state.configured
        && state.available
        && !channelDirty(channel)
        && !busy
      )
      return <Card
        key={channel}
        variant="transparent"
        className="grid min-w-0 content-start gap-3 p-4"
        data-notification-channel={channel}
      >
        <div className="flex min-w-0 flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <Card.Title>{labels[channel]}</Card.Title>
            <Card.Description className="mt-1">
              {state.configured ? '已配置；接收目标不会回显。' : `尚未配置${labels[channel]}接收目标。`}
            </Card.Description>
          </div>
          <StatusIndicator
            label={!state.configured ? '待配置' : !state.available ? '服务暂停' : '已配置'}
            tone={!state.configured ? 'neutral' : !state.available ? 'warning' : 'success'}
          />
        </div>

        <Checkbox
          isSelected={selected}
          isDisabled={readOnly}
          onChange={(value) => onChannelChange(channel, value)}
        >
          <Checkbox.Content>
            <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
            启用{labels[channel]}渠道
          </Checkbox.Content>
        </Checkbox>

        {channel === 'email' && <TextField
          fullWidth
          value={destinations.email}
          onChange={(value) => onDestinationChange('email', value)}
          isDisabled={readOnly || busy}
          isInvalid={Boolean(errors.email)}
          isRequired={selected && !state.configured}
        >
          <Label>{destinationNoun === '告警' ? '告警收件邮箱' : '收件邮箱'}</Label>
          <Input
            type="email"
            autoComplete="email"
            placeholder={state.configured ? '留空保持当前配置' : 'name@example.com'}
          />
          <Description>仅在非空时提交；保存后不会回显。</Description>
          {errors.email && <FieldError>{errors.email}</FieldError>}
        </TextField>}

        {channel === 'webhook' && <WebhookProviderFields
          idPrefix={`${idPrefix}-webhook`}
          provider={webhookProvider}
          options={settings.webhook_provider_options}
          destination={destinations.webhook}
          configured={state.configured && webhookProvider === webhookState.provider && !providerTouched}
          providerExplicit={webhookState.provider_explicit}
          signingEnabled={signingEnabled}
          signingSecret={signingSecret}
          signingConfigured={signingConfigured}
          destinationRequired={selected && !state.configured}
          destinationLabel={destinationNoun === '告警' ? '告警 Webhook 地址' : 'Webhook 地址'}
          fieldError={errors.webhook ?? ''}
          signingError={errors.signing ?? ''}
          readOnly={readOnly || busy}
          onProviderChange={onProviderChange}
          onDestinationChange={(value) => onDestinationChange('webhook', value)}
          onSigningEnabledChange={onSigningEnabledChange}
          onSigningSecretChange={onSigningSecretChange}
        />}

        {channel === 'telegram' && <TextField
          fullWidth
          value={destinations.telegram}
          onChange={(value) => onDestinationChange('telegram', value)}
          isDisabled={readOnly || busy}
          isInvalid={Boolean(errors.telegram)}
          isRequired={selected && !state.configured}
        >
          <Label>{destinationNoun === '告警' ? '告警 Chat ID' : 'Telegram Chat ID'}</Label>
          <Input
            type="password"
            autoComplete="off"
            placeholder={state.configured ? '留空保持当前配置' : '-1001234567890 或 @channel'}
          />
          <Description>支持有符号整数或 @channel；只写入服务端，提交即清空。</Description>
          {errors.telegram && <FieldError>{errors.telegram}</FieldError>}
        </TextField>}

        {state.configured && !state.available && <Description>
          {labels[channel]}服务暂停只影响本渠道；其他已启用渠道继续投递，恢复后不补发。
        </Description>}
        <div className="mt-auto grid gap-2 border-t border-separator pt-3">
          <p className="type-meta text-muted">
            {notificationTestLabel(state.last_test_status, {
              channel,
              verificationMode: channel === 'webhook' ? webhookState.verification_mode : 'http_status',
            })}
            {lastTestTime ? ` · ${lastTestTime}` : ''}
          </p>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            isDisabled={!testReady}
            onPress={() => onTest(channel)}
          >
            {testingChannel === channel ? '发送中…' : `发送${labels[channel]}测试`}
          </Button>
        </div>
      </Card>
    })}
  </div>
}
