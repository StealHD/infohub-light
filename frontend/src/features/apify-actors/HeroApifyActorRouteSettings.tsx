import { useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  ApifyActorAlertEvent,
  ApifyActorAlertSettings,
  ApifyActorAlertSettingsPatch,
  NotificationChannel,
  NotificationService,
  NotificationTestResult,
  WebhookProvider,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { SettingsDisclosure } from '../../components/settings'
import {
  actionToast,
  Button,
  Card,
  Checkbox,
  Description,
  Icons,
  LoadingState,
  Modal,
  StatusIndicator,
  Switch,
} from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'
import {
  notificationDestinationError,
} from '../notifications/notificationModel'
import {
  NotificationChannelCards,
  type NotificationDestinationDrafts,
  type NotificationDestinationErrors,
} from '../notifications/NotificationChannelCards'
import {
  APIFY_ACTOR_ROUTE_REFRESH_MS,
  actorAlertEventLabels,
  actorReasonLabel,
  formatActorDateTime,
  safeActorActionError,
} from './apifyActorModel'
import { LegacyHeroActorOpsControlPlane } from './HeroActorOpsControlPlane'

const alertEvents = Object.keys(actorAlertEventLabels) as ApifyActorAlertEvent[]

function lastAlertLabel(
  status: string | null,
  channel: NotificationChannel,
  verificationMode: 'http_status' | 'provider_response',
): string {
  if (!status) return '尚未发送运行告警'
  if (status === 'sent' || status === 'succeeded' || status === 'success') {
    if (channel === 'email') return '最近一次运行告警邮件已发送'
    if (channel === 'telegram') return '最近一次 Telegram 运行告警已发送'
    if (verificationMode === 'provider_response') return '最近一次运行告警已获平台接受'
    return '最近一次运行告警请求已发送，请确认接收端'
  }
  if (status === 'failed' || status === 'failure') return '最近一次运行告警发送失败'
  if (status === 'unknown') return '最近一次运行告警结果未知，不会自动重发'
  return '最近一次运行告警正在处理'
}

const emptyAlertDestinations = (): NotificationDestinationDrafts => ({
  email: '',
  webhook: '',
  telegram: '',
})

function sameAlertChannels(left: NotificationChannel[], right: NotificationChannel[]): boolean {
  return left.length === right.length && left.every((channel, index) => channel === right[index])
}

export function ApifyActorAlertSettingsForm({
  settings,
  onSave,
  onTest,
}: {
  settings: ApifyActorAlertSettings
  onSave: (patch: ApifyActorAlertSettingsPatch) => Promise<ApifyActorAlertSettings>
  onTest: (channel: NotificationChannel) => Promise<NotificationTestResult>
}) {
  const webhookState = settings.channel_states.webhook
  const [enabled, setEnabled] = useState(settings.enabled)
  const [channels, setChannels] = useState<NotificationChannel[]>(settings.channels)
  const [events, setEvents] = useState<ApifyActorAlertEvent[]>(settings.events)
  const [destinations, setDestinations] = useState<NotificationDestinationDrafts>(emptyAlertDestinations)
  const [webhookProvider, setWebhookProvider] = useState<WebhookProvider>(webhookState.provider)
  const [providerTouched, setProviderTouched] = useState(false)
  const [signingEnabled, setSigningEnabled] = useState(webhookState.signing_secret_configured)
  const [signingSecret, setSigningSecret] = useState('')
  const [errors, setErrors] = useState<NotificationDestinationErrors>({})
  const [eventError, setEventError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testingChannel, setTestingChannel] = useState<NotificationChannel | null>(null)
  const eventsDirty = [...events].sort().join(':') !== [...settings.events].sort().join(':')
  const signingDirty = signingEnabled !== webhookState.signing_secret_configured
    || Boolean(signingSecret.trim())
  const dirty = enabled !== settings.enabled
    || !sameAlertChannels(channels, settings.channels)
    || eventsDirty
    || Object.values(destinations).some((value) => Boolean(value.trim()))
    || providerTouched
    || signingDirty
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
    if (busy) return
    const submittedDestinations = {
      email: destinations.email.trim(),
      webhook: destinations.webhook.trim(),
      telegram: destinations.telegram.trim(),
    }
    const submittedSigningSecret = signingSecret.trim()
    setDestinations(emptyAlertDestinations())
    setSigningSecret('')
    setErrors({})
    setEventError('')
    setRequestError('')
    if (enabled && events.length === 0) {
      setEventError('启用运行告警时，请至少选择一种告警事件。')
      return
    }
    if (enabled && channels.length === 0) {
      setRequestError('启用 Apify 运行告警时，请至少选择一种告警渠道。')
      return
    }
    const nextErrors: NotificationDestinationErrors = {}
    for (const channel of ['email', 'webhook', 'telegram'] as const) {
      const configured = channel === 'webhook'
        ? webhookState.configured
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
    if (
      signingEnabled
      && !signingConfigured
      && !submittedSigningSecret
    ) {
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
        events,
        ...(submittedDestinations.email ? { email_address: submittedDestinations.email } : {}),
        ...(submittedDestinations.webhook ? { webhook_url: submittedDestinations.webhook } : {}),
        ...(submittedDestinations.telegram ? { telegram_chat_id: submittedDestinations.telegram } : {}),
        ...(providerTouched || submittedDestinations.webhook ? { webhook_provider: webhookProvider } : {}),
        ...(submittedSigningSecret ? { webhook_signing_secret: submittedSigningSecret } : {}),
        ...(!signingEnabled
          && webhookState.signing_secret_configured
          ? { webhook_signing_secret: null }
          : {}),
      })
      actionToast.success('Apify 运行告警设置已保存')
    } catch (caught) {
      const message = safeActorActionError(caught, 'Apify 运行告警设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('Apify 运行告警设置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function sendTest(channel: NotificationChannel) {
    if (busy || channelDirty(channel)) return
    setTestingChannel(channel)
    setRequestError('')
    try {
      const result = await onTest(channel)
      if (result.channel === 'email') {
        actionToast.success('测试运行告警邮件已发送', {
          description: '请检查当前告警收件邮箱。',
        })
      } else if (result.channel === 'telegram') {
        actionToast.success('Telegram 测试运行告警已发送', {
          description: '请检查当前告警目标会话。',
        })
      } else {
        actionToast.success(
          result.verification === 'provider_accepted' ? '平台已接受测试运行告警' : '测试运行告警请求已发送',
          {
            description: result.verification === 'provider_accepted'
              ? '平台业务响应已通过，请确认接收端实际展示。'
              : '接收端已返回 HTTP 成功状态，请确认实际处理。',
          },
        )
      }
    } catch (caught) {
      const message = safeActorActionError(caught, '测试运行告警发送失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('测试运行告警发送失败', { description: message })
    } finally {
      setTestingChannel(null)
    }
  }

  return <form className="grid min-w-0 gap-4" noValidate onSubmit={save}>
    <div className="grid gap-1">
      <Switch isSelected={enabled} onChange={(value) => {
        setEnabled(value)
        setEventError('')
        setRequestError('')
      }}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用 Apify 运行告警</Switch.Content>
      </Switch>
      <Description>只报告 Actor 切换、额度、费用保护和恢复；可同时选择多个渠道。</Description>
    </div>

    <NotificationChannelCards
      idPrefix="apify-alert"
      settings={settings}
      selectedChannels={channels}
      destinations={destinations}
      webhookProvider={webhookProvider}
      providerTouched={providerTouched}
      signingEnabled={signingEnabled}
      signingSecret={signingSecret}
      errors={errors}
      readOnly={false}
      busy={busy}
      testingChannel={testingChannel}
      channelDirty={channelDirty}
      destinationNoun="告警"
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

    <fieldset className="grid gap-3" aria-describedby="apify-actor-alert-events-help">
      <legend className="type-control">告警事件</legend>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {alertEvents.map((event) => <Checkbox
          key={event}
          isSelected={events.includes(event)}
          onChange={(selected) => {
            setEvents((current) => selected
              ? [...current, event]
              : current.filter((item) => item !== event))
            setEventError('')
            setRequestError('')
          }}
        >
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{actorAlertEventLabels[event]}</Checkbox.Content>
        </Checkbox>)}
      </div>
      <Description id="apify-actor-alert-events-help">同一故障只首报一次；状态恢复后再发送一条恢复通知。</Description>
      {eventError && <p className="type-meta text-danger" role="alert">{eventError}</p>}
    </fieldset>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      <p>每个渠道独立配置、测试与投递；一个渠道暂停或失败不会阻断其他渠道或抓取任务。</p>
      <p className="mt-1">测试告警使用模拟内容，不会抓取 X、调用 Actor 或产生 Apify 费用。</p>
      <p className="type-meta mt-1">
        {lastAlertLabel(
          settings.last_alert_status,
          settings.channel,
          settings.webhook_verification_mode,
        )} · {formatActorDateTime(settings.last_alerted_at)}
      </p>
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={busy || !dirty}>{saving ? '保存中…' : '保存运行告警'}</Button>
    </div>
  </form>
}

export function ApifyActorAlertSettingsPanel({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const editTriggerRef = useRef<HTMLButtonElement>(null)
  const [editOpen, setEditOpen] = useState(false)
  const [editBusy, setEditBusy] = useState(false)
  const settings = useQuery({
    queryKey: queryKeys.apifyActorAlertSettings(user.id),
    queryFn: ({ signal }) => api.apifyActorAlertSettings(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
    retry: false,
  })
  const services = useQuery({
    queryKey: queryKeys.notificationServices(user.id),
    queryFn: ({ signal }) => api.notificationServices(signal),
    enabled: queryEnabled && editOpen,
    staleTime: queryStaleTime.settings,
  })

  if (settings.isPending) return <LoadingState label="正在读取 Apify 运行告警设置" rows={2} />
  if (settings.isError || !settings.data) return <HeroNotice title="Apify 运行告警设置读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void settings.refetch()}>重试此区域</Button>
  </HeroNotice>

  const sharedTargets = services.data?.services.filter((service) => service.scope === 'shared') ?? []
  const cacheKey = [
    settings.data.enabled,
    settings.data.target_ids.join(':'),
    settings.data.events.join(':'),
    sharedTargets.map((target) => `${target.id}:${target.available}:${target.config_generation}`).join('|'),
    settings.data.last_alerted_at,
  ].join(':')

  async function save(patch: ApifyActorAlertSettingsPatch) {
    const updated = await api.updateApifyActorAlertSettings(patch)
    queryClient.setQueryData(queryKeys.apifyActorAlertSettings(user.id), updated)
    setEditOpen(false)
    requestAnimationFrame(() => editTriggerRef.current?.focus())
    return updated
  }

  return <>
    <div className="flex min-w-0 flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between">
      <dl className="grid min-w-0 grid-cols-2 gap-x-5 gap-y-2 type-meta min-[720px]:grid-cols-4">
        <div><dt className="text-muted">状态</dt><dd className="mt-0.5 type-control">{settings.data.enabled ? '已开启' : '已关闭'}</dd></div>
        <div><dt className="text-muted">共享服务</dt><dd className="mt-0.5 type-control tabular-nums">{settings.data.target_ids.length}</dd></div>
        <div><dt className="text-muted">事件类型</dt><dd className="mt-0.5 type-control tabular-nums">{settings.data.events.length}</dd></div>
        <div><dt className="text-muted">最近告警</dt><dd className="mt-0.5 type-control">{formatActorDateTime(settings.data.last_alerted_at)}</dd></div>
      </dl>
      <Button ref={editTriggerRef} variant="secondary" onPress={() => setEditOpen(true)}>编辑告警</Button>
    </div>
    <Modal isOpen={editOpen} onOpenChange={(open) => {
      if (editBusy) return
      setEditOpen(open)
      if (!open) requestAnimationFrame(() => editTriggerRef.current?.focus())
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开运行告警编辑</Modal.Trigger>
      <Modal.Backdrop isDismissable={!editBusy} isKeyboardDismissDisabled={editBusy}>
        <Modal.Container><Modal.Dialog>
          <Modal.Header><Modal.Heading>编辑运行告警</Modal.Heading></Modal.Header>
          <Modal.Body>
            {services.isPending && <LoadingState label="正在读取共享通知服务" rows={2} />}
            {(services.isError || !services.data) && !services.isPending && <HeroNotice title="共享通知服务读取失败" status="warning">
              <Button size="sm" variant="ghost" onPress={() => void services.refetch()}>重试此区域</Button>
            </HeroNotice>}
            {services.data && <ApifyTargetSelectionForm
              key={cacheKey}
              settings={settings.data}
              targets={sharedTargets}
              onSave={save}
              onBusyChange={setEditBusy}
            />}
          </Modal.Body>
        </Modal.Dialog></Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </>
}

function ApifyTargetSelectionForm({
  settings,
  targets,
  onSave,
  onBusyChange,
}: {
  settings: ApifyActorAlertSettings
  targets: NotificationService[]
  onSave: (patch: ApifyActorAlertSettingsPatch) => Promise<ApifyActorAlertSettings>
  onBusyChange?: (busy: boolean) => void
}) {
  const [enabled, setEnabled] = useState(settings.enabled)
  const [targetIds, setTargetIds] = useState(settings.target_ids)
  const [events, setEvents] = useState(settings.events)
  const [saving, setSaving] = useState(false)
  const [requestError, setRequestError] = useState('')
  const dirty = enabled !== settings.enabled
    || targetIds.length !== settings.target_ids.length
    || targetIds.some((id, index) => id !== settings.target_ids[index])
    || [...events].sort().join(':') !== [...settings.events].sort().join(':')

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (saving || !dirty) return
    if (enabled && targetIds.length === 0) {
      setRequestError('启用运行告警时，请至少选择一个工作区共享通知服务。')
      return
    }
    if (enabled && events.length === 0) {
      setRequestError('启用运行告警时，请至少选择一种告警事件。')
      return
    }
    setSaving(true)
    onBusyChange?.(true)
    setRequestError('')
    try {
      await onSave({ enabled, target_ids: targetIds, events })
      actionToast.success('Apify 运行告警设置已保存')
    } catch (caught) {
      const message = safeActorActionError(caught, 'Apify 运行告警设置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('Apify 运行告警设置保存失败', { description: message })
    } finally {
      setSaving(false)
      onBusyChange?.(false)
    }
  }

  return <form className="grid min-w-0 gap-4" noValidate onSubmit={save}>
    <div className="grid gap-1">
      <Switch isSelected={enabled} onChange={(value) => {
        setEnabled(value)
        setRequestError('')
      }}>
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>启用 Apify 运行告警</Switch.Content>
      </Switch>
      <Description>系统告警只能选择工作区共享通知服务；接收地址、共享凭据和测试统一在“消息通知”中完成。</Description>
    </div>
    <fieldset className="grid gap-3">
      <legend className="type-control">共享通知服务</legend>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {targets.map((target) => <Card key={target.id} className="grid gap-2 p-3">
          <Checkbox
            isSelected={targetIds.includes(target.id)}
            isDisabled={!target.available && !targetIds.includes(target.id)}
            onChange={(selected) => {
              setTargetIds((current) => selected
                ? current.includes(target.id) ? current : [...current, target.id]
                : current.filter((id) => id !== target.id))
              setRequestError('')
            }}
          >
            <Checkbox.Content>
              <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
              {target.name}
            </Checkbox.Content>
          </Checkbox>
          <Card.Description>
            {target.channel === 'email' ? '邮箱' : target.channel === 'telegram' ? 'Telegram' : 'Webhook'}
            {' · '}{target.available
              ? '可用'
              : target.enabled
                ? '暂不可用，不能新选择'
                : '已暂停，不能新选择'}
          </Card.Description>
        </Card>)}
      </div>
      {targets.length === 0 && <HeroNotice title="没有工作区共享通知服务" status="warning">
        <a className="underline" href="#settings-notifications">前往消息通知创建通知服务</a>
      </HeroNotice>}
    </fieldset>
    <fieldset className="grid gap-3" aria-describedby="apify-target-events-help">
      <legend className="type-control">告警事件</legend>
      <div className="grid gap-3 min-[720px]:grid-cols-2">
        {alertEvents.map((alertEvent) => <Checkbox
          key={alertEvent}
          isSelected={events.includes(alertEvent)}
          onChange={(selected) => {
            setEvents((current) => selected
              ? current.includes(alertEvent) ? current : [...current, alertEvent]
              : current.filter((item) => item !== alertEvent))
            setRequestError('')
          }}
        >
          <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{actorAlertEventLabels[alertEvent]}</Checkbox.Content>
        </Checkbox>)}
      </div>
      <Description id="apify-target-events-help">同一故障只首报一次；状态恢复后按原目标发送恢复通知。</Description>
    </fieldset>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      <p>任一目标失败不会阻断其他目标或原抓取任务；结果未知的投递不会自动重放。</p>
      <p className="type-meta mt-1">
        {lastAlertLabel(
          settings.last_alert_status,
          settings.channel,
          settings.webhook_verification_mode,
        )} · {formatActorDateTime(settings.last_alerted_at)}
      </p>
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={saving || !dirty}>{saving ? '保存中…' : '保存运行告警'}</Button>
    </div>
  </form>
}

function incidentDeliveryLabel(status: string | null): string {
  if (!status) return '未触发投递'
  if (status === 'sent') return '已发送'
  if (status === 'failed') return '发送失败'
  if (status === 'unknown') return '结果未知，不自动重发'
  if (status === 'partial') return '部分渠道发送失败'
  if (status === 'skipped') return '已按设置跳过'
  return '等待发送'
}

export function ApifyActorIncidentList({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const incidents = useQuery({
    queryKey: queryKeys.apifyActorAlertIncidents(user.id),
    queryFn: ({ signal }) => api.apifyActorAlertIncidents(signal),
    enabled: queryEnabled,
    retry: false,
    refetchInterval: queryEnabled ? APIFY_ACTOR_ROUTE_REFRESH_MS : false,
  })

  if (incidents.isPending) return <LoadingState label="正在读取 Actor 事件" rows={2} />
  if (incidents.isError || !incidents.data) return <HeroNotice title="最近 Actor 事件读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void incidents.refetch()}>重试此区域</Button>
  </HeroNotice>
  const rows = incidents.data.incidents.slice(0, 20)
  if (rows.length === 0) return <p className="type-meta text-muted">尚无切换、熔断、费用保护或恢复记录。</p>

  const renderIncident = (incident: (typeof rows)[number]) => <li
      key={incident.id}
      className="min-w-0 rounded-control border border-separator bg-surface-secondary p-3"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="type-control">{actorAlertEventLabels[incident.event_type]}</p>
          <p className="type-meta mt-1 break-words text-muted">
            {incident.actor_name ? `涉及 ${incident.actor_name}` : '工作区 X 抓取路线'}
            {incident.active_actor_name ? ` · 当前 ${incident.active_actor_name}` : ''}
          </p>
        </div>
        <StatusIndicator
          label={incident.status === 'resolved' ? '已恢复' : incident.severity === 'critical' ? '需要处理' : '持续观察'}
          tone={incident.status === 'resolved' ? 'success' : incident.severity === 'critical' ? 'danger' : 'warning'}
          icon={incident.status === 'resolved'
            ? <Icons.CircleCheck size={13} aria-hidden="true" />
            : <Icons.TriangleAlert size={13} aria-hidden="true" />}
        />
      </div>
      <p className="type-meta mt-2 text-muted">{actorReasonLabel(incident.reason_code)}</p>
      <p className="type-meta mt-1 text-muted">
        <time dateTime={incident.opened_at}>发生于 {formatActorDateTime(incident.opened_at)}</time>
        {incident.resolved_at && <> · <time dateTime={incident.resolved_at}>恢复于 {formatActorDateTime(incident.resolved_at)}</time></>}
        {' · '}{incidentDeliveryLabel(incident.delivery_status)}
      </p>
      {(incident.deliveries ?? []).length > 0 && <SettingsDisclosure
        title="投递详情"
        description="逐个共享通知服务查看投递结果。"
        className="mt-3"
      ><ul className="grid gap-1" aria-label="逐渠道投递状态">
          {(incident.deliveries ?? []).map((delivery) => <li
            key={`${delivery.event_type}:${delivery.target_id ?? delivery.channel}`}
            className="type-meta text-muted"
          >
            {delivery.target_name ?? (delivery.channel === 'email' ? '邮箱' : delivery.channel === 'webhook' ? 'Webhook' : 'Telegram')}
            {' · '}{incidentDeliveryLabel(delivery.status)}
          </li>)}
        </ul></SettingsDisclosure>}
    </li>

  return <div className="grid gap-3">
    <ol className="grid gap-2" aria-label="最近 Actor 事件">
      {rows.slice(0, 5).map(renderIncident)}
    </ol>
    {rows.length > 5 && <SettingsDisclosure
      title="查看全部事件"
      description={`另有 ${rows.length - 5} 条较早记录。`}
    ><ol className="grid gap-2" aria-label="较早 Actor 事件">{rows.slice(5).map(renderIncident)}</ol></SettingsDisclosure>}
  </div>
}

export function HeroApifyActorRouteSettings({ queryEnabled = true }: { queryEnabled?: boolean }) {
  return <Card variant="secondary" className="min-w-0 max-w-full p-4">
    <LegacyHeroActorOpsControlPlane queryEnabled={queryEnabled} />
    <div className="mt-6 border-t border-separator pt-5">
      <h3 className="type-page-title">故障告警</h3>
      <p className="type-meta mt-1 text-muted">从工作区共享通知服务中多选；服务只需统一配置和测试一次。</p>
      <div className="mt-4"><ApifyActorAlertSettingsPanel queryEnabled={queryEnabled} /></div>
    </div>
    <div className="mt-6 border-t border-separator pt-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="type-page-title">最近事件</h3>
        <span className="type-meta text-muted">最多显示 20 条</span>
      </div>
      <div className="mt-3"><ApifyActorIncidentList queryEnabled={queryEnabled} /></div>
    </div>
  </Card>
}
