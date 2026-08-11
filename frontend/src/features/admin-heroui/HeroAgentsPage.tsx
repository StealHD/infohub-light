import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type {
  AgentDelegation,
  AgentDelegationAccess,
  AgentDelegationDiagnosticsScope,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  actionToast,
  Button,
  Card,
  FieldError,
  Form,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  Popover,
  Separator,
  StatusIndicator,
  Switch,
  TextField,
  Tooltip,
  TooltipTriggerButton,
  topAnchoredTooltipProps,
} from '../../design-system'
import { OpenClawCredentialVault } from '../openclaw/openclawCredentialVault'
import { forgetOpenClawBrowser } from '../openclaw/openclawDevice'
import { validateGatewayUrl } from '../openclaw/openclawGateway'
import {
  clearOpenClawTranscript,
  readSavedGatewayUrl,
  saveGatewayUrl,
} from '../openclaw/useOpenClawChat'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'

const TOKEN_REFERENCE = '${INTELISCOPE_MCP_TOKEN}'
const oneTimeCopyIconClass = 'absolute right-2 top-2 z-10 size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11'
export const READ_TOOL_FILTER = [
  'get_my_feed',
  'get_item',
  'list_subscriptions',
  'source_health',
  'list_jobs',
  'get_job',
  'get_source_setup_guide',
  'search_bilibili_users',
  'resolve_source',
  'list_available_sources',
  'diagnose_source',
  'diagnose_job',
  'query_operation_logs',
] as const
export const SUBSCRIPTION_WRITE_TOOL_FILTER = [
  ...READ_TOOL_FILTER,
  'prepare_create_subscription',
  'prepare_update_subscription',
  'prepare_delete_subscription',
  'apply_subscription_change',
] as const

export function agentConfiguration(mcpUrl: string, access: AgentDelegationAccess = 'read'): string {
  const config = JSON.stringify({
    url: mcpUrl,
    transport: 'streamable-http',
    connectTimeout: 10,
    timeout: 30,
    supportsParallelToolCalls: true,
    headers: { Authorization: `Bearer ${TOKEN_REFERENCE}` },
    toolFilter: { include: access === 'subscriptions_write' ? SUBSCRIPTION_WRITE_TOOL_FILTER : READ_TOOL_FILTER },
  })
  return [`openclaw mcp set inteliscope '${config}'`, 'openclaw mcp doctor inteliscope --probe', 'openclaw mcp status --verbose', 'openclaw dashboard'].join('\n')
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\"'\"'")}'`
}

export function oneTimeTokenWriteCommand(token: string): string {
  const tokenLine = shellQuote(`INTELISCOPE_MCP_TOKEN=${token}`)
  return [
    'mkdir -p ~/.openclaw',
    'chmod 700 ~/.openclaw',
    `(umask 077; { test -f ~/.openclaw/.env && grep -v '^INTELISCOPE_MCP_TOKEN=' ~/.openclaw/.env || true; printf '%s\\n' ${tokenLine}; } > ~/.openclaw/.env.tmp && mv ~/.openclaw/.env.tmp ~/.openclaw/.env)`,
    'chmod 600 ~/.openclaw/.env',
  ].join(' && ')
}

function dateTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

function statusLabel(connection: AgentDelegation) {
  if (connection.status === 'active') return { label: '有效', tone: 'success' as const, icon: <Icons.CircleCheck size={13} aria-hidden="true" /> }
  if (connection.status === 'expired') return { label: '已过期', tone: 'warning' as const, icon: <Icons.ClockAlert size={13} aria-hidden="true" /> }
  return { label: '已吊销', tone: 'neutral' as const, icon: <Icons.CircleSlash2 size={13} aria-hidden="true" /> }
}

function accessLabel(access: AgentDelegationAccess) {
  return access === 'subscriptions_write' ? '可管理订阅' : '只读'
}

