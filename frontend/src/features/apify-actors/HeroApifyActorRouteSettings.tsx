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
  APIFY_ACTOR_ROUTE_REFRESH_MS,
  actorAlertEventLabels,
  actorReasonLabel,
  formatActorDateTime,
  safeActorActionError,
} from './apifyActorModel'

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
