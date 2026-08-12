import { useRef, useState, type FormEvent } from 'react'
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
import { StatusBadge, type StatusBadgeTone } from '../../components/settings'
import {
  actionToast,
  Button,
  Description,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  Popover,
  Separator,
  Table,
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

function serviceStatusTone(service: NotificationService): StatusBadgeTone {
  if (service.available && service.enabled) return 'success'
  if (service.last_test_status === 'failed' || !service.configured) return 'danger'
  if (!service.enabled || service.last_test_status !== 'sent') return 'warning'
  return 'neutral'
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
  senderName: 'Inscope',
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

function NotificationServiceActions({
  service,
  busy,
  admin,
  onTestAndEnable,
  onResume,
  onPause,
  onEdit,
  onArchive,
}: {
  service: NotificationService
  busy: boolean
  admin: boolean
  onTestAndEnable: (service: NotificationService) => void
  onResume: (service: NotificationService) => void
  onPause: (service: NotificationService) => void
  onEdit: (service: NotificationService) => void
  onArchive: (service: NotificationService, trigger: HTMLButtonElement | null) => void
}) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const canManageShared = admin && !service.legacy_private
  const canManageLegacy = service.legacy_private && service.can_edit
  const canResumeWithoutTest = Boolean(!service.enabled && service.can_enable && service.transport_ready)
  const canManage = canManageShared || canManageLegacy
  const hasPrimaryAction = Boolean(
    (canManageShared && !service.available && !canResumeWithoutTest)
    || canResumeWithoutTest
    || service.enabled
    || canManageShared,
  )

  if (!canManage) return null

  function choose(action: () => void) {
    setOpen(false)
    action()
  }

  return <Popover isOpen={open} onOpenChange={setOpen}>
    <Popover.Trigger<'button'>
      ref={triggerRef}
      aria-label={`更多操作：${service.name}`}
      className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11"
      render={(triggerProps) => <button {...triggerProps} type="button" disabled={busy} />}
    ><Icons.MoreHorizontal size={17} aria-hidden="true" /></Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-44 p-0">
      <Popover.Dialog aria-label={`${service.name} 通知服务操作`} className="grid gap-0.5 p-2">
        {canManageShared && !service.available && !canResumeWithoutTest && <Button
          variant="ghost"
          className="w-full justify-start"
          isDisabled={!service.can_validate || busy}
          onPress={() => choose(() => onTestAndEnable(service))}
        ><Icons.Send size={15} aria-hidden="true" />{service.enabled ? '测试并恢复' : '测试并启用'}</Button>}
        {canResumeWithoutTest && <Button
          variant="ghost"
          className="w-full justify-start"
          isDisabled={busy}
          onPress={() => choose(() => onResume(service))}
        ><Icons.Play size={15} aria-hidden="true" />启用</Button>}
        {service.enabled && <Button
          variant="ghost"
          className="w-full justify-start"
          isDisabled={busy}
          onPress={() => choose(() => onPause(service))}
        ><Icons.Pause size={15} aria-hidden="true" />暂停</Button>}
        {canManageShared && <Button
          variant="ghost"
          className="w-full justify-start"
          isDisabled={busy}
          onPress={() => choose(() => onEdit(service))}
        ><Icons.Pencil size={15} aria-hidden="true" />编辑</Button>}
        {hasPrimaryAction && <Separator className="my-1" />}
        <Button
          variant="ghost"
          className="w-full justify-start text-danger"
          isDisabled={busy}
          onPress={() => choose(() => onArchive(service, triggerRef.current))}
        ><Icons.Archive size={15} aria-hidden="true" />归档</Button>
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
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
  const [createOpen, setCreateOpen] = useState(false)
  const [editingService, setEditingService] = useState<string | null>(null)
  const [editName, setEditName] = useState('')
  const [editDestination, setEditDestination] = useState('')
  const [editWebhookProvider, setEditWebhookProvider] = useState<WebhookProvider>('generic_event')
  const [editSigningSecret, setEditSigningSecret] = useState('')
  const [editBotToken, setEditBotToken] = useState('')
  const [editEmailDraft, setEditEmailDraft] = useState<EmailDraft>(emptyEmailDraft)
  const [editReplaceEmailCredential, setEditReplaceEmailCredential] = useState(false)
  const [archiveTarget, setArchiveTarget] = useState<NotificationService | null>(null)
  const archiveTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [requestError, setRequestError] = useState('')

  const admin = Boolean(services.data?.can_manage)
  const emailCredential = services.data?.channel_credentials.email
  const telegramCredential = services.data?.channel_credentials.telegram

  function currentEmailDraft(): EmailDraft {
    return {
      provider: emailCredential?.provider ?? 'qq',
      senderEmail: '',
      senderName: emailCredential?.sender_name || 'Inscope',
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
      setCreateOpen(false)
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

  function closeArchiveDialog() {
    if (busyService === archiveTarget?.id) return
    setArchiveTarget(null)
    window.requestAnimationFrame(() => archiveTriggerRef.current?.focus())
  }

  function requestArchive(service: NotificationService, trigger: HTMLButtonElement | null) {
    if (busyService) return
    archiveTriggerRef.current = trigger
    setRequestError('')
    setArchiveTarget(service)
  }

  async function archive() {
    const service = archiveTarget
    if (!service) return
    setBusyService(service.id)
    setRequestError('')
    try {
      if (service.legacy_private) {
        await api.archiveNotificationTarget(service.id)
      } else {
        await api.archiveNotificationService(service.id)
      }
      setArchiveTarget(null)
      await refresh()
      actionToast.success('通知服务已归档')
      window.requestAnimationFrame(() => archiveTriggerRef.current?.focus())
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
  const editingTarget = services.data.services.find((service) => service.id === editingService && admin && !service.legacy_private) ?? null

  return <div className="grid min-w-0 gap-4">
    <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h3 className="type-title">通知服务</h3>
        <Description>
          管理员在这里一次性配置接收地址、共享凭据并完成测试；个人通知和系统告警只选择已配置服务。
        </Description>
      </div>
      {admin && <Button size="sm" onPress={() => { setRequestError(''); setCreateOpen(true) }}><Icons.Plus size={15} aria-hidden="true" />新增通知服务</Button>}
    </div>

    {services.data.services.length === 0
      ? <HeroNotice title="还没有通知服务" status="default" role="status">管理员创建并测试一个服务后，个人通知和系统告警就能直接选择。</HeroNotice>
      : <Table className="overflow-hidden rounded-[var(--inteliscope-radius-card)] border border-separator bg-surface-secondary shadow-sm" variant="secondary">
        <Table.ScrollContainer className="max-w-full overflow-hidden">
          <Table.Content aria-label="通知服务列表" className="w-full table-fixed">
            <Table.Header className="bg-default/55">
              <Table.Column id="service" isRowHeader className="h-11 px-3 type-meta text-muted min-[640px]:px-4">服务</Table.Column>
              <Table.Column id="channel" className="hidden h-11 w-24 px-3 type-meta text-muted min-[640px]:table-cell">渠道</Table.Column>
              <Table.Column id="status" className="h-11 w-20 px-2 type-meta text-muted min-[640px]:w-24">状态</Table.Column>
              <Table.Column id="usage" className="hidden h-11 w-44 px-3 type-meta text-muted min-[640px]:table-cell">使用情况</Table.Column>
              <Table.Column id="actions" className="h-11 w-12 px-2 text-right type-meta text-muted">操作</Table.Column>
            </Table.Header>
            <Table.Body>{services.data.services.map((service) => {
              const usageCount = service.usage.user_binding_count + service.usage.alert_binding_count
              const busy = busyService === service.id
              const scope = service.legacy_private ? '历史私人服务' : '工作区共享'
              const usage = usageCount > 0 ? `${usageCount} 个业务正在使用` : '尚未被业务选择'
              return <Table.Row key={service.id} id={service.id} className="border-b border-separator bg-surface-secondary transition-colors last:border-b-0 hover:bg-default/35">
                <Table.Cell className="px-3 py-3 align-top min-[640px]:px-4">
                  <p className="type-control truncate text-foreground">{service.name}</p>
                  <p className="type-meta mt-1 text-muted">{scope}<span className="min-[640px]:hidden"> · {channelLabels[service.channel]} · generation {service.config_generation} · {usage}</span></p>
                  {!service.available && <p className="type-meta mt-1 text-warning">{serviceUnavailableReason(service)}</p>}
                </Table.Cell>
                <Table.Cell className="hidden px-3 py-3 align-top min-[640px]:table-cell"><p className="type-meta text-muted">{channelLabels[service.channel]}</p></Table.Cell>
                <Table.Cell className="px-2 py-3 align-top"><StatusBadge tone={serviceStatusTone(service)}>{serviceStatus(service)}</StatusBadge></Table.Cell>
                <Table.Cell className="hidden px-3 py-3 align-top min-[640px]:table-cell"><p className="type-meta text-muted">generation {service.config_generation} · {usage}</p></Table.Cell>
                <Table.Cell className="px-2 py-2 text-right align-top"><NotificationServiceActions service={service} busy={busy} admin={admin} onTestAndEnable={(target) => void testAndEnable(target)} onResume={(target) => void resume(target)} onPause={(target) => void pause(target)} onEdit={beginEdit} onArchive={requestArchive} /></Table.Cell>
              </Table.Row>
            })}</Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>}

    {admin && <Modal isOpen={createOpen} onOpenChange={(open) => !creating && setCreateOpen(open)}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开新增通知服务</Modal.Trigger>
      <Modal.Backdrop isDismissable={!creating} isKeyboardDismissDisabled={creating}>
        <Modal.Container size="lg">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>新增通知服务</Modal.Heading></Modal.Header>
            <Modal.Body>
              <form
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

      {requestError && <div className="min-[768px]:col-span-2"><HeroNotice title={requestError} /></div>}

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
              </form>
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>}
    <Modal isOpen={Boolean(editingTarget)} onOpenChange={(open) => {
      if (!open && busyService !== editingTarget?.id) setEditingService(null)
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开编辑通知服务</Modal.Trigger>
      <Modal.Backdrop isDismissable={busyService !== editingTarget?.id} isKeyboardDismissDisabled={busyService === editingTarget?.id}>
        <Modal.Container size="lg">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>编辑通知服务</Modal.Heading></Modal.Header>
            <Modal.Body>{editingTarget && <form id="notification-service-edit-form" className="grid gap-3 min-[640px]:grid-cols-2" noValidate onSubmit={(event) => { event.preventDefault(); void saveAndTest(editingTarget) }}>
              <TextField fullWidth value={editName} onChange={setEditName}>
                <Label>服务名称</Label>
                <Input maxLength={80} />
              </TextField>
              <TextField fullWidth value={editDestination} onChange={setEditDestination}>
                <Label>重新填写{destinationLabel(editingTarget.channel)}</Label>
                <Input type={editingTarget.channel === 'email' ? 'email' : 'password'} autoComplete="off" placeholder="留空保持当前值；保存后不会回显" />
              </TextField>
              {editingTarget.channel === 'telegram' && <TextField fullWidth value={editBotToken} onChange={setEditBotToken}>
                <Label>更换共享 Bot Token（可选）</Label>
                <Input type="password" autoComplete="new-password" placeholder="留空复用当前 Token" />
              </TextField>}
              {editingTarget.channel === 'webhook' && <TextField fullWidth value={editSigningSecret} onChange={setEditSigningSecret}>
                <Label>更换签名密钥（可选）</Label>
                <Input type="password" autoComplete="new-password" placeholder="留空保持当前值" />
              </TextField>}
              {editingTarget.channel === 'webhook' && <label className="grid gap-1">
                <span className="type-control">Webhook 类型</span>
                <select className="min-h-10 rounded-control border border-separator bg-surface px-3" value={editWebhookProvider} onChange={(event) => setEditWebhookProvider(event.target.value as WebhookProvider)}>
                  {services.data.webhook_provider_options.map((option) => <option key={option.provider} value={option.provider}>{option.label}</option>)}
                </select>
              </label>}
              {editingTarget.channel === 'email' && emailCredential?.configured && !editReplaceEmailCredential && <div className="grid gap-2 rounded-control border border-separator bg-surface-secondary p-3 min-[640px]:col-span-2">
                <Description>当前共享邮件凭据保持不变，测试会直接复用。</Description>
                <Button type="button" size="sm" variant="ghost" onPress={() => setEditReplaceEmailCredential(true)}>更换共享邮件凭据</Button>
              </div>}
              {editingTarget.channel === 'email' && (!emailCredential?.configured || editReplaceEmailCredential) && <EmailCredentialFields draft={editEmailDraft} onChange={setEditEmailDraft} providers={services.data.channel_credentials.email.providers} credentialConfigured={false} />}
              {requestError && <div className="min-[640px]:col-span-2"><HeroNotice title={requestError} /></div>}
            </form>}</Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={busyService === editingTarget?.id} onPress={() => setEditingService(null)}>取消</Button>
              <Button type="submit" form="notification-service-edit-form" isDisabled={busyService === editingTarget?.id}>{busyService === editingTarget?.id ? '处理中…' : '保存并测试'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
    <Modal isOpen={Boolean(archiveTarget)} onOpenChange={(open) => !open && closeArchiveDialog()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开归档通知服务确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={busyService !== archiveTarget?.id} isKeyboardDismissDisabled={busyService === archiveTarget?.id}>
        <Modal.Container size="sm">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>归档通知服务</Modal.Heading></Modal.Header>
            <Modal.Body><p className="type-body text-muted">归档“{archiveTarget?.name ?? ''}”后，个人通知和系统告警将无法继续选择它。若仍有业务正在使用，服务端会安全阻止归档。</p>{requestError && <HeroNotice title={requestError} />}</Modal.Body>
            <Modal.Footer>
              <Button variant="ghost" isDisabled={busyService === archiveTarget?.id} onPress={closeArchiveDialog}>取消</Button>
              <Button variant="danger" isDisabled={busyService === archiveTarget?.id} onPress={() => void archive()}>{busyService === archiveTarget?.id ? '归档中…' : '确认归档'}</Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
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
