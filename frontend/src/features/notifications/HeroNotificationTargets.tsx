import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  NotificationChannel,
  NotificationEmailProvider,
  NotificationService,
  NotificationServiceEmailTransportPatch,
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

const botTokenPattern = /^\d{5,20}:[A-Za-z0-9_-]{30,100}$/
const emailPattern = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

function destinationLabel(channel: NotificationChannel): string {
  if (channel === 'email') return '收件邮箱'
  if (channel === 'telegram') return '群组或会话 Chat ID'
  return 'Webhook 地址'
}

function serviceStatus(service: NotificationService): string {
  if (!service.configured) return '未配置'
  if (!service.transport_ready && service.channel !== 'webhook') return '共享凭据待验证'
  if (service.last_test_status === 'failed') return '测试失败'
  if (service.last_test_status === 'unknown') return '结果未知'
  if (service.last_test_status !== 'sent') return '待验证'
  if (!service.enabled) return '已暂停'
  return service.available ? '可用' : '暂不可用'
}

function serviceUnavailableReason(service: NotificationService): string {
  if (!service.configured) return '接收地址尚未保存'
  if (!service.transport_ready && service.channel !== 'webhook') {
    return service.channel === 'telegram'
      ? '共享 Bot Token 尚未通过验证'
      : '共享邮件凭据尚未通过验证'
  }
  if (service.last_test_status === 'unknown') return '上次测试结果未知，请确认接收端后再手动测试'
  if (service.last_test_status === 'failed') return '上次测试失败，请编辑后重试'
  if (service.last_test_status !== 'sent') return '当前配置尚未测试'
  if (!service.enabled) return '服务已暂停'
  return '服务暂不可用'
}

type EmailDraft = {
  provider: NotificationEmailProvider
  senderEmail: string
  senderName: string
  credential: string
  region: string
  smtpUsername: string
}

const emptyEmailDraft: EmailDraft = {
  provider: 'qq',
  senderEmail: '',
  senderName: 'Inteliscope',
  credential: '',
  region: '',
  smtpUsername: '',
}

function emailTransportPayload(draft: EmailDraft): NotificationServiceEmailTransportPatch {
  const usesSes = draft.provider === 'amazon_ses'
  return {
    provider: draft.provider,
    sender_email: draft.senderEmail.trim(),
    sender_name: draft.senderName.trim(),
    region: usesSes ? draft.region.trim() : null,
    smtp_username: usesSes ? draft.smtpUsername.trim() : null,
    ...(draft.credential ? { credential: draft.credential } : {}),
  }
}

