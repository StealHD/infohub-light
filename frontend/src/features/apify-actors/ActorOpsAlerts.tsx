import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type { ApifyActorAlertEvent, ApifyActorAlertSettings, ApifyActorAlertSettingsPatch } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { Button, Checkbox, LoadingState, Modal, StatusIndicator, StatusNotice, Switch } from '../../design-system'

const eventLabels: Record<ApifyActorAlertEvent, string> = {
  actor_switched: '自动切换 Actor',
  route_exhausted: '路线不可用',
  quota_low: '额度偏低',
  budget_blocked: '费用保护',
  start_outcome_unknown: '启动结果待对账',
  recovered: '路线恢复',
}

const eventOptions = Object.keys(eventLabels) as ApifyActorAlertEvent[]

export function ActorOpsAlertSettingsPanel() {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')
  const settings = useQuery({
    queryKey: queryKeys.apifyActorAlertSettings(user.id),
    queryFn: ({ signal }) => api.apifyActorAlertSettings(signal),
    retry: false,
  })
  const services = useQuery({
    queryKey: queryKeys.notificationServices(user.id),
    queryFn: ({ signal }) => api.notificationServices(signal),
    enabled: open,
    retry: false,
  })
  if (settings.isPending) return <LoadingState label="正在读取 ActorOps 告警设置" rows={2} />
  if (settings.isError || !settings.data) return <StatusNotice title="ActorOps 告警设置读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void settings.refetch()}>重试此区域</Button>
  </StatusNotice>
  const save = async (patch: Pick<ApifyActorAlertSettingsPatch, 'enabled' | 'target_ids' | 'events'>) => {
    setSaving(true)
    setSaveError('')
    try {
      const updated = await api.updateApifyActorAlertSettings(patch)
      queryClient.setQueryData(queryKeys.apifyActorAlertSettings(user.id), updated)
      setOpen(false)
    } catch {
      setSaveError('保存 ActorOps 告警失败，请检查通知服务后重试。')
    } finally {
      setSaving(false)
    }
  }
  return <>
    <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between">
      <dl className="grid grid-cols-3 gap-x-4 gap-y-2 type-meta">
        <div><dt className="text-muted">状态</dt><dd className="mt-0.5 type-control">{settings.data.enabled ? '已开启' : '已关闭'}</dd></div>
        <div><dt className="text-muted">通知服务</dt><dd className="mt-0.5 type-control">{settings.data.target_ids.length}</dd></div>
        <div><dt className="text-muted">事件类型</dt><dd className="mt-0.5 type-control">{settings.data.events.length}</dd></div>
      </dl>
      <Button variant="secondary" onPress={() => setOpen(true)}>编辑告警</Button>
    </div>
    <Modal isOpen={open} onOpenChange={(next) => { if (!saving) { setOpen(next); if (!next) setSaveError('') } }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">编辑 ActorOps 告警</Modal.Trigger>
      <Modal.Backdrop isDismissable={!saving} isKeyboardDismissDisabled={saving}><Modal.Container><Modal.Dialog><Modal.Header><Modal.Heading>编辑 ActorOps 告警</Modal.Heading></Modal.Header><Modal.Body>
        <AlertEditor settings={settings.data} services={services.data?.services ?? []} saving={saving || services.isPending} saveError={saveError} onSave={save} onClose={() => { setSaveError(''); setOpen(false) }} />
      </Modal.Body></Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </>
}

function AlertEditor({ settings, services, saving, saveError, onSave, onClose }: {
  settings: ApifyActorAlertSettings
  services: Array<{ id: string; name: string; scope: string; available: boolean }>
  saving: boolean
  saveError: string
  onSave: (patch: Pick<ApifyActorAlertSettingsPatch, 'enabled' | 'target_ids' | 'events'>) => Promise<void>
  onClose: () => void
}) {
  const [enabled, setEnabled] = useState(settings.enabled)
  const [targets, setTargets] = useState(settings.target_ids)
  const [events, setEvents] = useState(settings.events)
  const shared = services.filter((service) => service.scope === 'shared')
  const submit = async () => {
    await onSave({ enabled, target_ids: targets, events })
  }
  return <div className="grid gap-4">
    <Switch isSelected={enabled} onChange={setEnabled} isDisabled={saving}>启用工作区 ActorOps 告警</Switch>
    <fieldset className="grid gap-2"><legend className="type-label">通知服务</legend>
      {shared.length ? shared.map((service) => <Checkbox key={service.id} isSelected={targets.includes(service.id)} isDisabled={saving || !service.available} onChange={(selected) => setTargets((current) => selected ? [...new Set([...current, service.id])] : current.filter((id) => id !== service.id))}>
        <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{service.name}{!service.available && '（暂不可用）'}</Checkbox.Content>
      </Checkbox>) : <p className="type-meta text-muted">暂无可用的共享通知服务。</p>}
    </fieldset>
    <fieldset className="grid gap-2"><legend className="type-label">告警事件</legend>
      {eventOptions.map((event) => <Checkbox key={event} isSelected={events.includes(event)} isDisabled={saving} onChange={(selected) => setEvents((current) => selected ? [...new Set([...current, event])] : current.filter((item) => item !== event))}>
        <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{eventLabels[event]}</Checkbox.Content>
      </Checkbox>)}
    </fieldset>
    {saveError && <StatusNotice title="ActorOps 告警未保存" status="warning">{saveError}</StatusNotice>}
    <div className="flex justify-end gap-2"><Button variant="ghost" onPress={onClose} isDisabled={saving}>取消</Button><Button isDisabled={saving} onPress={() => void submit()}>{saving ? '保存中…' : '保存告警'}</Button></div>
  </div>
}

export function ActorOpsAlertIncidentList() {
  const { api, user } = useAppContext()
  const incidents = useQuery({
    queryKey: queryKeys.apifyActorAlertIncidents(user.id),
    queryFn: ({ signal }) => api.apifyActorAlertIncidents(signal),
    retry: false,
  })
  if (incidents.isPending) return <LoadingState label="正在读取 ActorOps 告警事件" rows={2} />
  if (incidents.isError || !incidents.data) return <StatusNotice title="ActorOps 告警事件读取失败" status="warning">
    <Button size="sm" variant="ghost" onPress={() => void incidents.refetch()}>重试此区域</Button>
  </StatusNotice>
  if (!incidents.data.incidents.length) return <p className="type-meta text-muted">尚无需要处理的 ActorOps 告警。</p>
  return <ol className="grid gap-2" aria-label="ActorOps 告警事件">
    {incidents.data.incidents.slice(0, 5).map((incident) => <li key={incident.id} className="rounded-control border border-separator bg-surface-secondary p-3">
      <div className="flex flex-wrap items-center justify-between gap-2"><p className="type-control">{eventLabels[incident.event_type]}</p><StatusIndicator label={incident.status === 'resolved' ? '已恢复' : '需处理'} tone={incident.status === 'resolved' ? 'success' : 'warning'} /></div>
      <p className="mt-1 type-meta text-muted">{incident.reason_code || '状态已更新'} · {formatTime(incident.last_seen_at)}</p>
    </li>)}
  </ol>
}

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '时间未记录' : new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}