function OpenClawConfigurationCard({
  title,
  description,
  configuration,
  configurationLabel,
  copyDisabled = false,
  onCopy,
}: {
  title: string
  description: string
  configuration: string
  configurationLabel: string
  copyDisabled?: boolean
  onCopy: () => void
}) {
  return <Card variant="secondary" className="min-w-0 p-4">
    <div className="flex items-center justify-between gap-2">
      <Card.Title>{title}</Card.Title>
      <Button size="sm" variant="ghost" isDisabled={copyDisabled} onPress={onCopy}><Icons.Copy size={15} />复制</Button>
    </div>
    <Card.Description className="mt-1 min-h-10">{description}</Card.Description>
    <pre aria-label={configurationLabel} tabIndex={0} className="type-meta mt-3 max-h-56 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-default p-3 [overflow-wrap:anywhere]">{configuration}</pre>
  </Card>
}

function OneTimeCopyAction({
  label,
  disabled = false,
  onCopy,
}: {
  label: string
  disabled?: boolean
  onCopy: () => void
}) {
  return <Tooltip delay={250}>
    <TooltipTriggerButton
      aria-label={label}
      className={oneTimeCopyIconClass}
      disabled={disabled}
      onClick={onCopy}
    >
      <Icons.Copy size={15} aria-hidden="true" />
    </TooltipTriggerButton>
    <Tooltip.Content {...topAnchoredTooltipProps}>{label}</Tooltip.Content>
  </Tooltip>
}

function OneTimeSetupCommand({
  label,
  command,
  copyLabel,
  copyDisabled = false,
  onCopy,
  className = '',
}: {
  label: string
  command: string
  copyLabel: string
  copyDisabled?: boolean
  onCopy: () => void
  className?: string
}) {
  return <div className={`relative min-w-0 ${className}`}>
    <OneTimeCopyAction label={copyLabel} disabled={copyDisabled} onCopy={onCopy} />
    <pre
      aria-label={label}
      tabIndex={0}
      className="type-meta max-h-56 min-w-0 max-w-full overflow-x-hidden overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-default p-3 pr-14 [overflow-wrap:anywhere]"
    >
      {command}
    </pre>
  </div>
}

function DialogFrame({ title, children, footer, dismissable = true, testId }: {
  title: string
  children: React.ReactNode
  footer: React.ReactNode
  dismissable?: boolean
  testId?: string
}) {
  return <Modal.Backdrop isDismissable={dismissable} isKeyboardDismissDisabled={!dismissable} data-testid={testId}>
    <Modal.Container size="lg">
      <Modal.Dialog>
        <Modal.Header><Modal.Heading>{title}</Modal.Heading></Modal.Header>
        <Modal.Body>{children}</Modal.Body>
        <Modal.Footer>{footer}</Modal.Footer>
      </Modal.Dialog>
    </Modal.Container>
  </Modal.Backdrop>
}

type ConnectionAction = 'copy' | 'rename' | 'revoke' | 'delete'

function ConnectionCardActions({
  connection,
  open,
  onOpenChange,
  onAction,
}: {
  connection: AgentDelegation
  open: boolean
  onOpenChange: (open: boolean) => void
  onAction: (action: ConnectionAction, trigger: HTMLButtonElement | null) => void
}) {
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dangerAction = connection.status === 'active'
    ? { action: 'revoke' as const, label: '吊销连接', icon: Icons.Unplug }
    : connection.status === 'revoked'
      ? { action: 'delete' as const, label: '删除记录', icon: Icons.Trash2 }
      : null

  function choose(action: ConnectionAction) {
    onAction(action, triggerRef.current)
  }

  return <Popover isOpen={open} onOpenChange={onOpenChange}>
    <Popover.Trigger<'button'>
      ref={triggerRef}
      aria-label={`更多操作：${connection.name}`}
      className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11"
      render={(triggerProps) => <button {...triggerProps} type="button" />}
    ><Icons.MoreHorizontal size={17} aria-hidden="true" /></Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-44 p-0">
      <Popover.Dialog aria-label={`${connection.name} 连接操作`} className="grid gap-0.5 p-2">
        <Button variant="ghost" className="w-full justify-start" onPress={() => choose('copy')}>
          <Icons.Copy size={15} aria-hidden="true" />复制配置
        </Button>
        <Button variant="ghost" className="w-full justify-start" onPress={() => choose('rename')}>
          <Icons.Pencil size={15} aria-hidden="true" />重命名
        </Button>
        {dangerAction && <>
          <Separator className="my-1" />
          <Button
            variant="ghost"
            className="w-full justify-start text-danger"
            onPress={() => choose(dangerAction.action)}
          >
            <dangerAction.icon size={15} aria-hidden="true" />{dangerAction.label}
          </Button>
        </>}
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}

