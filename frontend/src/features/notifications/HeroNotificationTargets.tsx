import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationChannel,
  NotificationTarget,
  NotificationTargetScope,
  WebhookProvider,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Card,
  Description,
  Input,
  Label,
  LoadingState,
  TextField,
} from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'
import { safeNotificationError } from './notificationModel'

const channelLabels: Record<NotificationChannel, string> = {
  email: '邮箱',
  webhook: 'Webhook',
  telegram: 'Telegram',
}

function destinationLabel(channel: NotificationChannel): string {
  if (channel === 'email') return '收件邮箱'
  if (channel === 'telegram') return 'Chat ID'
  return 'Webhook 地址'
}

function targetStatus(target: NotificationTarget): string {
  if (!target.configured) return '未配置'
  if (!target.transport_ready) return '发送基础服务不可用'
  if (target.last_test_status !== 'sent') return '待测试'
  if (!target.enabled) return '已暂停'
  return target.available ? '可用' : '不可用'
}

export function HeroNotificationTargets({
  queryEnabled = true,
}: {
  queryEnabled?: boolean
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const admin = user.role === 'owner' || user.role === 'admin'
  const readOnly = user.role === 'viewer'
  const targets = useQuery({
    queryKey: queryKeys.notificationTargets(user.id),
    queryFn: ({ signal }) => api.notificationTargets(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })
  const [name, setName] = useState('')
  const [scope, setScope] = useState<NotificationTargetScope>('private')
  const [channel, setChannel] = useState<NotificationChannel>('email')
  const [destination, setDestination] = useState('')
  const [provider, setProvider] = useState<WebhookProvider>('generic_event')
  const [busyTarget, setBusyTarget] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [editingTarget, setEditingTarget] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDestination, setEditDestination] = useState('')
  const [confirmArchive, setConfirmArchive] = useState<string | null>(null)
  const [requestError, setRequestError] = useState('')

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.notificationTargets(user.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.notificationSettings(user.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.apifyActorAlertSettings(user.id),
      }),
    ])
  }

  async function createTarget(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || creating || !name.trim() || !destination.trim()) return
    const submittedDestination = destination.trim()
    setDestination('')
    setRequestError('')
    setCreating(true)
    try {
      await api.createNotificationTarget({
        name: name.trim(),
        scope,
        channel,
        ...(channel === 'email'
          ? { email_address: submittedDestination }
          : channel === 'telegram'
            ? { telegram_chat_id: submittedDestination }
            : {
                webhook_url: submittedDestination,
                webhook_provider: provider,
              }),
      })
      setName('')
      await refresh()
      actionToast.success('通知目标已创建', {
        description: '请先发送测试，再启用该目标。',
      })
    } catch (caught) {
      const message = safeNotificationError(
        caught,
        '通知目标创建失败，请检查配置。',
      )
      setRequestError(message)
      actionToast.danger('通知目标创建失败', { description: message })
    } finally {
      setCreating(false)
    }
  }

  async function testTarget(target: NotificationTarget) {
    setBusyTarget(target.id)
    setRequestError('')
    try {
      await api.testNotificationTarget(target.id)
      await refresh()
      actionToast.success('通知目标测试成功')
    } catch (caught) {
      const message = safeNotificationError(caught, '通知目标测试失败。')
      setRequestError(message)
      actionToast.danger('通知目标测试失败', { description: message })
    } finally {
      setBusyTarget(null)
    }
  }

  async function toggleTarget(target: NotificationTarget) {
    setBusyTarget(target.id)
    setRequestError('')
    try {
      await api.updateNotificationTarget(target.id, {
        enabled: !target.enabled,
      })
      await refresh()
      actionToast.success(target.enabled ? '通知目标已暂停' : '通知目标已启用')
    } catch (caught) {
      const message = safeNotificationError(caught, '通知目标状态更新失败。')
      setRequestError(message)
      actionToast.danger('通知目标状态更新失败', { description: message })
    } finally {
      setBusyTarget(null)
    }
  }

  async function saveTarget(target: NotificationTarget) {
    const nextName = editName.trim()
    const nextDestination = editDestination.trim()
    if (!nextName && !nextDestination) return
    setEditDestination('')
    setBusyTarget(target.id)
    setRequestError('')
    try {
      await api.updateNotificationTarget(target.id, {
        ...(nextName && nextName !== target.name ? { name: nextName } : {}),
        ...(nextDestination
          ? target.channel === 'email'
            ? { email_address: nextDestination }
            : target.channel === 'telegram'
              ? { telegram_chat_id: nextDestination }
              : {
                  webhook_url: nextDestination,
                  webhook_provider: target.webhook_provider ?? 'generic_event',
                }
          : {}),
      })
      setEditingTarget(null)
      await refresh()
      actionToast.success(
        nextDestination
          ? '通知目标已更新，请重新测试后启用'
          : '通知目标名称已更新',
      )
    } catch (caught) {
      const message = safeNotificationError(caught, '通知目标更新失败。')
      setRequestError(message)
      actionToast.danger('通知目标更新失败', { description: message })
    } finally {
      setBusyTarget(null)
    }
  }

  async function archiveTarget(target: NotificationTarget) {
    if (confirmArchive !== target.id) {
      setConfirmArchive(target.id)
      return
    }
    setBusyTarget(target.id)
    setRequestError('')
    try {
      await api.archiveNotificationTarget(target.id)
      setConfirmArchive(null)
      await refresh()
      actionToast.success('通知目标已归档')
    } catch (caught) {
      const message = safeNotificationError(
        caught,
        '请先从所有业务中取消选择该目标。',
      )
      setRequestError(message)
      actionToast.danger('通知目标无法归档', { description: message })
    } finally {
      setBusyTarget(null)
    }
  }

  if (targets.isPending) {
    return <LoadingState label="正在读取通知目标" rows={3} />
  }
  if (targets.isError || !targets.data) {
    return <HeroNotice title="通知目标读取失败，请刷新后重试。" />
  }

  return <div className="grid min-w-0 gap-4">
    <div>
      <h3 className="type-title">通知目标</h3>
      <Description>
        邮箱、Webhook 或 Telegram 会话只在这里配置和测试一次；个人通知与系统告警直接复用。
      </Description>
    </div>
    <div className="grid min-w-0 gap-3 min-[768px]:grid-cols-2 min-[1280px]:grid-cols-3">
      {targets.data.targets.map((target) => {
        const busy = busyTarget === target.id
        const usageCount = target.usage.user_binding_count + target.usage.alert_binding_count
        return <Card key={target.id} className="grid min-w-0 gap-3 p-4">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <Card.Title>{target.name}</Card.Title>
              <Card.Description>
                {target.scope === 'shared' ? '工作区共享' : '我的目标'} · {channelLabels[target.channel]}
              </Card.Description>
            </div>
            <span className="type-caption shrink-0 rounded-full bg-surface-secondary px-2 py-1 text-muted">
              {targetStatus(target)}
            </span>
          </div>
          <Description>
            当前 generation {target.config_generation}
            {usageCount > 0 ? ` · ${usageCount} 个业务正在使用` : ' · 尚未被业务选择'}
          </Description>
          {editingTarget === target.id && <div className="grid gap-3 border-t border-separator pt-3">
            <TextField fullWidth value={editName} onChange={setEditName}>
              <Label>名称</Label>
              <Input maxLength={80} />
            </TextField>
            <TextField
              fullWidth
              value={editDestination}
              onChange={setEditDestination}
            >
              <Label>重新填写{destinationLabel(target.channel)}</Label>
              <Input
                type={target.channel === 'email' ? 'email' : 'password'}
                autoComplete="off"
                placeholder="留空保持当前值；保存后不会回显"
              />
            </TextField>
            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                isDisabled={busy || (!editName.trim() && !editDestination.trim())}
                onPress={() => void saveTarget(target)}
              >保存目标</Button>
              <Button
                size="sm"
                variant="ghost"
                isDisabled={busy}
                onPress={() => {
                  setEditingTarget(null)
                  setEditDestination('')
                }}
              >取消</Button>
            </div>
          </div>}
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              isDisabled={!target.can_test || busy}
              onPress={() => void testTarget(target)}
            >{busy ? '处理中…' : '发送测试'}</Button>
            <Button
              size="sm"
              variant="secondary"
              isDisabled={!target.can_edit || busy || (!target.enabled && !target.can_enable)}
              onPress={() => void toggleTarget(target)}
            >{target.enabled ? '暂停' : '启用'}</Button>
            {target.can_edit && <Button
              size="sm"
              variant="ghost"
              isDisabled={busy}
              onPress={() => {
                setEditingTarget(target.id)
                setEditName(target.name)
                setEditDestination('')
              }}
            >编辑</Button>}
            {target.can_edit && <Button
              size="sm"
              variant="ghost"
              isDisabled={busy}
              onPress={() => void archiveTarget(target)}
            >{confirmArchive === target.id ? '再次点击确认归档' : '归档'}</Button>}
          </div>
        </Card>
      })}
      {targets.data.targets.length === 0 && <HeroNotice
        title="还没有通知目标"
        status="default"
        role="status"
      >先创建一个接收地址，测试并启用后即可供业务选择。</HeroNotice>}
    </div>

    {!readOnly && <form
      className="grid min-w-0 gap-3 rounded-control border border-separator bg-surface-secondary p-4 min-[768px]:grid-cols-2"
      noValidate
      onSubmit={createTarget}
    >
      <div className="min-[768px]:col-span-2">
        <h4 className="type-control">新增通知目标</h4>
      </div>
      <TextField fullWidth value={name} onChange={setName} isRequired>
        <Label>目标名称</Label>
        <Input maxLength={80} placeholder="例如：值班群 Telegram" />
      </TextField>
      <label className="grid gap-1">
        <span className="type-control">作用范围</span>
        <select
          className="min-h-10 rounded-control border border-separator bg-surface px-3"
          value={scope}
          onChange={(event) => setScope(event.target.value as NotificationTargetScope)}
        >
          <option value="private">我的目标</option>
          {admin && <option value="shared">工作区共享目标</option>}
        </select>
      </label>
      <label className="grid gap-1">
        <span className="type-control">渠道</span>
        <select
          className="min-h-10 rounded-control border border-separator bg-surface px-3"
          value={channel}
          onChange={(event) => {
            setChannel(event.target.value as NotificationChannel)
            setDestination('')
          }}
        >
          <option value="email">邮箱</option>
          <option value="webhook">Webhook</option>
          <option value="telegram">Telegram</option>
        </select>
      </label>
      {channel === 'webhook' && <label className="grid gap-1">
        <span className="type-control">Webhook 类型</span>
        <select
          className="min-h-10 rounded-control border border-separator bg-surface px-3"
          value={provider}
          onChange={(event) => setProvider(event.target.value as WebhookProvider)}
        >
          {targets.data.webhook_provider_options.map((option) => <option
            key={option.provider}
            value={option.provider}
          >{option.label}</option>)}
        </select>
      </label>}
      <TextField
        fullWidth
        value={destination}
        onChange={setDestination}
        isRequired
      >
        <Label>{destinationLabel(channel)}</Label>
        <Input
          type={channel === 'email' ? 'email' : 'password'}
          autoComplete="off"
          placeholder="只写保存，后续不会回显"
        />
      </TextField>
      <div className="flex items-end min-[768px]:col-span-2">
        <Button type="submit" isDisabled={creating || !name.trim() || !destination.trim()}>
          {creating ? '创建中…' : '创建通知目标'}
        </Button>
      </div>
    </form>}
    {requestError && <HeroNotice title={requestError} />}
  </div>
}