export function HeroNotificationTargets({
  queryEnabled = true,
}: {
  queryEnabled?: boolean
}) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const services = useQuery({
    queryKey: queryKeys.notificationServices(user.id),
    queryFn: ({ signal }) => api.notificationServices(signal),
    enabled: queryEnabled,
    staleTime: queryStaleTime.settings,
  })
  const [name, setName] = useState('')
  const [channel, setChannel] = useState<NotificationChannel>('email')
  const [destination, setDestination] = useState('')
  const [provider, setProvider] = useState<WebhookProvider>('generic_event')
  const [signingSecret, setSigningSecret] = useState('')
  const [botToken, setBotToken] = useState('')
  const [emailDraft, setEmailDraft] = useState<EmailDraft>(emptyEmailDraft)
  const [replaceEmailCredential, setReplaceEmailCredential] = useState(false)
  const [busyService, setBusyService] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  const [editingService, setEditingService] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDestination, setEditDestination] = useState('')
  const [editWebhookProvider, setEditWebhookProvider] = useState<WebhookProvider>('generic_event')
  const [editSigningSecret, setEditSigningSecret] = useState('')
  const [editBotToken, setEditBotToken] = useState('')
  const [editEmailDraft, setEditEmailDraft] = useState<EmailDraft>(emptyEmailDraft)
  const [editReplaceEmailCredential, setEditReplaceEmailCredential] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState<string | null>(null)
  const [requestError, setRequestError] = useState('')

  const admin = Boolean(services.data?.can_manage)
  const emailCredential = services.data?.channel_credentials.email
  const telegramCredential = services.data?.channel_credentials.telegram

  function currentEmailDraft(): EmailDraft {
    return {
      provider: emailCredential?.provider ?? 'qq',
      senderEmail: '',
      senderName: emailCredential?.sender_name || 'Inteliscope',
      credential: '',
      region: emailCredential?.region ?? '',
      smtpUsername: '',
    }
  }

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.notificationServices(user.id),
      }),
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

  function validateDraft(
    draftChannel: NotificationChannel,
    draftDestination: string,
    draftToken: string,
    draftEmail: EmailDraft,
    configureEmailCredential: boolean,
  ): string {
    if (!name.trim()) return '请输入通知服务名称。'
    if (!draftDestination.trim()) return `请输入${destinationLabel(draftChannel)}。`
    if (draftChannel === 'email') {
      if (!emailPattern.test(draftDestination.trim())) return '请输入有效的收件邮箱。'
      if (configureEmailCredential) {
        if (!emailPattern.test(draftEmail.senderEmail.trim())) return '请输入有效的发件邮箱。'
        if (!draftEmail.senderName.trim()) return '请输入发件名称。'
        if (!draftEmail.credential) return '配置或更换邮箱服务时必须填写授权码或 API Key。'
        if (draftEmail.provider === 'amazon_ses' && (!draftEmail.region.trim() || !draftEmail.smtpUsername.trim())) {
          return 'Amazon SES 还需要 Region 和 SMTP 用户名。'
        }
      }
    }
    if (draftChannel === 'telegram') {
      if (!telegramCredential?.configured && !draftToken) return '首次配置 Telegram 服务时必须填写 Bot Token。'
      if (draftToken && !botTokenPattern.test(draftToken)) return '请输入有效的 Telegram Bot Token。'
    }
    return ''
  }

  async function createService(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!admin || creating) return
    const submittedDestination = destination.trim()
    const submittedToken = botToken.trim()
    const submittedSigning = signingSecret.trim()
    const submittedEmail = { ...emailDraft, credential: emailDraft.credential.trim() }
    const configureEmailCredential = channel === 'email'
      && (!emailCredential?.configured || replaceEmailCredential)
    const error = validateDraft(
      channel,
      submittedDestination,
      submittedToken,
      submittedEmail,
      configureEmailCredential,
    )
    if (error) {
      setRequestError(error)
      return
    }
    setDestination('')
    setBotToken('')
    setSigningSecret('')
    setEmailDraft((current) => ({
      ...current,
      senderEmail: '',
      credential: '',
      smtpUsername: '',
    }))
    setRequestError('')
    setCreating(true)
    let createdId = ''
    try {
      const created = await api.createNotificationService({
        name: name.trim(),
        scope: 'shared',
        channel,
        ...(channel === 'email'
          ? {
              email_address: submittedDestination,
              ...(configureEmailCredential
                ? { email_transport: emailTransportPayload(submittedEmail) }
                : {}),
            }
          : channel === 'telegram'
            ? {
                telegram_chat_id: submittedDestination,
                ...(submittedToken ? { telegram_bot_token: submittedToken } : {}),
              }
            : {
                webhook_url: submittedDestination,
                webhook_provider: provider,
                ...(submittedSigning ? { webhook_signing_secret: submittedSigning } : {}),
              }),
      })
      createdId = created.id
      await api.testAndEnableNotificationService(created.id)
      setName('')
      setReplaceEmailCredential(false)
      await refresh()
      actionToast.success('通知服务已保存并启用')
    } catch (caught) {
      await refresh()
      const message = safeNotificationError(caught, '通知服务保存或测试失败，请检查配置。')
      setRequestError(message)
      actionToast.danger(
        createdId ? '通知服务已保存，但测试未通过' : '通知服务保存失败',
        { description: message },
      )
    } finally {
      setCreating(false)
    }
  }

  async function testAndEnable(service: NotificationService) {
    setBusyService(service.id)
    setRequestError('')
    try {
      await api.testAndEnableNotificationService(service.id)
      await refresh()
      actionToast.success('通知服务测试成功并已启用')
    } catch (caught) {
      await refresh()
      const message = safeNotificationError(caught, '通知服务测试失败，请检查配置。')
      setRequestError(message)
      actionToast.danger('通知服务测试失败', { description: message })
    } finally {
      setBusyService(null)
    }
  }

  function beginEdit(service: NotificationService) {
    setEditingService(service.id)
    setEditName(service.name)
    setEditDestination('')
    setEditWebhookProvider(service.webhook_provider ?? 'generic_event')
    setEditSigningSecret('')
    setEditBotToken('')
    setEditEmailDraft(currentEmailDraft())
    setEditReplaceEmailCredential(false)
    setRequestError('')
  }

  async function saveAndTest(service: NotificationService) {
    if (!admin || busyService) return
    const submittedDestination = editDestination.trim()
    const submittedToken = editBotToken.trim()
    const submittedSigning = editSigningSecret.trim()
    const submittedEmail = {
      ...editEmailDraft,
      credential: editEmailDraft.credential.trim(),
    }
    if (submittedToken && !botTokenPattern.test(submittedToken)) {
      setRequestError('请输入有效的 Telegram Bot Token。')
      return
    }
    const configureEmailCredential = service.channel === 'email'
      && (!emailCredential?.configured || editReplaceEmailCredential)
    if (service.channel === 'email') {
      if (submittedDestination && !emailPattern.test(submittedDestination)) {
        setRequestError('请输入有效的收件邮箱。')
        return
      }
      if (configureEmailCredential) {
        if (!emailPattern.test(submittedEmail.senderEmail.trim())) {
          setRequestError('请输入有效的发件邮箱。')
          return
        }
        if (!submittedEmail.credential) {
          setRequestError('更换共享邮件凭据时必须填写授权码或 API Key。')
          return
        }
      }
    }
    setEditDestination('')
    setEditBotToken('')
    setEditSigningSecret('')
    setEditEmailDraft((current) => ({
      ...current,
      senderEmail: '',
      credential: '',
      smtpUsername: '',
    }))
    setBusyService(service.id)
    setRequestError('')
    let saved = false
    try {
      await api.updateNotificationService(service.id, {
        ...(editName.trim() && editName.trim() !== service.name ? { name: editName.trim() } : {}),
        ...(submittedDestination
          ? service.channel === 'email'
            ? { email_address: submittedDestination }
            : service.channel === 'telegram'
              ? { telegram_chat_id: submittedDestination }
              : { webhook_url: submittedDestination }
          : {}),
        ...(service.channel === 'webhook'
          ? {
              webhook_provider: editWebhookProvider,
              ...(submittedSigning ? { webhook_signing_secret: submittedSigning } : {}),
            }
          : {}),
        ...(service.channel === 'telegram' && submittedToken
          ? { telegram_bot_token: submittedToken }
          : {}),
        ...(configureEmailCredential
          ? { email_transport: emailTransportPayload(submittedEmail) }
          : {}),
      })
      saved = true
      await api.testAndEnableNotificationService(service.id)
      setEditingService(null)
      setEditDestination('')
      await refresh()
      actionToast.success('通知服务已保存、测试并启用')
    } catch (caught) {
      await refresh()
      const message = safeNotificationError(caught, '通知服务保存或测试失败，请检查配置。')
      setRequestError(message)
      actionToast.danger(
        saved ? '修改已保存，但测试未通过' : '通知服务修改失败',
        { description: message },
      )
    } finally {
      setBusyService(null)
    }
  }

  async function pause(service: NotificationService) {
    setBusyService(service.id)
    setRequestError('')
    try {
      if (service.legacy_private) {
        await api.updateNotificationTarget(service.id, { enabled: false })
      } else {
        await api.updateNotificationService(service.id, { enabled: false })
      }
      await refresh()
      actionToast.success('通知服务已暂停')
    } catch (caught) {
      const message = safeNotificationError(caught, '通知服务暂停失败。')
      setRequestError(message)
      actionToast.danger('通知服务暂停失败', { description: message })
    } finally {
      setBusyService(null)
    }
  }

  async function resume(service: NotificationService) {
    setBusyService(service.id)
    setRequestError('')
    try {
      if (service.legacy_private) {
        await api.updateNotificationTarget(service.id, { enabled: true })
      } else {
        await api.updateNotificationService(service.id, { enabled: true })
      }
      await refresh()
      actionToast.success('通知服务已启用')
    } catch (caught) {
      const message = safeNotificationError(caught, '通知服务启用失败。')
      setRequestError(message)
      actionToast.danger('通知服务启用失败', { description: message })
    } finally {
      setBusyService(null)
    }
  }

  async function archive(service: NotificationService) {
    if (confirmArchive !== service.id) {
      setConfirmArchive(service.id)
      return
    }
    setBusyService(service.id)
    setRequestError('')
    try {
      if (service.legacy_private) {
        await api.archiveNotificationTarget(service.id)
      } else {
        await api.archiveNotificationService(service.id)
      }
      setConfirmArchive(null)
      await refresh()
      actionToast.success('通知服务已归档')
    } catch (caught) {
      const message = safeNotificationError(caught, '请先从所有业务中取消选择该服务。')
      setRequestError(message)
      actionToast.danger('通知服务无法归档', { description: message })
    } finally {
      setBusyService(null)
    }
  }

  if (services.isPending) return <LoadingState label="正在读取通知服务" rows={3} />
  if (services.isError || !services.data) {
    return <HeroNotice title="通知服务读取失败，请刷新后重试。" />
  }

  const providerPreset = services.data.channel_credentials.email.providers.find(
    (option) => option.provider === emailDraft.provider,
  )

  return <div className="grid min-w-0 gap-4">
    <div>
      <h3 className="type-title">通知服务</h3>
      <Description>
        管理员在这里一次性配置接收地址、共享凭据并完成测试；个人通知和系统告警只选择已配置服务。
      </Description>
    </div>

    <div className="grid min-w-0 gap-3 min-[768px]:grid-cols-2 min-[1280px]:grid-cols-3">
      {services.data.services.map((service) => {
        const busy = busyService === service.id
        const usageCount = service.usage.user_binding_count + service.usage.alert_binding_count
        const canManageShared = admin && !service.legacy_private
        const canManageLegacy = service.legacy_private && service.can_edit
        const canResumeWithoutTest = Boolean(
          !service.enabled
          && service.can_enable
          && service.transport_ready
        )
        return <Card key={service.id} className="grid min-w-0 gap-3 p-4">
          <div className="flex min-w-0 items-start justify-between gap-3">
            <div className="min-w-0">
              <Card.Title>{service.name}</Card.Title>
              <Card.Description>
                {service.legacy_private ? '历史私人服务' : '工作区共享'} · {channelLabels[service.channel]}
              </Card.Description>
            </div>
            <span className="type-caption shrink-0 rounded-full bg-surface-secondary px-2 py-1 text-muted">
              {serviceStatus(service)}
            </span>
          </div>
          <Description>
            generation {service.config_generation}
            {usageCount > 0 ? ` · ${usageCount} 个业务正在使用` : ' · 尚未被业务选择'}
          </Description>
          {!service.available && <HeroNotice
            title={serviceUnavailableReason(service)}
            status="warning"
            role="status"
          />}

          {editingService === service.id && canManageShared && <div className="grid gap-3 border-t border-separator pt-3">
            <TextField fullWidth value={editName} onChange={setEditName}>
              <Label>服务名称</Label>
              <Input maxLength={80} />
            </TextField>
            <TextField fullWidth value={editDestination} onChange={setEditDestination}>
              <Label>重新填写{destinationLabel(service.channel)}</Label>
              <Input
                type={service.channel === 'email' ? 'email' : 'password'}
                autoComplete="off"
                placeholder="留空保持当前值；保存后不会回显"
              />
            </TextField>
            {service.channel === 'telegram' && <TextField
              fullWidth
              value={editBotToken}
              onChange={setEditBotToken}
            >
              <Label>更换共享 Bot Token（可选）</Label>
              <Input type="password" autoComplete="new-password" placeholder="留空复用当前 Token" />
            </TextField>}
            {service.channel === 'webhook' && <TextField
              fullWidth
              value={editSigningSecret}
              onChange={setEditSigningSecret}
            >
              <Label>更换签名密钥（可选）</Label>
              <Input type="password" autoComplete="new-password" placeholder="留空保持当前值" />
            </TextField>}
            {service.channel === 'webhook' && <label className="grid gap-1">
              <span className="type-control">Webhook 类型</span>
              <select
                className="min-h-10 rounded-control border border-separator bg-surface px-3"
                value={editWebhookProvider}
                onChange={(event) => setEditWebhookProvider(event.target.value as WebhookProvider)}
              >
                {services.data.webhook_provider_options.map((option) => <option
                  key={option.provider}
                  value={option.provider}
                >{option.label}</option>)}
              </select>
            </label>}
            {service.channel === 'email'
              && emailCredential?.configured
              && !editReplaceEmailCredential
              && <div className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3">
                <Description>当前共享邮件凭据保持不变，测试会直接复用。</Description>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onPress={() => setEditReplaceEmailCredential(true)}
                >更换共享邮件凭据</Button>
              </div>}
            {service.channel === 'email'
              && (!emailCredential?.configured || editReplaceEmailCredential)
              && <EmailCredentialFields
                draft={editEmailDraft}
                onChange={setEditEmailDraft}
                providers={services.data.channel_credentials.email.providers}
                credentialConfigured={false}
              />}
            <div className="flex flex-wrap gap-2">
              <Button size="sm" isDisabled={busy} onPress={() => void saveAndTest(service)}>
                {busy ? '处理中…' : '保存并测试'}
              </Button>
              <Button size="sm" variant="ghost" isDisabled={busy} onPress={() => setEditingService(null)}>
                取消
              </Button>
            </div>
          </div>}

          <div className="flex flex-wrap gap-2">
            {canManageShared && !service.available && !canResumeWithoutTest && <Button
              size="sm"
              variant="secondary"
              isDisabled={!service.can_validate || busy}
              onPress={() => void testAndEnable(service)}
            >{busy
                ? '处理中…'
                : service.enabled
                  ? '测试并恢复'
                  : '测试并启用'}</Button>}
            {(canManageShared || canManageLegacy) && canResumeWithoutTest && <Button
              size="sm"
              variant="secondary"
              isDisabled={busy}
              onPress={() => void resume(service)}
            >启用</Button>}
            {canManageShared && service.enabled && <Button
              size="sm"
              variant="secondary"
              isDisabled={busy}
              onPress={() => void pause(service)}
            >暂停</Button>}
            {canManageLegacy && service.enabled && <Button
              size="sm"
              variant="secondary"
              isDisabled={busy}
              onPress={() => void pause(service)}
            >暂停</Button>}
            {canManageShared && <Button
              size="sm"
              variant="ghost"
              isDisabled={busy}
              onPress={() => beginEdit(service)}
            >编辑</Button>}
            {(canManageShared || canManageLegacy) && <Button
              size="sm"
              variant="ghost"
              isDisabled={busy}
              onPress={() => void archive(service)}
            >{confirmArchive === service.id ? '再次点击确认归档' : '归档'}</Button>}
          </div>
        </Card>
      })}
      {services.data.services.length === 0 && <HeroNotice
        title="还没有通知服务"
        status="default"
        role="status"
      >管理员创建并测试一个服务后，个人通知和系统告警就能直接选择。</HeroNotice>}
    </div>

    {admin && <form
      className="grid min-w-0 gap-3 rounded-control border border-separator bg-surface-secondary p-4 min-[768px]:grid-cols-2"
      noValidate
      onSubmit={createService}
    >
      <div className="min-[768px]:col-span-2">
        <h4 className="type-control">新增通知服务</h4>
        <Description>新服务固定为工作区共享；唯一提交动作会保存配置、发送一次测试并在成功后自动启用。</Description>
      </div>
      <TextField fullWidth value={name} onChange={setName} isRequired>
        <Label>服务名称</Label>
        <Input maxLength={80} placeholder="例如：值班群 Telegram" />
      </TextField>
      <label className="grid gap-1">
        <span className="type-control">发送方式</span>
        <select
          className="min-h-10 rounded-control border border-separator bg-surface px-3"
          value={channel}
          onChange={(event) => {
            setChannel(event.target.value as NotificationChannel)
            setDestination('')
            setBotToken('')
            setSigningSecret('')
            setEmailDraft((current) => ({
              ...current,
              senderEmail: '',
              credential: '',
              smtpUsername: '',
            }))
            setReplaceEmailCredential(false)
            setRequestError('')
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
          {services.data.webhook_provider_options.map((option) => <option
            key={option.provider}
            value={option.provider}
          >{option.label}</option>)}
        </select>
      </label>}

      <TextField fullWidth value={destination} onChange={setDestination} isRequired>
        <Label>{destinationLabel(channel)}</Label>
        <Input
          type={channel === 'email' ? 'email' : 'password'}
          autoComplete="off"
          placeholder={channel === 'telegram' ? '例如：-1001234567890' : '只写保存，后续不会回显'}
        />
        {channel === 'telegram' && <Description>群组 Chat ID 通常以 -100 开头；机器人必须已加入群组并具备发言权限。</Description>}
      </TextField>

      {channel === 'telegram' && <TextField fullWidth value={botToken} onChange={setBotToken}>
        <Label>Bot Token{telegramCredential?.configured ? '（可留空复用）' : ''}</Label>
        <Input type="password" autoComplete="new-password" placeholder={telegramCredential?.configured ? '留空复用已配置 Token' : '从 BotFather 获取，保存后不会回显'} />
      </TextField>}

      {channel === 'webhook' && <TextField fullWidth value={signingSecret} onChange={setSigningSecret}>
        <Label>签名密钥（可选）</Label>
        <Input type="password" autoComplete="new-password" placeholder="保存后不会回显" />
      </TextField>}

      {channel === 'email'
        && emailCredential?.configured
        && !replaceEmailCredential
        && <div className="grid gap-2 rounded-control border border-separator bg-surface p-3">
          <Description>将复用已经验证的工作区邮件凭据；这里只新增收件服务。</Description>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onPress={() => {
              setEmailDraft(currentEmailDraft())
              setReplaceEmailCredential(true)
            }}
          >更换共享邮件凭据</Button>
        </div>}
      {channel === 'email'
        && (!emailCredential?.configured || replaceEmailCredential)
        && <EmailCredentialFields
          draft={emailDraft}
          onChange={setEmailDraft}
          providers={services.data.channel_credentials.email.providers}
          credentialConfigured={false}
        />}

      <div className="flex items-end min-[768px]:col-span-2">
        <Button type="submit" isDisabled={creating || !name.trim() || !destination.trim()}>
          {creating ? '保存并测试中…' : '保存并测试'}
        </Button>
      </div>
      {providerPreset
        && channel === 'email'
        && (!emailCredential?.configured || replaceEmailCredential)
        && <Description className="min-[768px]:col-span-2">
        {providerPreset.label} 使用 {providerPreset.security.toUpperCase()} / {providerPreset.smtp_port}；凭据只写入 SecretStore。
      </Description>}
    </form>}
    {!admin && <HeroNotice title="通知服务由管理员统一维护" status="default" role="status">
      你无需重复配置或测试；在下方业务设置中选择已经可用的服务即可。历史私人服务仍保留原有可见范围。
    </HeroNotice>}
    {requestError && <HeroNotice title={requestError} />}
  </div>
}