export function OpenClawBrowserSettings({
  userId,
  enabled,
  defaultUrl,
  targetVersion,
  vault: providedVault,
  forgetBrowser = forgetOpenClawBrowser,
}: {
  userId: string
  enabled: boolean
  defaultUrl: string
  targetVersion: string
  vault?: OpenClawCredentialVault
  forgetBrowser?: typeof forgetOpenClawBrowser
}) {
  const [url, setUrl] = useState(() => readSavedGatewayUrl(userId, defaultUrl))
  const [paired, setPaired] = useState<boolean | null>(null)
  const [urlError, setUrlError] = useState('')
  const [forgetError, setForgetError] = useState('')
  const [forgetOpen, setForgetOpen] = useState(false)
  const [forgetPending, setForgetPending] = useState(false)
  const saveAddressRef = useRef<HTMLButtonElement>(null)
  const forgetTriggerRef = useRef<HTMLButtonElement>(null)
  const defaultVault = useMemo(() => new OpenClawCredentialVault(), [])
  const vault = providedVault ?? defaultVault

  useEffect(() => {
    let cancelled = false
    void vault.load(userId, url).then((credential) => {
      if (!cancelled) setPaired(Boolean(credential))
    }).catch(() => {
      if (!cancelled) setPaired(false)
    })
    return () => { cancelled = true }
  }, [url, userId, vault])

  function saveUrl() {
    try {
      const normalized = validateGatewayUrl(url)
      saveGatewayUrl(userId, normalized)
      setUrl(normalized)
      setUrlError('')
      actionToast.success('Gateway 地址已保存')
    } catch (error) {
      setUrlError(error instanceof Error ? error.message : 'Gateway 地址无效。')
    }
  }

  function closeForgetDialog() {
    setForgetOpen(false)
    setForgetError('')
    window.requestAnimationFrame(() => {
      ;(forgetTriggerRef.current ?? saveAddressRef.current)?.focus()
    })
  }

  async function confirmForget() {
    setForgetPending(true)
    setForgetError('')
    try {
      const gatewayUrl = validateGatewayUrl(url)
      const result = await forgetBrowser({
        userId,
        gatewayUrl,
        vault,
        clearTranscripts: clearOpenClawTranscript,
      })
      setPaired(false)
      closeForgetDialog()
      actionToast.success(result === 'not-paired'
        ? '当前浏览器已无可删除的 OpenClaw 配对'
        : 'OpenClaw 服务端设备和当前浏览器配对已删除')
    } catch (error) {
      setForgetError(error instanceof Error ? error.message : '无法移除 OpenClaw 浏览器配对；本地凭据已保留。')
    } finally {
      setForgetPending(false)
    }
  }

  return <>
    <AdminSection
      title="OpenClaw 对话连接"
      description={`浏览器直连你的 OpenClaw Gateway；目标版本 ${targetVersion}。Gateway token 不会发送到 Inscope 服务器。`}
    >
      {!enabled && <HeroNotice title="管理员尚未启用站内 OpenClaw 对话；信息流仍提供复制交接模式。" status="warning" role="status" />}
      <div className="mt-3 grid gap-3 min-[720px]:grid-cols-[minmax(0,1fr)_auto] min-[720px]:items-end">
        <TextField fullWidth value={url} onChange={(value) => { setUrl(value); setUrlError('') }} isInvalid={Boolean(urlError)}>
          <Label>OpenClaw Gateway URL</Label>
          <Input aria-label="OpenClaw Gateway URL" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
          {urlError && <FieldError>{urlError}</FieldError>}
        </TextField>
        <div className="flex flex-wrap items-center gap-2">
          <Button ref={saveAddressRef} size="sm" variant="ghost" onPress={saveUrl}>保存地址</Button>
          {paired && <Tooltip delay={250}>
            <TooltipTriggerButton
              ref={forgetTriggerRef}
              aria-label="忘记此浏览器"
              disabled={forgetPending}
              className="size-8 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11"
              onClick={() => { setForgetError(''); setForgetOpen(true) }}
            ><Icons.Unplug size={16} aria-hidden="true" /></TooltipTriggerButton>
            <Tooltip.Content {...topAnchoredTooltipProps}>忘记此浏览器</Tooltip.Content>
          </Tooltip>}
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <StatusIndicator
          iconOnly
          label={paired === null ? '正在检查配对' : paired ? '此浏览器已配对' : '此浏览器未配对'}
          tone={paired === null ? 'accent' : paired ? 'success' : 'neutral'}
          icon={paired === null
            ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            : paired
              ? <Icons.CircleCheck size={13} aria-hidden="true" />
              : <Icons.CircleDashed size={13} aria-hidden="true" />}
        />
        {enabled && <a className="type-control text-accent" href="/feed">打开信息流对话面板</a>}
      </div>
      <p className="type-meta mt-2 text-muted">确认忘记后会先从 OpenClaw Gateway 移除当前设备；只有服务端成功或设备已不存在时，才会清除本地对话和配对凭据。</p>
      <p className="type-meta mt-3 text-muted">本地只允许 ws://127.0.0.1 或 ws://localhost；远程 Gateway 必须使用 wss://。首次 token 只在对话面板输入。</p>
    </AdminSection>
    <Modal isOpen={forgetOpen} onOpenChange={(open) => {
      if (forgetPending) return
      if (open) setForgetOpen(true)
      else closeForgetDialog()
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开移除浏览器配对</Modal.Trigger>
      <DialogFrame
        title="移除 OpenClaw 浏览器配对"
        dismissable={!forgetPending}
        footer={<>
          <Button variant="ghost" isDisabled={forgetPending} onPress={closeForgetDialog}>取消</Button>
          <Button variant="danger" isDisabled={forgetPending} onPress={() => void confirmForget()}>
            {forgetPending ? '正在移除…' : '确认移除并忘记'}
          </Button>
        </>}
      >
        <p className="type-body text-muted">这会让当前浏览器设备失去 OpenClaw 访问权限，并删除此用户在该 Gateway 下的本地对话与配对凭据。服务端拒绝时，本地恢复材料会保留。</p>
        {forgetError && <div className="mt-4"><HeroNotice title={forgetError} /></div>}
      </DialogFrame>
    </Modal>
  </>
}

export function HeroAgentsPage() {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: queryKeys.agentDelegations(user.id),
    queryFn: ({ signal }) => api.agentDelegations(signal),
    refetchOnWindowFocus: true,
    refetchInterval: false,
  })
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState('')
  const [createAccess, setCreateAccess] = useState<AgentDelegationAccess>('read')
  const [createDiagnosticsScope, setCreateDiagnosticsScope] = useState<AgentDelegationDiagnosticsScope>('self')
  const [createPending, setCreatePending] = useState(false)
  const [oneTimeCredential, setOneTimeCredential] = useState<{ token: string; access: AgentDelegationAccess } | null>(null)
  const [renameTarget, setRenameTarget] = useState<AgentDelegation | null>(null)
  const [renameName, setRenameName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<AgentDelegation | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<AgentDelegation | null>(null)
  const [openConnectionMenuId, setOpenConnectionMenuId] = useState<string | null>(null)
  const connectionActionTriggerRef = useRef<HTMLButtonElement | null>(null)
  const [createError, setCreateError] = useState('')
  const [renameError, setRenameError] = useState('')
  const [revokeError, setRevokeError] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const readConfiguration = useMemo(() => agentConfiguration(query.data?.mcp_url || '<MCP_URL>', 'read'), [query.data?.mcp_url])
  const writeConfiguration = useMemo(() => agentConfiguration(query.data?.mcp_url || '<MCP_URL>', 'subscriptions_write'), [query.data?.mcp_url])
  const oneTimeConfiguration = oneTimeCredential?.access === 'subscriptions_write' ? writeConfiguration : readConfiguration
  const oneTimeTokenWrite = oneTimeCredential ? oneTimeTokenWriteCommand(oneTimeCredential.token) : ''
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.agentDelegations(user.id) })

  function restoreConnectionActionFocus() {
    const trigger = connectionActionTriggerRef.current
    window.requestAnimationFrame(() => trigger?.focus())
  }

  function closeRenameDialog() {
    setRenameTarget(null)
    setRenameName('')
    setRenameError('')
    restoreConnectionActionFocus()
  }

  function closeRevokeDialog() {
    setRevokeTarget(null)
    setRevokeError('')
    restoreConnectionActionFocus()
  }

  function closeDeleteDialog() {
    setDeleteTarget(null)
    setDeleteError('')
    restoreConnectionActionFocus()
  }

  function openCreateDialog() {
    setCreateName('')
    setCreateAccess('read')
    setCreateDiagnosticsScope('self')
    setCreateError('')
    setCreateOpen(true)
  }

  async function createConnection() {
    if (!createName.trim()) return
    setCreatePending(true)
    try {
      const result = await api.createAgentDelegation(
        createName.trim(),
        createAccess,
        createDiagnosticsScope,
      )
      setCreateOpen(false)
      setCreateName('')
      setCreateAccess('read')
      setCreateDiagnosticsScope('self')
      setOneTimeCredential({ token: result.token, access: result.connection.access ?? createAccess })
      setCreateError('')
      refresh()
    } catch (caught) {
      setCreateError(caught instanceof ApiError || caught instanceof Error ? caught.message : '连接创建失败。')
    } finally {
      setCreatePending(false)
    }
  }

  const rename = useMutation({
    mutationFn: () => api.renameAgentDelegation(renameTarget!.id, renameName.trim()),
    onSuccess: () => {
      closeRenameDialog()
      actionToast.success('连接名称已更新')
      refresh()
    },
    onError: (caught) => setRenameError(caught instanceof ApiError || caught instanceof Error ? caught.message : '重命名失败。'),
  })
  const revoke = useMutation({
    mutationFn: () => api.revokeAgentDelegation(revokeTarget!.id),
    onSuccess: () => {
      closeRevokeDialog()
      actionToast.success('连接已永久吊销')
      refresh()
    },
    onError: (caught) => setRevokeError(caught instanceof ApiError || caught instanceof Error ? caught.message : '吊销失败。'),
  })
  const deleteRecord = useMutation({
    mutationFn: () => api.deleteAgentDelegationRecord(deleteTarget!.id),
    onSuccess: () => {
      closeDeleteDialog()
      actionToast.success('已删除连接记录')
      refresh()
    },
    onError: (caught) => setDeleteError(caught instanceof ApiError || caught instanceof Error ? caught.message : '删除失败。'),
  })

  async function copy(value: string, message: string) {
    try {
      await navigator.clipboard.writeText(value)
      actionToast.success(message)
    } catch {
      actionToast.danger('复制失败', { description: '无法写入剪贴板，请手动复制。' })
    }
  }

  function chooseConnectionAction(
    connection: AgentDelegation,
    action: ConnectionAction,
    trigger: HTMLButtonElement | null,
  ) {
    connectionActionTriggerRef.current = trigger
    setOpenConnectionMenuId(null)
    if (action === 'copy') {
      void copy(
        agentConfiguration(query.data?.mcp_url || '<MCP_URL>', connection.access),
        `${connection.name} 配置已复制。`,
      ).finally(restoreConnectionActionFocus)
      return
    }
    if (action === 'rename') {
      setRenameError('')
      setRenameTarget(connection)
      setRenameName(connection.name)
      return
    }
    if (action === 'revoke' && connection.status === 'active') {
      setRevokeError('')
      setRevokeTarget(connection)
      return
    }
    if (action === 'delete' && connection.status === 'revoked') {
      setDeleteError('')
      setDeleteTarget(connection)
    }
  }

  if (query.isLoading) return <PageFrame width="admin" className="p-5"><LoadingState label="正在读取助手连接" rows={1} /></PageFrame>
  if (query.isError || !query.data) return <PageFrame width="admin" className="p-5"><HeroNotice title="连接列表读取失败。"><Button size="sm" variant="ghost" onPress={() => void query.refetch()}>重试</Button></HeroNotice></PageFrame>

  const activeCount = query.data.connections.filter((connection) => connection.status === 'active').length
  const limitReached = activeCount >= query.data.max_active
  const creationDisabled = !query.data.enabled || limitReached
  const chatSettings = query.data.openclaw_chat ?? {
    enabled: false,
    default_gateway_url: 'ws://127.0.0.1:18789',
    protocol_version: 4 as const,
    target_version: '2026.7.1',
  }

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
      <AdminPageHeader description="管理 OpenClaw 对当前账户的数据权限，以及浏览器到本地 Gateway 的对话连接。" actions={<>
        <Button size="sm" variant="ghost" isIconOnly aria-label="刷新最近使用时间" onPress={() => void query.refetch()}><Icons.RefreshCw size={16} /></Button>
        <Button size="sm" isDisabled={creationDisabled} onPress={openCreateDialog}><Icons.Bot size={16} />创建连接</Button>
      </>} />
      {!query.data.enabled && <HeroNotice title="管理员尚未启用 Remote MCP。" status="warning" role="status" />}
      {limitReached && <HeroNotice title={`已达到 ${query.data.max_active} 个有效连接上限。`} status="accent" role="status" />}

      <AdminSection title="Inscope 数据连接" description="Remote MCP 让 OpenClaw 访问当前账户的数据。Inscope 服务器不运行 Agent 或模型；“最近使用”也不能代表 OpenClaw 在线。"><code className="type-body block overflow-wrap-anywhere rounded-lg bg-default p-3">{query.data.mcp_url || '功能尚未启用'}</code></AdminSection>

      <AdminSection title="我的连接" description={`${activeCount}/${query.data.max_active} 个有效连接`}>
        <div className="grid gap-3">
        {!query.data.connections.length && <Card variant="transparent" className="p-6 text-center"><Card.Description>还没有助手连接。</Card.Description></Card>}
        {query.data.connections.map((connection) => {
          const status = statusLabel(connection)
          return <Card key={connection.id} variant="secondary" className="p-4">
            <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center">
              <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Card.Title className="truncate">{connection.name}</Card.Title><StatusIndicator iconOnly label={status.label} tone={status.tone} icon={status.icon} /><span className="type-meta inline-flex items-center gap-1 text-muted"><Icons.LockKeyhole size={12} aria-hidden="true" />{accessLabel(connection.access)}</span>{connection.diagnostics_scope === 'workspace' && <span className="type-meta text-muted">工作区诊断</span>}</div><Card.Description className="mt-1">{connection.last_used_at ? `最近使用 ${dateTime(connection.last_used_at)}` : '从未使用'} · 到期 {dateTime(connection.expires_at)} · {connection.token_prefix}…</Card.Description></div>
              <ConnectionCardActions
                connection={connection}
                open={openConnectionMenuId === connection.id}
                onOpenChange={(open) => setOpenConnectionMenuId(open ? connection.id : null)}
                onAction={(action, trigger) => chooseConnectionAction(connection, action, trigger)}
              />
            </div>
          </Card>
        })}
        </div>
        <p className="type-meta mt-3 text-muted">可管理订阅不包括密钥、共享来源、任务、Feed 条目状态或刷新操作。</p>
      </AdminSection>

      <AdminSection title="OpenClaw MCP 配置" description="MCP token 保存在本机 ~/.openclaw/.env 并设置 0600 权限；它与 Gateway token 完全不同，也不要配置 OAuth。">
        <div className="grid gap-3 min-[900px]:grid-cols-2">
          <OpenClawConfigurationCard
            title="只读 · 13 个工具"
            description="读取并诊断信息流、订阅、公开来源、来源健康和任务。"
            configuration={readConfiguration}
            configurationLabel="OpenClaw 配置命令"
            onCopy={() => void copy(readConfiguration, '只读配置已复制。')}
          />
          <OpenClawConfigurationCard
            title="订阅管理 · 17 个工具"
            description={query.data.subscription_writes_enabled ? '变更仍需 prepare、准确确认和 apply。' : '生产订阅写入当前关闭。'}
            configuration={writeConfiguration}
            configurationLabel="订阅管理 OpenClaw 配置命令"
            copyDisabled={!query.data.subscription_writes_enabled}
            onCopy={() => void copy(writeConfiguration, '订阅管理配置已复制。')}
          />
        </div>
      </AdminSection>
      <OpenClawBrowserSettings userId={user.id} enabled={chatSettings.enabled} defaultUrl={chatSettings.default_gateway_url} targetVersion={chatSettings.target_version} />
      <AdminSection title="故障排查"><ol className="type-body list-decimal space-y-2 pl-5 text-muted"><li>确认环境文件权限为 0600，并重新启动 OpenClaw。</li><li>运行 doctor 和 status；401 表示令牌无效、过期、已吊销或用户已禁用。</li><li>“最近使用”只表示服务收到过调用，不能判断本地 Agent 是否在线。</li></ol></AdminSection>
    </PageFrame>

    <Modal isOpen={createOpen} onOpenChange={(open) => !createPending && setCreateOpen(open)}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开创建连接</Modal.Trigger>
      <DialogFrame title="创建助手连接" footer={<><Button variant="ghost" isDisabled={createPending} onPress={() => setCreateOpen(false)}>取消</Button><Button isDisabled={!createName.trim() || createPending} onPress={() => void createConnection()}>{createPending ? '生成中…' : '生成一次性令牌'}</Button></>}>
        <Form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); void createConnection() }}>
          <TextField autoFocus fullWidth isRequired value={createName} onChange={setCreateName}><Label>连接名称</Label><Input maxLength={80} /><p className="type-meta text-muted">令牌有效 {query.data.token_ttl_days} 天，只会显示一次。</p></TextField>
          <HeroSelect
            label="访问权限"
            value={createAccess}
            onChange={(value) => setCreateAccess(value as AgentDelegationAccess)}
            options={[
              { id: 'read', label: '只读' },
              ...(user.role === 'viewer' ? [] : [{ id: 'subscriptions_write', label: '可管理订阅', isDisabled: !query.data.subscription_writes_enabled }]),
            ]}
          />
          {(user.role === 'owner' || user.role === 'admin') && <Switch
            isSelected={createDiagnosticsScope === 'workspace'}
            onChange={(selected) => setCreateDiagnosticsScope(selected ? 'workspace' : 'self')}
          >
            <Switch.Content>
              <Switch.Control><Switch.Thumb /></Switch.Control>
              允许读取工作区故障诊断
            </Switch.Content>
          </Switch>}
          {(user.role === 'owner' || user.role === 'admin') && <p className="type-meta text-muted">仅影响这次新建的令牌；旧令牌不会自动获得权限。工作区查询必须指定请求、任务、来源或订阅 ID，或者只查询 warning/error。</p>}
          {user.role !== 'viewer' && !query.data.subscription_writes_enabled && <p className="type-body text-muted">管理员尚未启用订阅管理连接；你仍可创建只读连接。</p>}
          <p className="type-body text-muted">只读连接可读取并诊断信息流、订阅、来源健康和任务，也可查看来源配置指导。可管理订阅连接还可准备并确认私有来源和订阅变更，但不能管理密钥、共享来源、任务、Feed 条目状态或刷新操作。</p>
          {createError && <HeroNotice title={createError} />}
        </Form>
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(oneTimeCredential)} onOpenChange={() => undefined}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开一次性令牌</Modal.Trigger>
      <DialogFrame title="保存一次性 MCP token" dismissable={false} testId="one-time-token-backdrop" footer={<Button onPress={() => { setOneTimeCredential(null); actionToast.success('一次性令牌已从页面清除') }}>我已保存</Button>}>
        <HeroNotice title="关闭后无法恢复。" status="warning" role="status">请先保存到本机环境文件，再明确确认。</HeroNotice>
        <div className="relative mt-4 min-w-0"><code className="block min-w-0 max-w-full truncate rounded-lg bg-default p-3 pr-14">{oneTimeCredential?.token}</code><OneTimeCopyAction label="复制令牌" onCopy={() => oneTimeCredential && void copy(oneTimeCredential.token, '令牌已复制。')} /></div>
        <p className="type-meta mt-4 text-muted">复制写入命令后，在本机终端粘贴运行；它只更新 Inteliscope 令牌并保留环境文件里的其他内容。</p>
        <OneTimeSetupCommand
          label="本地令牌环境命令"
          command={oneTimeTokenWrite}
          copyLabel="复制本地令牌写入命令"
          onCopy={() => oneTimeCredential && void copy(oneTimeTokenWrite, '写入命令已复制。')}
          className="mt-2"
        />
        <OneTimeSetupCommand
          label="OpenClaw 配置命令"
          command={oneTimeConfiguration}
          copyLabel="复制 OpenClaw 配置命令"
          onCopy={() => void copy(oneTimeConfiguration, 'OpenClaw 配置已复制。')}
          className="mt-3"
        />
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(renameTarget)} onOpenChange={(open) => !open && !rename.isPending && closeRenameDialog()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开重命名连接</Modal.Trigger>
      <DialogFrame title="重命名助手连接" dismissable={!rename.isPending} footer={<><Button variant="ghost" isDisabled={rename.isPending} onPress={closeRenameDialog}>取消</Button><Button isDisabled={!renameName.trim() || rename.isPending} onPress={() => rename.mutate()}>{rename.isPending ? '保存中…' : '保存名称'}</Button></>}>
        <TextField autoFocus fullWidth isRequired value={renameName} onChange={setRenameName}><Label>连接名称</Label><Input maxLength={80} /></TextField>
        {renameError && <div className="mt-4"><HeroNotice title={renameError} /></div>}
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(revokeTarget)} onOpenChange={(open) => !open && !revoke.isPending && closeRevokeDialog()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开吊销连接</Modal.Trigger>
      <DialogFrame title="吊销助手连接" dismissable={!revoke.isPending} footer={<><Button variant="ghost" isDisabled={revoke.isPending} onPress={closeRevokeDialog}>取消</Button><Button variant="danger" isDisabled={revoke.isPending} onPress={() => revoke.mutate()}>{revoke.isPending ? '正在吊销…' : '确认吊销'}</Button></>}>
        <p className="type-body text-muted">吊销后无法恢复，OpenClaw 的下一次请求会立即失败。需要恢复时请创建新连接。</p>
        {revokeError && <div className="mt-4"><HeroNotice title={revokeError} /></div>}
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(deleteTarget)} onOpenChange={(open) => !open && !deleteRecord.isPending && closeDeleteDialog()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开删除连接</Modal.Trigger>
      <DialogFrame
        title="删除已吊销连接"
        dismissable={!deleteRecord.isPending}
        footer={<><Button variant="ghost" isDisabled={deleteRecord.isPending} onPress={closeDeleteDialog}>取消</Button><Button variant="danger" isDisabled={deleteRecord.isPending} onPress={() => deleteRecord.mutate()}>{deleteRecord.isPending ? '正在删除…' : '确认删除'}</Button></>}
      >
        <p className="type-body text-muted">只会删除这一条已吊销连接记录，不会影响其他连接。删除后无法恢复。</p>
        {deleteError && <div className="mt-4"><HeroNotice title={deleteError} /></div>}
      </DialogFrame>
    </Modal>
  </div>
}
