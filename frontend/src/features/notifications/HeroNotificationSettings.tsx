import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationChannel,
  NotificationTestResult,
  UserNotificationSettings,
  UserNotificationSettingsPatch,
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
  const [fieldError, setFieldError] = useState('')
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const configured = notificationChannelConfigured(settings, channel)
  const persistedConfigured = notificationChannelConfigured(settings, settings.channel)
  const dirty = enabled !== settings.enabled || channel !== settings.channel || Boolean(destination.trim())
  const emailUnavailable = channel === 'email' && !settings.email_transport_ready
  const persistedEmailUnavailable = settings.channel === 'email' && !settings.email_transport_ready
  const testReady = !readOnly && persistedConfigured && !persistedEmailUnavailable && !dirty && !saving && !testing
  const lastTestTime = formatLastTest(settings.last_tested_at)

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (readOnly || saving || testing) return
    const submittedDestination = destination.trim()
    setDestination('')
    setFieldError('')
    setRequestError('')
    if (enabled && emailUnavailable) {
      setRequestError('工作区邮件发送服务尚未就绪，暂不能启用邮箱通知。Webhook 不受影响。')
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
    setSaving(true)
    try {
      await onSave({
        enabled,
        channel,
        ...(submittedDestination
          ? channel === 'email'
            ? { email_address: submittedDestination }
            : { webhook_url: submittedDestination }
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

  async function sendTest() {
    if (readOnly || !testReady) return
    setTesting(true)
    setRequestError('')
    try {
      await onTest()
      actionToast.success('测试通知已发送', { description: '请检查当前通知方式的接收端。' })
    } catch (caught) {
      const message = safeNotificationError(caught, '测试通知发送失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('测试通知发送失败', { description: message })
    } finally {
      setTesting(false)
    }
  }

  return <form className="grid gap-4" onSubmit={save}>
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
          setFieldError('')
          setRequestError('')
        }}
        options={[
          { id: 'email', label: '邮箱' },
          { id: 'webhook', label: 'Webhook' },
        ]}
      />
      <TextField
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
        <Label>{channel === 'email' ? '收件邮箱' : 'Webhook 地址'}</Label>
        <Input
          type={channel === 'email' ? 'email' : 'password'}
          autoComplete={channel === 'email' ? 'email' : 'new-password'}
          placeholder={configured ? '留空保持当前配置' : channel === 'email' ? 'name@example.com' : '输入 HTTPS 地址'}
        />
        <Description>
          {configured
            ? '已配置；真实接收地址不会回显，留空不会覆盖。'
            : '尚未配置当前通知方式。'}
        </Description>
        {fieldError && <FieldError>{fieldError}</FieldError>}
      </TextField>
    </div>
    <div className="type-body rounded-control border border-separator bg-surface-secondary p-3 text-muted">
      <p>只推送开启后首次入库的新内容；已有历史、来源复用内容和停用期间内容不会补发。</p>
      <p className="mt-1">测试通知使用模拟内容，不会抓取来源，也不会改变新内容投递起点。</p>
      <p className="type-meta mt-2">{notificationTestLabel(settings.last_test_status)}{lastTestTime ? ` · ${lastTestTime}` : ''}</p>
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
    settings.data.last_tested_at,
    settings.data.last_test_status,
  ].join(':')

  async function save(patch: UserNotificationSettingsPatch) {
    const updated = await api.updateNotificationSettings(patch)
    queryClient.setQueryData(queryKeys.notificationSettings(user.id), updated)
    return updated
  }

  async function test() {
    const result = await api.testNotificationSettings()
    await queryClient.invalidateQueries({ queryKey: queryKeys.notificationSettings(user.id) })
    return result
  }

  return <NotificationSettingsForm
    key={cacheKey}
    settings={settings.data}
    onSave={save}
    onTest={test}
    readOnly={user.role === 'viewer'}
  />
}
