import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationChannel,
  NotificationTestResult,
  UserNotificationSettings,
  UserNotificationSettingsPatch,
  WebhookProvider,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Description,
  FieldError,
  Input,
  Label,
  LoadingState,
  Switch,
  TextField,
} from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import {
  notificationChannelConfigured,
  notificationDestinationError,
  notificationTestLabel,
  safeNotificationError,
} from './notificationModel'
import { WebhookProviderFields } from './WebhookProviderFields'

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

export function NotificationSettingsForm({
  settings,
  onSave,
  onTest,
  readOnly = false,
}: {
  settings: UserNotificationSettings
  onSave: (patch: UserNotificationSettingsPatch) => Promise<UserNotificationSettings>
  onTest: () => Promise<NotificationTestResult>
  readOnly?: boolean
}) {
  const [enabled, setEnabled] = useState(settings.enabled)
  const [channel, setChannel] = useState<NotificationChannel>(settings.channel)
  const [destination, setDestination] = useState('')
  const [webhookProvider, setWebhookProvider] = useState<WebhookProvider>(settings.webhook_provider)
  const [providerTouched, setProviderTouched] = useState(false)
  const [signingEnabled, setSigningEnabled] = useState(settings.webhook_signing_secret_configured)
  const [signingSecret, setSigningSecret] = useState('')
  const [fieldError, setFieldError] = useState('')
  const [signingError, setSigningError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const webhookConfigured = settings.webhook_configured
    && webhookProvider === settings.webhook_provider
    && !providerTouched
  const signingConfigured = settings.webhook_signing_secret_configured
    && webhookProvider === settings.webhook_provider
    && !providerTouched
  const configured = channel === 'webhook'
    ? webhookConfigured
    : notificationChannelConfigured(settings, channel)
  const persistedConfigured = notificationChannelConfigured(settings, settings.channel)
  const signingDirty = signingEnabled !== settings.webhook_signing_secret_configured
    || Boolean(signingSecret.trim())
  const dirty = enabled !== settings.enabled
    || channel !== settings.channel
    || Boolean(destination.trim())
    || (channel === 'webhook' && (providerTouched || signingDirty))
  const emailUnavailable = channel === 'email' && !settings.email_transport_ready
  const persistedEmailUnavailable = settings.channel === 'email' && !settings.email_transport_ready
  const testReady = !readOnly && persistedConfigured && !persistedEmailUnavailable && !dirty && !saving && !testing
  const lastTestTime = formatLastTest(settings.last_tested_at)

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || saving || testing) return
    const submittedDestination = destination.trim()
    const submittedSigningSecret = signingSecret.trim()
    setDestination('')
    setSigningSecret('')
    setFieldError('')
    setSigningError('')
    setRequestError('')
    if (enabled && emailUnavailable) {
      setRequestError('工作区邮件发送服务尚未就绪，暂不能启用邮箱通知。Webhook 不受影响。')
      return
    }
    if (
      channel === 'webhook'
      && !settings.webhook_provider_explicit
      && !submittedDestination
    ) {
      setFieldError('升级旧 Webhook 配置时，请选择类型并重新输入对应地址。')
      return
    }
    if (channel === 'webhook' && providerTouched && !submittedDestination) {
      setFieldError('选择或更换 Webhook 类型时，请重新输入对应地址。')
      return
    }
    const validationError = notificationDestinationError({
      channel,
      destination: submittedDestination,
      configured,
      enabled,
    })
    if (validationError) {
      setFieldError(validationError)
      return
    }
    if (
      channel === 'webhook'
      && signingEnabled
      && !signingConfigured
      && !submittedSigningSecret
    ) {
      setSigningError('启用签名校验时需要填写签名 Secret。')
      return
    }
    setSaving(true)
    try {
      const updated = await onSave({
        enabled,
        channel,
        ...(submittedDestination
          ? channel === 'email'
            ? { email_address: submittedDestination }
            : { webhook_url: submittedDestination }
          : {}),
        ...(channel === 'webhook' && (providerTouched || submittedDestination)
          ? { webhook_provider: webhookProvider }
          : {}),
        ...(channel === 'webhook' && submittedSigningSecret
          ? { webhook_signing_secret: submittedSigningSecret }
          : {}),
        ...(channel === 'webhook'
          && !signingEnabled
          && settings.webhook_signing_secret_configured
          ? { webhook_signing_secret: null }
          : {}),
      })
      setWebhookProvider(updated.webhook_provider)
      setProviderTouched(false)
      setSigningEnabled(updated.webhook_signing_secret_configured)
      actionToast.success('消息通知设置已保存')
    } catch (caught) {
      const message = safeNotificationError(caught, '消息通知设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('消息通知设置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function sendTest() {
    if (readOnly || !testReady) return
    setTesting(true)
    setRequestError('')
    try {
      const result = await onTest()
      if (result.channel === 'email') {
        actionToast.success('测试邮件已发送', {
          description: '请检查当前收件邮箱。',
        })
        return
      }
      actionToast.success(
        result.verification === 'provider_accepted' ? '平台已接受测试通知' : '测试通知请求已发送',
        {
          description: result.verification === 'provider_accepted'
            ? '平台业务响应已通过，请确认接收端实际展示。'
            : '接收端已返回 HTTP 成功状态，请确认实际处理。',
        },
      )
    } catch (caught) {
      const message = safeNotificationError(caught, '测试通知发送失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('测试通知发送失败', { description: message })
    } finally {
      setTesting(false)
    }
  }

  return <form className="grid gap-4" noValidate onSubmit={save}>
    {readOnly && <HeroNotice title="当前账户为只读权限" status="default" role="status">
      通知设置仅供查看，无法修改或发送测试通知。
    </HeroNotice>}
    {!settings.email_transport_ready && <HeroNotice
      title={settings.enabled && settings.channel === 'email' ? '邮箱通知已暂停' : '邮件发送服务尚未就绪'}
      status="warning"
      role="status"
    >
      暂停期间不会产生邮件投递，也不会在服务恢复后补发；Webhook 通知不受影响。
    </HeroNotice>}
    <div className="grid gap-1">
      <Switch isSelected={enabled} isDisabled={readOnly || (emailUnavailable && !settings.enabled)} onChange={(value) => {
        setEnabled(value)
        setFieldError('')
        setRequestError('')
      }}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用新内容通知</Switch.Content>
      </Switch>
      <Description>只对已在订阅设置中开启通知的来源生效。</Description>
    </div>
    <div className="grid gap-4 min-[720px]:grid-cols-2">
      <HeroSelect
        label="通知方式"
        value={channel}
        isDisabled={readOnly}
        onChange={(value) => {
          setChannel(value as NotificationChannel)
          setDestination('')
          setWebhookProvider(settings.webhook_provider)
          setProviderTouched(false)
          setSigningEnabled(settings.webhook_signing_secret_configured)
          setSigningSecret('')
          setFieldError('')
          setSigningError('')
          setRequestError('')
        }}
        options={[
          { id: 'email', label: '邮箱' },
          { id: 'webhook', label: 'Webhook' },
        ]}
      />
      {channel === 'email' && <TextField
        fullWidth
        value={destination}
        onChange={(value) => {
          setDestination(value)
          setFieldError('')
          setRequestError('')
        }}
        isDisabled={readOnly}
        isInvalid={Boolean(fieldError)}
        isRequired={!readOnly && enabled && !configured}
      >
        <Label>收件邮箱</Label>
        <Input
          type="email"
          autoComplete="email"
          placeholder={configured ? '留空保持当前配置' : 'name@example.com'}
        />
        <Description>
          {configured
            ? '已配置；真实接收地址不会回显，留空不会覆盖。'
            : '尚未配置当前通知方式。'}
        </Description>
        {fieldError && <FieldError>{fieldError}</FieldError>}
      </TextField>}
      {channel === 'webhook' && <WebhookProviderFields
        idPrefix="preferred-source-webhook"
        provider={webhookProvider}
        options={settings.webhook_provider_options}
        destination={destination}
        configured={configured}
        providerExplicit={settings.webhook_provider_explicit}
        signingEnabled={signingEnabled}
        signingSecret={signingSecret}
        signingConfigured={signingConfigured}
        destinationRequired={enabled && !configured}
        fieldError={fieldError}
        signingError={signingError}
        readOnly={readOnly}
        onProviderChange={(provider) => {
          setWebhookProvider(provider)
          setProviderTouched(provider !== settings.webhook_provider || !settings.webhook_provider_explicit)
          setDestination('')
          setSigningEnabled(false)
          setSigningSecret('')
          setFieldError('')
          setSigningError('')
          setRequestError('')
        }}
        onDestinationChange={(value) => {
          setDestination(value)
          setFieldError('')
          setRequestError('')
        }}
        onSigningEnabledChange={(value) => {
          setSigningEnabled(value)
          if (!settings.webhook_provider_explicit) {
            setProviderTouched(true)
          }
          setSigningSecret('')
          setSigningError('')
          setRequestError('')
        }}
        onSigningSecretChange={(value) => {
          setSigningSecret(value)
          setSigningError('')
          setRequestError('')
        }}
      />}
    </div>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      {channel === 'webhook' && <p className="mb-1">
        平台预设会校验业务响应；通用类型只确认 HTTP 2xx。保存成功仅表示配置已写入，测试后仍请确认接收端实际展示。
      </p>}
      <p>只推送开启后首次入库的新内容；已有历史、来源复用内容和停用期间内容不会补发。</p>
      <p className="mt-1">测试通知使用模拟内容，不会抓取来源，也不会改变新内容投递起点。</p>
      <p className="type-meta mt-2">
        {notificationTestLabel(settings.last_test_status, {
          channel: settings.channel,
          verificationMode: settings.webhook_verification_mode,
        })}
        {lastTestTime ? ` · ${lastTestTime}` : ''}
      </p>
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={readOnly || saving || testing || !dirty}>{saving ? '保存中…' : '保存通知设置'}</Button>
      <Button type="button" variant="secondary" isDisabled={!testReady} onPress={() => void sendTest()}>
        {testing ? '发送中…' : '发送测试通知'}
      </Button>
    </div>
  </form>
}

export function HeroNotificationSettings() {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: queryKeys.notificationSettings(user.id),
    queryFn: ({ signal }) => api.notificationSettings(signal),
    staleTime: queryStaleTime.settings,
  })

  if (settings.isLoading) return <LoadingState label="正在读取消息通知设置" rows={1} />
  if (settings.isError || !settings.data) return <HeroNotice title="消息通知设置读取失败，请刷新后重试。" />

  const cacheKey = [
    settings.data.enabled,
    settings.data.channel,
    settings.data.email_configured,
    settings.data.email_transport_ready,
    settings.data.webhook_configured,
    settings.data.webhook_provider,
    settings.data.webhook_provider_explicit,
    settings.data.webhook_signing_secret_configured,
    settings.data.last_tested_at,
    settings.data.last_test_status,
  ].join(':')

  async function save(patch: UserNotificationSettingsPatch) {
    const updated = await api.updateNotificationSettings(patch)
    queryClient.setQueryData(queryKeys.notificationSettings(user.id), updated)
    return updated
  }

  async function test() {
    try {
      return await api.testNotificationSettings()
    } finally {
      await queryClient.invalidateQueries({ queryKey: queryKeys.notificationSettings(user.id) })
    }
  }

  return <NotificationSettingsForm
    key={cacheKey}
    settings={settings.data}
    onSave={save}
    onTest={test}
    readOnly={user.role === 'viewer'}
  />
}