function EmailCredentialFields({
  draft,
  onChange,
  providers,
  credentialConfigured,
}: {
  draft: EmailDraft
  onChange: (draft: EmailDraft) => void
  providers: Array<{
    provider: NotificationEmailProvider
    label: string
    credential_label: string
  }>
  credentialConfigured: boolean
}) {
  const preset = providers.find((option) => option.provider === draft.provider)
  const usesSes = draft.provider === 'amazon_ses'
  return <>
    <label className="grid gap-1">
      <span className="type-control">邮件服务商</span>
      <select
        className="min-h-10 rounded-control border border-separator bg-surface px-3"
        value={draft.provider}
        onChange={(event) => onChange({
          ...draft,
          provider: event.target.value as NotificationEmailProvider,
          credential: '',
        })}
      >
        {providers.map((option) => <option key={option.provider} value={option.provider}>
          {option.label}
        </option>)}
      </select>
    </label>
    <TextField fullWidth value={draft.senderEmail} onChange={(value) => onChange({ ...draft, senderEmail: value })}>
      <Label>发件邮箱</Label>
      <Input type="email" autoComplete="email" />
    </TextField>
    <TextField fullWidth value={draft.senderName} onChange={(value) => onChange({ ...draft, senderName: value })}>
      <Label>发件名称</Label>
      <Input maxLength={80} />
    </TextField>
    <TextField fullWidth value={draft.credential} onChange={(value) => onChange({ ...draft, credential: value })}>
      <Label>{preset?.credential_label ?? '授权码或 API Key'}{credentialConfigured ? '（可留空复用）' : ''}</Label>
      <Input type="password" autoComplete="new-password" placeholder={credentialConfigured ? '留空复用已配置凭据' : '保存后不会回显'} />
    </TextField>
    {usesSes && <>
      <TextField fullWidth value={draft.region} onChange={(value) => onChange({ ...draft, region: value })}>
        <Label>Amazon SES Region</Label>
        <Input placeholder="例如：ap-northeast-1" />
      </TextField>
      <TextField fullWidth value={draft.smtpUsername} onChange={(value) => onChange({ ...draft, smtpUsername: value })}>
        <Label>SES SMTP 用户名</Label>
        <Input autoComplete="off" />
      </TextField>
    </>}
  </>
}
