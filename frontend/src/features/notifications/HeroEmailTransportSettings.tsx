import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import type {
  NotificationEmailProvider,
  NotificationEmailTransport,
  NotificationEmailTransportPatch,
  NotificationEmailTransportTestResult,
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
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import { safeNotificationError } from './notificationModel'

type TransportField = 'senderEmail' | 'senderName' | 'region' | 'smtpUsername' | 'credential' | 'recipient'
type TransportErrors = Partial<Record<TransportField, string>>

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

function validEmail(value: string): boolean {
  return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)
}

function senderPlaceholder(provider: NotificationEmailProvider): string {
  if (provider === 'qq') return 'name@qq.com'
  if (provider === 'netease') return 'name@163.com'
  if (provider === 'gmail') return 'name@gmail.com'
  return 'notice@example.com'
}

export function EmailTransportSettingsForm({
  settings,
  onSave,
  onTest,
  onDelete,
}: {
  settings: NotificationEmailTransport
  onSave: (patch: NotificationEmailTransportPatch) => Promise<NotificationEmailTransport>
  onTest: (recipientEmail: string) => Promise<NotificationEmailTransportTestResult>
  onDelete: () => Promise<void>
}) {
  const [provider, setProvider] = useState<NotificationEmailProvider>(settings.provider ?? 'qq')
  const [senderEmail, setSenderEmail] = useState(settings.sender_email ?? '')
  const [senderName, setSenderName] = useState(settings.sender_name || 'Inteliscope')
  const [region, setRegion] = useState(settings.region ?? '')
  const [smtpUsername, setSmtpUsername] = useState(settings.smtp_username ?? '')
  const [credential, setCredential] = useState('')
  const [recipient, setRecipient] = useState('')
  const [errors, setErrors] = useState<TransportErrors>({})
  const [requestError, setRequestError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const preset = settings.providers.find((option) => option.provider === provider)
  const usesSesFields = provider === 'amazon_ses'
  const busy = saving || testing || deleting
  const configDirty = (
    provider !== settings.provider
    || senderEmail.trim() !== (settings.sender_email ?? '')
    || senderName.trim() !== settings.sender_name
    || (usesSesFields ? region.trim() !== (settings.region ?? '') : Boolean(settings.region))
    || (usesSesFields ? smtpUsername.trim() !== (settings.smtp_username ?? '') : Boolean(settings.smtp_username))
    || Boolean(credential)
  )
  const canTest = (
    settings.configured
    && settings.credential_configured
    && !configDirty
    && validEmail(recipient.trim())
    && !busy
  )
  const canToggle = (
    !busy
    && (settings.enabled || (!configDirty && settings.can_enable))
  )

  function clearError(field: TransportField) {
    setErrors((current) => ({ ...current, [field]: undefined }))
    setRequestError('')
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const submittedCredential = credential
    setCredential('')
    setErrors({})
    setRequestError('')
    const nextErrors: TransportErrors = {}
    if (!validEmail(senderEmail.trim())) nextErrors.senderEmail = '请输入有效的完整发件邮箱。'
    if (!senderName.trim()) nextErrors.senderName = '发件名称不能为空。'
    if (usesSesFields && !region.trim()) nextErrors.region = 'Amazon SES Region 不能为空。'
    if (usesSesFields && !smtpUsername.trim()) nextErrors.smtpUsername = 'SES SMTP 用户名不能为空。'
    if (!settings.credential_configured && !submittedCredential) {
      nextErrors.credential = `首次保存必须填写${preset?.credential_label ?? '凭据'}。`
    }
    if (Object.keys(nextErrors).length) {
      setErrors(nextErrors)
      return
    }
    setSaving(true)
    try {
      await onSave({
        provider,
        sender_email: senderEmail.trim(),
        sender_name: senderName.trim(),
        region: usesSesFields ? region.trim() : null,
        smtp_username: usesSesFields ? smtpUsername.trim() : null,
        ...(submittedCredential ? { credential: submittedCredential } : {}),
      })
      actionToast.success('邮件发送服务配置已保存', {
        description: '请发送测试邮件；测试成功后才能启用。',
      })
    } catch (caught) {
      const message = safeNotificationError(caught, '邮件发送服务保存失败，请稍后重试。')
      setRequestError(message)
      actionToast.danger('邮件发送服务保存失败', { description: message })
    } finally {
      setSaving(false)
    }
  }

  async function sendTest() {
    if (!canTest) return
    const submittedRecipient = recipient.trim()
    setRecipient('')
    setErrors({})
    setRequestError('')
    setTesting(true)
    try {
      await onTest(submittedRecipient)
      actionToast.success('测试邮件已发送', {
        description: '请检查收件箱；确认成功后即可启用发件服务。',
      })
    } catch (caught) {
      const message = safeNotificationError(caught, '测试邮件发送失败，请检查配置后重试。')
      setRequestError(message)
      actionToast.danger('测试邮件发送失败', { description: message })
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
      actionToast.success(nextEnabled ? '邮件发送服务已启用' : '邮件发送服务已停用')
    } catch (caught) {
      const message = safeNotificationError(caught, '邮件发送服务状态更新失败。')
      setRequestError(message)
      actionToast.danger('邮件发送服务状态更新失败', { description: message })
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
      actionToast.success('邮件发送服务配置已删除')
    } catch (caught) {
      const message = safeNotificationError(caught, '邮件发送服务删除失败。')
      setRequestError(message)
      actionToast.danger('邮件发送服务删除失败', { description: message })
    } finally {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  return <Card variant="transparent" className="grid gap-4 p-4 min-[768px]:p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <Card.Title>邮件发送服务</Card.Title>
        <Card.Description className="mt-1">Owner/Admin 统一配置发件账号；成员只填写自己的收件邮箱。</Card.Description>
      </div>
      <Switch
        isSelected={settings.enabled}
        isDisabled={!canToggle}
        onChange={(value) => void toggleEnabled(value)}
      >
        <Switch.Content><Switch.Control><Switch.Thumb /></Switch.Control>{settings.enabled ? '已启用' : '未启用'}</Switch.Content>
      </Switch>
    </div>

    {settings.ready
      ? <HeroNotice title="邮件发送服务已就绪" status="success" role="status">
        新产生的偏好来源内容可以发送邮件通知。
      </HeroNotice>
      : <HeroNotice title={settings.last_test_status === 'failed' ? '上次测试失败' : '按顺序完成：保存配置 → 发送测试邮件 → 启用'} status="warning" role="status">
        配置变化会自动停用服务并要求重新测试；停用期间不会入队，也不会补发。
      </HeroNotice>}

    <form className="grid gap-4" noValidate onSubmit={save}>
      <div className="grid gap-4 min-[720px]:grid-cols-2">
        <HeroSelect
          label="邮件服务商"
          value={provider}
          isDisabled={busy}
          onChange={(value) => {
            setProvider(value as NotificationEmailProvider)
            setCredential('')
            setErrors({})
            setRequestError('')
          }}
          options={settings.providers.map((option) => ({
            id: option.provider,
            label: option.label,
            description: option.sender_hint,
          }))}
        />
        <TextField
          fullWidth
          value={senderEmail}
          onChange={(value) => {
            setSenderEmail(value)
            clearError('senderEmail')
          }}
          isDisabled={busy}
          isRequired
          isInvalid={Boolean(errors.senderEmail)}
        >
          <Label>发件邮箱</Label>
          <Input type="email" autoComplete="email" placeholder={senderPlaceholder(provider)} />
          {errors.senderEmail && <FieldError>{errors.senderEmail}</FieldError>}
        </TextField>
        <TextField
          fullWidth
          value={senderName}
          onChange={(value) => {
            setSenderName(value)
            clearError('senderName')
          }}
          isDisabled={busy}
          isRequired
          isInvalid={Boolean(errors.senderName)}
        >
          <Label>发件名称</Label>
          <Input placeholder="Inteliscope" />
          {errors.senderName && <FieldError>{errors.senderName}</FieldError>}
        </TextField>
        <TextField
          fullWidth
          value={credential}
          onChange={(value) => {
            setCredential(value)
            clearError('credential')
          }}
          isDisabled={busy}
          isRequired={!settings.credential_configured}
          isInvalid={Boolean(errors.credential)}
        >
          <Label>{preset?.credential_label ?? '发件凭据'}</Label>
          <Input
            type="password"
            autoComplete="new-password"
            placeholder={settings.credential_configured ? '留空保持当前凭据' : '保存后不会回显'}
          />
          <Description>凭据只写入 SecretStore，提交后立即从表单清空。</Description>
          {errors.credential && <FieldError>{errors.credential}</FieldError>}
        </TextField>
        {usesSesFields && <>
          <TextField
            fullWidth
            value={region}
            onChange={(value) => {
              setRegion(value)
              clearError('region')
            }}
            isDisabled={busy}
            isRequired
            isInvalid={Boolean(errors.region)}
          >
            <Label>Amazon SES Region</Label>
            <Input placeholder="ap-southeast-1" />
            {errors.region && <FieldError>{errors.region}</FieldError>}
          </TextField>
          <TextField
            fullWidth
            value={smtpUsername}
            onChange={(value) => {
              setSmtpUsername(value)
              clearError('smtpUsername')
            }}
            isDisabled={busy}
            isRequired
            isInvalid={Boolean(errors.smtpUsername)}
          >
            <Label>SES SMTP 用户名</Label>
            <Input autoComplete="username" />
            {errors.smtpUsername && <FieldError>{errors.smtpUsername}</FieldError>}
          </TextField>
        </>}
      </div>
      {settings.connection && <div className="type-meta rounded-control border border-separator bg-surface-secondary p-3 text-muted">
        固定连接：{settings.connection.smtp_host}:{settings.connection.smtp_port} · SSL · 登录名 {settings.connection.smtp_username}
      </div>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" isDisabled={!configDirty || busy}>{saving ? '保存中…' : '保存配置'}</Button>
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
        value={recipient}
        onChange={(value) => {
          setRecipient(value)
          clearError('recipient')
        }}
        isDisabled={busy || !settings.configured || configDirty}
        isInvalid={Boolean(errors.recipient)}
      >
        <Label>测试收件邮箱</Label>
        <Input type="email" autoComplete="email" placeholder="只用于本次测试，不会保存" />
        <Description>
          {settings.last_test_status === 'sent'
            ? `当前 generation ${settings.generation} 已测试成功 · ${formatLastTest(settings.last_tested_at)}`
            : `当前 generation ${settings.generation} ${settings.last_test_status === 'failed' ? '测试失败' : '尚未测试'}`}
        </Description>
      </TextField>
      <Button
        type="button"
        variant="secondary"
        isDisabled={!canTest}
        onPress={() => void sendTest()}
      >{testing ? '发送中…' : '发送测试邮件'}</Button>
    </div>
    {requestError && <HeroNotice title={requestError} />}
  </Card>
}

export function HeroEmailTransportSettings() {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const transport = useQuery({
    queryKey: queryKeys.notificationEmailTransport(user.id),
    queryFn: ({ signal }) => api.notificationEmailTransport(signal),
  })

  if (transport.isLoading) return <LoadingState label="正在读取邮件发送服务" rows={2} />
  if (transport.isError || !transport.data) {
    return <HeroNotice title="邮件发送服务读取失败，请刷新后重试。" />
  }

  const cacheKey = [
    transport.data.provider,
    transport.data.sender_email,
    transport.data.sender_name,
    transport.data.region,
    transport.data.smtp_username,
    transport.data.enabled,
    transport.data.credential_configured,
    transport.data.generation,
    transport.data.last_test_status,
  ].join(':')

  async function save(patch: NotificationEmailTransportPatch) {
    const updated = await api.updateNotificationEmailTransport(patch)
    queryClient.setQueryData(
      queryKeys.notificationEmailTransport(user.id),
      updated,
    )
    await queryClient.invalidateQueries({
      queryKey: queryKeys.notificationSettings(user.id),
    })
    return updated
  }

  async function test(recipientEmail: string) {
    const result = await api.testNotificationEmailTransport(recipientEmail)
    await queryClient.invalidateQueries({
      queryKey: queryKeys.notificationEmailTransport(user.id),
    })
    return result
  }

  async function remove() {
    await api.deleteNotificationEmailTransport()
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.notificationEmailTransport(user.id),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.notificationSettings(user.id),
      }),
    ])
  }

  return <EmailTransportSettingsForm
    key={cacheKey}
    settings={transport.data}
    onSave={save}
    onTest={test}
    onDelete={remove}
  />
}
