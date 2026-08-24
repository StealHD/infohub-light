import { useMemo, useRef, useState } from 'react'
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
  Form,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  StatusIndicator,
  Switch,
  TextField,
} from '../../design-system'
import {
  agentConfiguration,
  oneTimeTokenWriteCommand,
} from '../openclaw/openclawAgentConfiguration'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'
import {
  ConnectionCardActions,
  DialogFrame,
  OneTimeCopyAction,
  OneTimeSetupCommand,
  OpenClawConfigurationCard,
  type ConnectionAction,
} from './HeroAgentDelegationViews'
import { OpenClawBrowserSettings } from './HeroAgentsPageBrowserSettings'
import { delegationAccessLabel, delegationDateTime, delegationStatus } from './HeroAgentDelegationPresentation'

export { OpenClawBrowserSettings } from './HeroAgentsPageBrowserSettings'

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
  const systemConfiguration = useMemo(() => agentConfiguration(query.data?.mcp_url || '<MCP_URL>', 'system_settings_write'), [query.data?.mcp_url])
  const oneTimeConfiguration = oneTimeCredential ? agentConfiguration(query.data?.mcp_url || '<MCP_URL>', oneTimeCredential.access) : readConfiguration
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
          const status = delegationStatus(connection)
          return <Card key={connection.id} variant="secondary" className="p-4">
            <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center">
              <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Card.Title className="truncate">{connection.name}</Card.Title><StatusIndicator iconOnly label={status.label} tone={status.tone} icon={status.icon} /><span className="type-meta inline-flex items-center gap-1 text-muted"><Icons.LockKeyhole size={12} aria-hidden="true" />{delegationAccessLabel(connection.access)}</span>{connection.diagnostics_scope === 'workspace' && <span className="type-meta text-muted">工作区诊断</span>}</div><Card.Description className="mt-1">{connection.last_used_at ? `最近使用 ${delegationDateTime(connection.last_used_at)}` : '从未使用'} · 到期 {delegationDateTime(connection.expires_at)} · {connection.token_prefix}…</Card.Description></div>
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
        <p className="type-meta mt-3 text-muted">写入连接彼此隔离；订阅管理与系统管理不会互相获得权限，也都不包括密钥。</p>
      </AdminSection>

      <AdminSection title="OpenClaw MCP 配置" description="MCP token 保存在本机 ~/.openclaw/.env 并设置 0600 权限；它与 Gateway token 完全不同，也不要配置 OAuth。">
        <div className="grid gap-3 min-[900px]:grid-cols-3">
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
          <OpenClawConfigurationCard
            title="系统管理 · 16 个工具"
            description={query.data.system_settings_writes_enabled ? '仅可修改安全白名单参数，仍需预演、准确确认和应用。' : '生产系统参数写入当前关闭。'}
            configuration={systemConfiguration}
            configurationLabel="系统管理 OpenClaw 配置命令"
            copyDisabled={!query.data.system_settings_writes_enabled || (user.role !== 'owner' && user.role !== 'admin')}
            onCopy={() => void copy(systemConfiguration, '系统管理配置已复制。')}
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
              ...(user.role === 'owner' || user.role === 'admin' ? [{ id: 'system_settings_write', label: '系统管理', isDisabled: !query.data.system_settings_writes_enabled }] : []),
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
          {(user.role === 'owner' || user.role === 'admin') && !query.data.system_settings_writes_enabled && <p className="type-body text-muted">管理员尚未启用系统管理连接。</p>}
          <p className="type-body text-muted">只读连接用于浏览和诊断；订阅管理用于来源与订阅提案；系统管理仅用于安全白名单参数。两类写权限相互独立，均不能管理密钥。</p>
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
