import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationChannel,
  NotificationTarget,
  NotificationTestResult,
  UserNotificationSettings,
  UserNotificationSettingsPatch,
  WebhookProvider,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Card,
  Checkbox,
  Description,
  LoadingState,
  Switch,
} from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'
import {
  NotificationChannelCards,
  type NotificationDestinationDrafts,
  type NotificationDestinationErrors,
} from './NotificationChannelCards'
import {
  notificationDestinationError,
  safeNotificationError,
} from './notificationModel'

const emptyDestinations = (): NotificationDestinationDrafts => ({
  email: '',
  webhook: '',
  telegram: '',
})

function sameChannels(left: NotificationChannel[], right: NotificationChannel[]): boolean {
  return left.length === right.length && left.every((channel, index) => channel === right[index])
}

export function NotificationSettingsForm({
  settings,
  onSave,
  onTest,
  readOnly = false,
}: {
  settings: UserNotificationSettings
  onSave: (patch: UserNotificationSettingsPatch) => Promise<UserNotificationSettings>
  onTest: (channel: NotificationChannel) => Promise<NotificationTestResult>
  readOnly?: boolean
}) {
  const webhookState = settings.channel_states.webhook
  const [enabled, setEnabled] = useState(settings.enabled)
  const [channels, setChannels] = useState<NotificationChannel[]>(settings.channels)
  const [destinations, setDestinations] = useState<NotificationDestinationDrafts>(emptyDestinations)
  const [webhookProvider, setWebhookProvider] = useState<WebhookProvider>(webhookState.provider)
  const [providerTouched, setProviderTouched] = useState(false)
  const [signingEnabled, setSigningEnabled] = useState(webhookState.signing_secret_configured)
  const [signingSecret, setSigningSecret] = useState('')
  const [errors, setErrors] = useState<NotificationDestinationErrors>({})
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testingChannel, setTestingChannel] = useState<NotificationChannel | null>(null)
  const signingDirty = signingEnabled !== webhookState.signing_secret_configured || Boolean(signingSecret.trim())
  const dirty = (
    enabled !== settings.enabled
    || !sameChannels(channels, settings.channels)
    || Object.values(destinations).some((value) => Boolean(value.trim()))
    || providerTouched
    || signingDirty
  )
  const busy = saving || testingChannel !== null

  function channelDirty(channel: NotificationChannel): boolean {
    if (channels.includes(channel) !== settings.channel_states[channel].enabled) return true
    if (destinations[channel].trim()) return true
    return channel === 'webhook' && (providerTouched || signingDirty)
  }

  function setDestination(channel: NotificationChannel, value: string) {
    setDestinations((current) => ({ ...current, [channel]: value }))
    setErrors((current) => ({ ...current, [channel]: undefined }))
    setRequestError('')
  }

  function toggleChannel(channel: NotificationChannel, selected: boolean) {
    setChannels((current) => selected
      ? current.includes(channel) ? current : [...current, channel]
      : current.filter((item) => item !== channel))
    setErrors((current) => ({ ...current, [channel]: undefined }))
    setRequestError('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || busy) return
    const submittedDestinations = {
      email: destinations.email.trim(),
      webhook: destinations.webhook.trim(),
      telegram: destinations.telegram.trim(),
    }
    const submittedSigningSecret = signingSecret.trim()
    setDestinations(emptyDestinations())
    setSigningSecret('')
    setErrors({})
    setRequestError('')

    if (enabled && channels.length === 0) {
      setRequestError('启用新内容通知时，请至少选择一种通知渠道。')
      return
    }
    const nextErrors: NotificationDestinationErrors = {}
    for (const channel of ['email', 'webhook', 'telegram'] as const) {
      const configured = channel === 'webhook'
        ? settings.channel_states.webhook.configured
          && webhookProvider === webhookState.provider
          && !providerTouched
        : settings.channel_states[channel].configured
      if (channels.includes(channel) || submittedDestinations[channel]) {
        const error = notificationDestinationError({
          channel,
          destination: submittedDestinations[channel],
          configured,
          enabled: channels.includes(channel),
        })
        if (error) nextErrors[channel] = error
      }
    }
    if (
      channels.includes('webhook')
      && !webhookState.provider_explicit
      && (providerTouched || submittedDestinations.webhook)
      && !submittedDestinations.webhook
    ) {
      nextErrors.webhook = '升级旧 Webhook 配置时，请选择类型并重新输入对应地址。'
    }
    if (providerTouched && !submittedDestinations.webhook) {
      nextErrors.webhook = '选择或更换 Webhook 类型时，请重新输入对应地址。'
    }
    const signingConfigured = webhookState.signing_secret_configured
      && webhookProvider === webhookState.provider
      && !providerTouched
    if (signingEnabled && !signingConfigured && !submittedSigningSecret) {
      nextErrors.signing = '启用签名校验时需要填写签名 Secret。'
    }
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }

    setSaving(true)
    try {
      await onSave({
        enabled,
        channels,
        ...(submittedDestinations.email ? { email_address: submittedDestinations.email } : {}),
        ...(submittedDestinations.webhook ? { webhook_url: submittedDestinations.webhook } : {}),
        ...(submittedDestinations.telegram ? { telegram_chat_id: submittedDestinations.telegram } : {}),
        ...(providerTouched || submittedDestinations.webhook ? { webhook_provider: webhookProvider } : {}),
        ...(submittedSigningSecret ? { webhook_signing_secret: submittedSigningSecret } : {}),
        ...(!signingEnabled && webhookState.signing_secret_configured
          ? { webhook_signing_secret: null }
          : {}),
      })
      actionToast.success('消息通知设置已保存')
    } catch (caught) {
      const message = safeNotificationError(caught, '消息通知设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('消息通知设置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function sendTest(channel: NotificationChannel) {
    if (readOnly || busy || channelDirty(channel)) return
    setTestingChannel(channel)
    setRequestError('')
    try {
      const result = await onTest(channel)
      if (result.channel === 'email') {
        actionToast.success('测试邮件已发送', { description: '请检查当前收件邮箱。' })
      } else if (result.channel === 'telegram') {
        actionToast.success('Telegram 测试消息已发送', { description: '请检查当前目标会话。' })
      } else {
        actionToast.success(
          result.verification === 'provider_accepted' ? '平台已接受测试通知' : '测试通知请求已发送',
          {
            description: result.verification === 'provider_accepted'
              ? '平台业务响应已通过，请确认接收端实际展示。'
              : '接收端已返回 HTTP 成功状态，请确认实际处理。',
          },
        )
      }
    } catch (caught) {
      const message = safeNotificationError(caught, '测试通知发送失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('测试通知发送失败', { description: message })
    } finally {
      setTestingChannel(null)
    }
  }

  return <form className="grid min-w-0 gap-4" noValidate onSubmit={save}>
    {readOnly && <HeroNotice title="当前账户为只读权限" status="default" role="status">
      通知设置仅供查看，无法修改或发送测试通知。
    </HeroNotice>}
    <div className="grid gap-1">
      <Switch
        isSelected={enabled}
        isDisabled={readOnly}
        onChange={(value) => {
          setEnabled(value)
          setRequestError('')
        }}
      >
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用新内容通知</Switch.Content>
      </Switch>
      <Description>只对已在订阅设置中开启通知的来源生效；可同时选择多个渠道。</Description>
    </div>

    <NotificationChannelCards
      idPrefix="preferred-source"
      settings={settings}
      selectedChannels={channels}
      destinations={destinations}
      webhookProvider={webhookProvider}
      providerTouched={providerTouched}
      signingEnabled={signingEnabled}
      signingSecret={signingSecret}
      errors={errors}
      readOnly={readOnly}
      busy={busy}
      testingChannel={testingChannel}
      channelDirty={channelDirty}
      onChannelChange={toggleChannel}
      onDestinationChange={setDestination}
      onProviderChange={(provider) => {
        setWebhookProvider(provider)
        setProviderTouched(provider !== webhookState.provider || !webhookState.provider_explicit)
        setDestinations((current) => ({ ...current, webhook: '' }))
        setSigningEnabled(false)
        setSigningSecret('')
        setErrors((current) => ({ ...current, webhook: undefined, signing: undefined }))
        setRequestError('')
      }}
      onSigningEnabledChange={(value) => {
        setSigningEnabled(value)
        if (!webhookState.provider_explicit) setProviderTouched(true)
        setSigningSecret('')
        setErrors((current) => ({ ...current, signing: undefined }))
        setRequestError('')
      }}
      onSigningSecretChange={(value) => {
        setSigningSecret(value)
        setErrors((current) => ({ ...current, signing: undefined }))
        setRequestError('')
      }}
      onTest={(channel) => void sendTest(channel)}
    />

    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      <p>每个渠道独立配置、测试与投递；一个渠道暂停或失败不会阻断其他渠道。</p>
      <p className="mt-1">只推送开启后首次入库的新内容；已有历史、来源复用内容和停用期间内容不会补发。</p>
      <p className="mt-1">测试使用模拟内容，不会抓取来源，也不会改变新内容投递起点。</p>
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={readOnly || busy || !dirty}>
        {saving ? '保存中…' : '保存通知设置'}
      </Button>
    </div>
  </form>
}

export function HeroNotificationSettings({ queryEnabled = true }: { queryEnabled?: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: queryKeys.notificationSettings(user.id),
    queryFn: ({ signal }) => api.notificationSettings(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })
  const targets = useQuery({
    queryKey: queryKeys.notificationTargets(user.id),
    queryFn: ({ signal }) => api.notificationTargets(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })

  if (settings.isPending || targets.isPending) return <LoadingState label="正在读取消息通知设置" rows={2} />
  if (settings.isError || targets.isError || !settings.data || !targets.data) {
    return <HeroNotice title="消息通知设置读取失败，请刷新后重试。" />
  }

  const cacheKey = [
    settings.data.enabled,
    settings.data.target_ids.join(':'),
    targets.data.targets.map((target) => `${target.id}:${target.available}:${target.config_generation}`).join('|'),
  ].join(':')

  async function save(patch: UserNotificationSettingsPatch) {
    const updated = await api.updateNotificationSettings(patch)
    queryClient.setQueryData(queryKeys.notificationSettings(user.id), updated)
    return updated
  }

  return <NotificationTargetSelectionForm
    key={cacheKey}
    settings={settings.data}
    targets={targets.data.targets}
    onSave={save}
    readOnly={user.role === 'viewer'}
  />
}

export function NotificationTargetSelectionForm({
  settings,
  targets,
  onSave,
  readOnly = false,
}: {
  settings: UserNotificationSettings
  targets: NotificationTarget[]
  onSave: (patch: UserNotificationSettingsPatch) => Promise<UserNotificationSettings>
  readOnly?: boolean
}) {
  const [enabled, setEnabled] = useState(settings.enabled)
  const [targetIds, setTargetIds] = useState(settings.target_ids)
  const [saving, setSaving] = useState(false)
  const [requestError, setRequestError] = useState('')
  const dirty = enabled !== settings.enabled
    || targetIds.length !== settings.target_ids.length
    || targetIds.some((id, index) => id !== settings.target_ids[index])

  function toggleTarget(targetId: string, selected: boolean) {
    setTargetIds((current) => selected
      ? current.includes(targetId) ? current : [...current, targetId]
      : current.filter((id) => id !== targetId))
    setRequestError('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || saving || !dirty) return
    if (enabled && targetIds.length === 0) {
      setRequestError('启用新内容通知时，请至少选择一个通知目标。')
      return
    }
    setSaving(true)
    setRequestError('')
    try {
      await onSave({ enabled, target_ids: targetIds })
      actionToast.success('消息通知设置已保存')
    } catch (caught) {
      const message = safeNotificationError(caught, '消息通知设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('消息通知设置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  return <form className="grid min-w-0 gap-4" noValidate onSubmit={save}>
    {readOnly && <HeroNotice title="当前账户为只读权限" status="default" role="status">
      通知设置仅供查看，无法修改。
    </HeroNotice>}
    <div className="grid gap-1">
      <Switch
        isSelected={enabled}
        isDisabled={readOnly}
        onChange={(value) => {
          setEnabled(value)
          setRequestError('')
        }}
      >
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用新内容通知</Switch.Content>
      </Switch>
      <Description>只对订阅中已开启通知的来源生效；可以选择多个目标，也可以选择多个相同渠道的目标。</Description>
    </div>
    <div className="grid min-w-0 gap-3 min-[768px]:grid-cols-2">
      {targets.map((target) => <Card key={target.id} className="grid gap-2 p-4">
        <Checkbox
          isSelected={targetIds.includes(target.id)}
          isDisabled={readOnly}
          onChange={(selected) => toggleTarget(target.id, selected)}
        >
          <Checkbox.Content>
            <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
            <span>{target.name}</span>
          </Checkbox.Content>
        </Checkbox>
        <Card.Description>
          {target.scope === 'shared' ? '工作区共享' : '我的目标'} · {
            target.channel === 'email' ? '邮箱' : target.channel === 'telegram' ? 'Telegram' : 'Webhook'
          } · {target.available ? '可用' : target.enabled ? '暂不可用' : '已暂停'}
        </Card.Description>
      </Card>)}
      {targets.length === 0 && <HeroNotice
        title="暂无可选通知目标"
        status="warning"
        role="status"
      >请先在上方“通知目标”中创建、测试并启用一个目标。</HeroNotice>}
    </div>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      新启用目标、恢复目标或恢复总开关都只发送之后严格新增的内容，不补发停用期间或历史内容。
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={readOnly || saving || !dirty}>
        {saving ? '保存中…' : '保存通知设置'}
      </Button>
    </div>
  </form>
}
