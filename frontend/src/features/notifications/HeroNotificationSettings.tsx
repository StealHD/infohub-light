import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationService,
  UserNotificationSettings,
  UserNotificationSettingsPatch,
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
import { safeNotificationError } from './notificationModel'

export function HeroNotificationSettings({ queryEnabled = true }: { queryEnabled?: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const settings = useQuery({
    queryKey: queryKeys.notificationSettings(user.id),
    queryFn: ({ signal }) => api.notificationSettings(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })
  const services = useQuery({
    queryKey: queryKeys.notificationServices(user.id),
    queryFn: ({ signal }) => api.notificationServices(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })

  if (settings.isPending || services.isPending) return <LoadingState label="正在读取消息通知设置" rows={2} />
  if (settings.isError || services.isError || !settings.data || !services.data) {
    return <HeroNotice title="消息通知设置读取失败，请刷新后重试。" />
  }

  const cacheKey = [
    settings.data.enabled,
    settings.data.target_ids.join(':'),
    services.data.services.map((service) => `${service.id}:${service.available}:${service.config_generation}`).join('|'),
  ].join(':')

  async function save(patch: UserNotificationSettingsPatch) {
    const updated = await api.updateNotificationSettings(patch)
    queryClient.setQueryData(queryKeys.notificationSettings(user.id), updated)
    return updated
  }

  return <NotificationTargetSelectionForm
    key={cacheKey}
    settings={settings.data}
    targets={services.data.services}
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
  targets: NotificationService[]
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
      setRequestError('启用新内容通知时，请至少选择一个通知服务。')
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
      <Description>只对订阅中已开启通知的来源生效；可以选择多个服务，也可以选择多个相同渠道的服务。</Description>
    </div>
    <div className="grid min-w-0 gap-3 min-[768px]:grid-cols-2">
      {targets.map((target) => <Card key={target.id} className="grid gap-2 p-4">
        <Checkbox
          isSelected={targetIds.includes(target.id)}
          isDisabled={
            readOnly
            || (!target.available && !targetIds.includes(target.id))
          }
          onChange={(selected) => toggleTarget(target.id, selected)}
        >
          <Checkbox.Content>
            <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
            <span>{target.name}</span>
          </Checkbox.Content>
        </Checkbox>
        <Card.Description>
          {target.scope === 'shared' ? '工作区共享' : '历史私人服务'} · {
            target.channel === 'email' ? '邮箱' : target.channel === 'telegram' ? 'Telegram' : 'Webhook'
          } · {target.available
            ? '可用'
            : target.enabled
              ? '暂不可用，不能新选择'
              : '已暂停，不能新选择'}
        </Card.Description>
      </Card>)}
      {targets.length === 0 && <HeroNotice
        title="暂无可选通知服务"
        status="warning"
        role="status"
      >请联系管理员在上方“通知服务”中保存并测试一个服务。</HeroNotice>}
    </div>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      新选择服务、恢复服务或恢复总开关都只发送之后严格新增的内容，不补发停用期间或历史内容。
    </div>
    {requestError && <HeroNotice title={requestError} />}
    <div className="flex flex-wrap gap-2">
      <Button type="submit" isDisabled={readOnly || saving || !dirty}>
        {saving ? '保存中…' : '保存通知设置'}
      </Button>
    </div>
  </form>
}
