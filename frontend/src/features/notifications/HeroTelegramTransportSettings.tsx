import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationTelegramTransport,
  NotificationTelegramTransportPatch,
  NotificationTelegramTransportTestResult,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Card,
  Description,
  FieldError,
  Input,
  Label,
  LoadingState,
  Switch,
  TextField,
} from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'
import { notificationDestinationError, safeNotificationError } from './notificationModel'

const botTokenPattern = /^\d{5,20}:[A-Za-z0-9_-]{30,100}$/

function formatLastTest(value: string | null): string {
  if (!value) return '尚未测试'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚未测试'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

export function TelegramTransportSettingsForm({
  settings,
  onSave,
  onTest,
  onDelete,
}: {
  settings: NotificationTelegramTransport
  onSave: (patch: NotificationTelegramTransportPatch) => Promise<NotificationTelegramTransport>
  onTest: (chatId: string) => Promise<NotificationTelegramTransportTestResult>
  onDelete: () => Promise<void>
}) {
  const [botToken, setBotToken] = useState('')
  const [chatId, setChatId] = useState('')
  const [tokenError, setTokenError] = useState('')
  const [chatError, setChatError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const busy = saving || testing || deleting
  const configDirty = Boolean(botToken)
  const canTest = (
    settings.configured
    && settings.token_configured
    && !configDirty
    && !notificationDestinationError({
      channel: 'telegram',
      destination: chatId,
      configured: false,
      enabled: true,
    })
    && !busy
  )
  const canToggle = !busy && (settings.enabled || (!configDirty && settings.can_enable))

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const submittedToken = botToken.trim()
    setBotToken('')
    setTokenError('')
    setRequestError('')
    if (!submittedToken) return
    if (!botTokenPattern.test(submittedToken)) {
      setTokenError('请输入有效的 Telegram Bot Token。')
      return
    }
    setSaving(true)
    try {
      await onSave({ bot_token: submittedToken })
      actionToast.success('Telegram Bot 配置已保存', {
        description: '请发送测试消息；测试成功后才能启用。',
      })
    } catch (caught) {
      const message = safeNotificationError(caught, 'Telegram Bot 配置保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('Telegram Bot 配置保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function sendTest() {
    if (!canTest) return
    const submittedChatId = chatId.trim()
    setChatId('')
    setChatError('')
    setRequestError('')
    setTesting(true)
    try {
      await onTest(submittedChatId)
      actionToast.success('Telegram 测试消息已发送', {
        description: '请检查目标会话；确认成功后即可启用 Bot 服务。',
      })
    } catch (caught) {
      const message = safeNotificationError(caught, 'Telegram 测试消息发送失败，请检查配置后重试。')
      setRequestError(message)
      actionToast.danger('Telegram 测试消息发送失败', { description: message })
    } finally {
      setTesting(false)
    }
  }

  async function toggleEnabled(nextEnabled: boolean) {
    if (!canToggle) return
    setSaving(true)
    setRequestError('')
    try {
      await onSave({ enabled: nextEnabled })
      actionToast.success(nextEnabled ? 'Telegram Bot 服务已启用' : 'Telegram Bot 服务已停用')
    } catch (caught) {
      const message = safeNotificationError(caught, 'Telegram Bot 服务状态更新失败。')
      setRequestError(message)
      actionToast.danger('Telegram Bot 服务状态更新失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function removeTransport() {
    if (!settings.configured || busy) return
    if (!confirmDelete) {
      setConfirmDelete(true)
      return
    }
    setDeleting(true)
    setRequestError('')
    try {
      await onDelete()
      actionToast.success('Telegram Bot 配置已删除')
    } catch (caught) {
      const message = safeNotificationError(caught, 'Telegram Bot 配置删除失败。')
      setRequestError(message)
      actionToast.danger('Telegram Bot 配置删除失败', { description: message })
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  return <Card variant="transparent" className="grid min-w-0 gap-4 p-4 min-[768px]:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <Card.Title>Telegram Bot 服务</Card.Title>
        <Card.Description className="mt-1">Owner/Admin 统一配置 Bot Token；个人通知和运行告警分别填写 Chat ID。</Card.Description>
      </div>
      <Switch
        isSelected={settings.enabled}
        isDisabled={!canToggle}
        onChange={(value) => void toggleEnabled(value)}
      >
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>
          {settings.enabled ? 'Telegram 已启用' : 'Telegram 未启用'}
        </Switch.Content>
      </Switch>
    </div>

    {settings.ready
      ? <HeroNotice title="Telegram Bot 服务已就绪" status="success" role="status">
        新产生的通知和运行告警可以通过 Telegram 发送。
      </HeroNotice>
      : <HeroNotice
          title={settings.last_test_status === 'failed'
            ? '上次 Telegram 测试失败'
            : '按顺序完成：保存 Token → 发送测试消息 → 启用'}
          status="warning"
          role="status"
        >
          Token 变化会自动停用服务并要求重新测试；停用期间不入队，也不补发。
        </HeroNotice>}

    <form className="grid gap-3" noValidate onSubmit={save}>
      <TextField
        fullWidth
        value={botToken}
        onChange={(value) => {
          setBotToken(value)
          setTokenError('')
          setRequestError('')
        }}
        isDisabled={busy}
        isRequired={!settings.token_configured}
        isInvalid={Boolean(tokenError)}
      >
        <Label>Bot Token</Label>
        <Input
          type="password"
          autoComplete="new-password"
          placeholder={settings.token_configured ? '留空保持当前 Token' : '保存后不会回显'}
        />
        <Description>Token 只写入 SecretStore，提交开始即从表单清空。</Description>
        {tokenError && <FieldError>{tokenError}</FieldError>}
      </TextField>
      <div className="flex flex-wrap gap-2">
        <Button type="submit" isDisabled={!configDirty || busy}>{saving ? '保存中…' : '保存 Token'}</Button>
        {settings.configured && <Button
          type="button"
          variant="ghost"
          isDisabled={busy}
          onPress={() => void removeTransport()}
        >{deleting ? '删除中…' : confirmDelete ? '再次点击确认删除' : '删除配置'}</Button>}
      </div>
    </form>

    <div className="grid gap-3 border-t border-separator pt-4 min-[720px]:grid-cols-[minmax(0,1fr)_auto] min-[720px]:items-end">
      <TextField
        fullWidth
        value={chatId}
        onChange={(value) => {
          setChatId(value)
          setChatError('')
          setRequestError('')
        }}
        isDisabled={busy || !settings.configured || configDirty}
        isInvalid={Boolean(chatError)}
      >
        <Label>一次性测试 Chat ID</Label>
        <Input type="password" autoComplete="off" placeholder="-1001234567890 或 @channel" />
        <Description>
          仅用于本次测试，不保存。当前 generation {settings.generation}
          {settings.last_test_status === 'sent'
            ? ` 已测试成功 · ${formatLastTest(settings.last_tested_at)}`
            : ` ${settings.last_test_status === 'failed' ? '测试失败' : '尚未测试'}`}
        </Description>
        {chatError && <FieldError>{chatError}</FieldError>}
      </TextField>
      <Button
        type="button"
        variant="secondary"
        isDisabled={!canTest}
        onPress={() => void sendTest()}
      >{testing ? '发送中…' : '发送 Telegram 测试'}</Button>
    </div>
    {requestError && <HeroNotice title={requestError} />}
  </Card>
}

export function HeroTelegramTransportSettings({ queryEnabled = true }: { queryEnabled?: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const transport = useQuery({
    queryKey: queryKeys.notificationTelegramTransport(user.id),
    queryFn: ({ signal }) => api.notificationTelegramTransport(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })

  if (transport.isPending) return <LoadingState label="正在读取 Telegram Bot 服务" rows={2} />
  if (transport.isError || !transport.data) {
    return <HeroNotice title="Telegram Bot 服务读取失败，请刷新后重试。" />
  }

  const cacheKey = [
    transport.data.configured,
    transport.data.enabled,
    transport.data.token_configured,
    transport.data.generation,
    transport.data.last_test_status,
  ].join(':')

  async function save(patch: NotificationTelegramTransportPatch) {
    const updated = await api.updateNotificationTelegramTransport(patch)
    queryClient.setQueryData(queryKeys.notificationTelegramTransport(user.id), updated)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.notificationSettings(user.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorAlertSettings(user.id) }),
    ])
    return updated
  }

  async function test(chatId: string) {
    const result = await api.testNotificationTelegramTransport(chatId)
    await queryClient.invalidateQueries({
      queryKey: queryKeys.notificationTelegramTransport(user.id),
    })
    return result
  }

  async function remove() {
    await api.deleteNotificationTelegramTransport()
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.notificationTelegramTransport(user.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.notificationSettings(user.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorAlertSettings(user.id) }),
    ])
  }

  return <TelegramTransportSettingsForm
    key={cacheKey}
    settings={transport.data}
    onSave={save}
    onTest={test}
    onDelete={remove}
  />
}
