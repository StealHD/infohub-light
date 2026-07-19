import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { AgentDelegation, AgentDelegationAccess } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import {
  Button,
  Card,
  Chip,
  Form,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  TextField,
} from '../../design-system'
import { OpenClawCredentialVault } from '../openclaw/openclawCredentialVault'
import { validateGatewayUrl } from '../openclaw/openclawGateway'
import { readSavedGatewayUrl, saveGatewayUrl } from '../openclaw/useOpenClawChat'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'

const TOKEN_REFERENCE = '${INTELISCOPE_MCP_TOKEN}'
export const READ_TOOL_FILTER = [
  'get_my_feed',
  'get_item',
  'list_subscriptions',
  'source_health',
  'list_jobs',
  'get_job',
  'get_source_setup_guide',
  'list_available_sources',
  'diagnose_source',
  'diagnose_job',
] as const
export const SUBSCRIPTION_WRITE_TOOL_FILTER = [
  'get_my_feed',
  'get_item',
  'list_subscriptions',
  'source_health',
  'list_jobs',
  'get_job',
  'get_source_setup_guide',
  'list_available_sources',
  'prepare_create_subscription',
  'prepare_update_subscription',
  'prepare_delete_subscription',
  'apply_subscription_change',
  'diagnose_source',
  'diagnose_job',
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

function dateTime(value: string) {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(parsed)
}

function statusLabel(connection: AgentDelegation) {
  if (connection.status === 'active') return { label: '有效', color: 'success' as const }
  if (connection.status === 'expired') return { label: '已过期', color: 'warning' as const }
  return { label: '已吊销', color: 'default' as const }
}

function accessLabel(access: AgentDelegationAccess) {
  return access === 'subscriptions_write' ? '可管理订阅' : '只读'
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

function OpenClawBrowserSettings({ userId, enabled, defaultUrl, targetVersion }: {
  userId: string
  enabled: boolean
  defaultUrl: string
  targetVersion: string
}) {
  const [url, setUrl] = useState(() => readSavedGatewayUrl(userId, defaultUrl))
  const [paired, setPaired] = useState<boolean | null>(null)
  const [notice, setNotice] = useState('')
  const vault = useMemo(() => new OpenClawCredentialVault(), [])

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
      setNotice('Gateway 地址已保存在当前浏览器。')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Gateway 地址无效。')
    }
  }

  async function forget() {
    try {
      await vault.forget(userId, validateGatewayUrl(url))
      setPaired(false)
      setNotice('已删除此用户在当前浏览器中的 OpenClaw 配对。请按 OpenClaw 设备列表指引吊销服务端设备。')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '无法删除当前浏览器配对。')
    }
  }

  return <AdminSection
    title="OpenClaw 对话连接"
    description={`浏览器直连你的 OpenClaw Gateway；目标版本 ${targetVersion}。Gateway token 不会发送到 Inteliscope 服务器。`}
  >
    {!enabled && <HeroNotice title="管理员尚未启用站内 OpenClaw 对话；信息流仍提供复制交接模式。" status="warning" role="status" />}
    <div className="mt-3 grid gap-3 min-[720px]:grid-cols-[minmax(0,1fr)_auto] min-[720px]:items-end">
      <TextField fullWidth value={url} onChange={setUrl}>
        <Label>OpenClaw Gateway URL</Label>
        <Input aria-label="OpenClaw Gateway URL" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      </TextField>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="ghost" onPress={saveUrl}>保存地址</Button>
        <Button size="sm" variant="danger" isDisabled={!paired} onPress={() => void forget()}>忘记此浏览器</Button>
      </div>
    </div>
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <Chip size="sm" color={paired ? 'success' : 'default'} variant="soft"><Chip.Label>{paired === null ? '正在检查配对' : paired ? '此浏览器已配对' : '此浏览器未配对'}</Chip.Label></Chip>
      {enabled && <a className="type-control text-accent" href="/feed">打开信息流对话面板</a>}
    </div>
    {notice && <p className="type-body mt-3 text-muted" role="status">{notice}</p>}
    <p className="type-meta mt-2 text-muted">忘记后可运行 <code>openclaw devices list</code>，找到 Inteliscope 浏览器设备并在 OpenClaw 中吊销，避免服务端仍保留旧设备授权。</p>
    <p className="type-meta mt-3 text-muted">本地只允许 ws://127.0.0.1 或 ws://localhost；远程 Gateway 必须使用 wss://。首次 token 只在对话面板输入。</p>
  </AdminSection>
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
  const [createPending, setCreatePending] = useState(false)
  const [oneTimeCredential, setOneTimeCredential] = useState<{ token: string; access: AgentDelegationAccess } | null>(null)
  const [renameTarget, setRenameTarget] = useState<AgentDelegation | null>(null)
  const [renameName, setRenameName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<AgentDelegation | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const readConfiguration = useMemo(() => agentConfiguration(query.data?.mcp_url || '<MCP_URL>', 'read'), [query.data?.mcp_url])
  const writeConfiguration = useMemo(() => agentConfiguration(query.data?.mcp_url || '<MCP_URL>', 'subscriptions_write'), [query.data?.mcp_url])
  const oneTimeConfiguration = oneTimeCredential?.access === 'subscriptions_write' ? writeConfiguration : readConfiguration
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.agentDelegations(user.id) })

  function openCreateDialog() {
    setCreateName('')
    setCreateAccess('read')
    setCreateOpen(true)
  }

  async function createConnection() {
    if (!createName.trim()) return
    setCreatePending(true)
    try {
      const result = await api.createAgentDelegation(createName.trim(), createAccess)
      setCreateOpen(false)
      setCreateName('')
      setCreateAccess('read')
      setOneTimeCredential({ token: result.token, access: result.connection.access ?? createAccess })
      setError('')
      refresh()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : '连接创建失败。')
    } finally {
      setCreatePending(false)
    }
  }

  const rename = useMutation({
    mutationFn: () => api.renameAgentDelegation(renameTarget!.id, renameName.trim()),
    onSuccess: () => { setRenameTarget(null); setRenameName(''); setNotice('连接名称已更新。'); setError(''); refresh() },
    onError: (caught) => setError(caught instanceof ApiError ? caught.message : '重命名失败。'),
  })
  const revoke = useMutation({
    mutationFn: () => api.revokeAgentDelegation(revokeTarget!.id),
    onSuccess: () => { setRevokeTarget(null); setNotice('连接已永久吊销。'); setError(''); refresh() },
    onError: (caught) => setError(caught instanceof ApiError ? caught.message : '吊销失败。'),
  })

  async function copy(value: string, message: string) {
    try { await navigator.clipboard.writeText(value); setNotice(message); setError('') }
    catch { setError('无法写入剪贴板，请手动复制。') }
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

  return <div className="h-full overflow-y-auto">
    <PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
      <AdminPageHeader description="管理 OpenClaw 对当前账户的数据权限，以及浏览器到本地 Gateway 的对话连接。" actions={<>
        <Button size="sm" variant="ghost" isIconOnly aria-label="刷新最近使用时间" onPress={() => void query.refetch()}><Icons.RefreshCw size={16} /></Button>
        <Button size="sm" isDisabled={creationDisabled} onPress={openCreateDialog}><Icons.Bot size={16} />创建连接</Button>
      </>} />
      {notice && <HeroNotice title={notice} status="success" role="status" />}
      {error && <HeroNotice title={error} />}
      {!query.data.enabled && <HeroNotice title="管理员尚未启用 Remote MCP。" status="warning" role="status" />}
      {limitReached && <HeroNotice title={`已达到 ${query.data.max_active} 个有效连接上限。`} status="accent" role="status" />}

      <AdminSection title="Inteliscope 数据连接" description="Remote MCP 让 OpenClaw 访问当前账户的数据。Inteliscope 服务器不运行 Agent 或模型；“最近使用”也不能代表 OpenClaw 在线。"><code className="type-body block overflow-wrap-anywhere rounded-lg bg-default p-3">{query.data.mcp_url || '功能尚未启用'}</code></AdminSection>

      <AdminSection title="我的连接" description={`${activeCount}/${query.data.max_active} 个有效连接`}>
        <div className="grid gap-3">
        {!query.data.connections.length && <Card variant="transparent" className="p-6 text-center"><Card.Description>还没有助手连接。</Card.Description></Card>}
        {query.data.connections.map((connection) => {
          const status = statusLabel(connection)
          return <Card key={connection.id} variant="secondary" className="p-4">
            <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center">
              <div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><Card.Title className="truncate">{connection.name}</Card.Title><Chip size="sm" color={status.color} variant="soft"><Chip.Label>{status.label}</Chip.Label></Chip><Chip size="sm" variant="soft"><Chip.Label>{accessLabel(connection.access)}</Chip.Label></Chip></div><Card.Description className="mt-1">{connection.last_used_at ? `最近使用 ${dateTime(connection.last_used_at)}` : '从未使用'} · 到期 {dateTime(connection.expires_at)} · {connection.token_prefix}…</Card.Description></div>
              <div className="flex flex-wrap gap-2"><Button size="sm" variant="ghost" aria-label={`复制 ${connection.name} 配置`} onPress={() => void copy(agentConfiguration(query.data.mcp_url, connection.access), `${connection.name} 配置已复制。`)}><Icons.Copy size={15} />复制配置</Button><Button size="sm" variant="ghost" aria-label={`重命名 ${connection.name}`} onPress={() => { setRenameTarget(connection); setRenameName(connection.name) }}>重命名</Button><Button size="sm" variant="danger" isDisabled={connection.status !== 'active'} aria-label={`吊销 ${connection.name}`} onPress={() => setRevokeTarget(connection)}>吊销</Button></div>
            </div>
          </Card>
        })}
        </div>
        <p className="type-meta mt-3 text-muted">可管理订阅不包括密钥、共享来源、任务、Feed 条目状态或刷新操作。</p>
      </AdminSection>

      <AdminSection title="OpenClaw MCP 配置" description="MCP token 保存在本机 ~/.openclaw/.env 并设置 0600 权限；它与 Gateway token 完全不同，也不要配置 OAuth。">
        <div className="grid gap-3 min-[900px]:grid-cols-2">
          <Card variant="secondary" className="p-4"><div className="flex items-center justify-between gap-2"><Card.Title>只读 · 10 个工具</Card.Title><Button size="sm" variant="ghost" onPress={() => void copy(readConfiguration, '只读配置已复制。')}><Icons.Copy size={15} />复制</Button></div><pre aria-label="OpenClaw 配置命令" tabIndex={0} className="type-meta mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{readConfiguration}</pre></Card>
          <Card variant="secondary" className="p-4"><div className="flex items-center justify-between gap-2"><Card.Title>订阅管理 · 14 个工具</Card.Title><Button size="sm" variant="ghost" isDisabled={!query.data.subscription_writes_enabled} onPress={() => void copy(writeConfiguration, '订阅管理配置已复制。')}><Icons.Copy size={15} />复制</Button></div><Card.Description className="mt-1">{query.data.subscription_writes_enabled ? '变更仍需 prepare、准确确认和 apply。' : '生产订阅写入当前关闭。'}</Card.Description><pre aria-label="订阅管理 OpenClaw 配置命令" tabIndex={0} className="type-meta mt-3 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{writeConfiguration}</pre></Card>
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
          {user.role !== 'viewer' && !query.data.subscription_writes_enabled && <p className="type-body text-muted">管理员尚未启用订阅管理连接；你仍可创建只读连接。</p>}
          <p className="type-body text-muted">只读连接可读取并诊断信息流、订阅、来源健康和任务，也可查看来源配置指导。可管理订阅连接还可准备并确认私有来源和订阅变更，但不能管理密钥、共享来源、任务、Feed 条目状态或刷新操作。</p>
        </Form>
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(oneTimeCredential)} onOpenChange={() => undefined}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开一次性令牌</Modal.Trigger>
      <DialogFrame title="保存一次性令牌" dismissable={false} testId="one-time-token-backdrop" footer={<Button onPress={() => { setOneTimeCredential(null); setNotice('一次性令牌已从页面清除。') }}>我已保存</Button>}>
        <HeroNotice title="关闭后无法恢复。" status="warning" role="status">请先保存到本机环境文件，再明确确认。</HeroNotice>
        <div className="mt-4 flex flex-col gap-2 min-[640px]:flex-row"><code className="min-w-0 flex-1 overflow-wrap-anywhere rounded-lg bg-default p-3">{oneTimeCredential?.token}</code><Button variant="ghost" onPress={() => oneTimeCredential && void copy(oneTimeCredential.token, '令牌已复制。')}><Icons.Copy size={15} />复制令牌</Button></div>
        <pre aria-label="本地令牌环境命令" className="type-meta mt-4 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{'INTELISCOPE_MCP_TOKEN=<一次性令牌>\nchmod 0600 ~/.openclaw/.env'}</pre>
        <pre aria-label="OpenClaw 配置命令" className="type-meta mt-3 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{oneTimeConfiguration}</pre>
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(renameTarget)} onOpenChange={(open) => !open && !rename.isPending && setRenameTarget(null)}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开重命名连接</Modal.Trigger>
      <DialogFrame title="重命名助手连接" footer={<><Button variant="ghost" onPress={() => setRenameTarget(null)}>取消</Button><Button isDisabled={!renameName.trim() || rename.isPending} onPress={() => rename.mutate()}>保存名称</Button></>}>
        <TextField autoFocus fullWidth isRequired value={renameName} onChange={setRenameName}><Label>连接名称</Label><Input maxLength={80} /></TextField>
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(revokeTarget)} onOpenChange={(open) => !open && !revoke.isPending && setRevokeTarget(null)}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开吊销连接</Modal.Trigger>
      <DialogFrame title="吊销助手连接" footer={<><Button variant="ghost" onPress={() => setRevokeTarget(null)}>取消</Button><Button variant="danger" isDisabled={revoke.isPending} onPress={() => revoke.mutate()}>确认吊销</Button></>}>
        <p className="type-body text-muted">吊销后无法恢复，OpenClaw 的下一次请求会立即失败。需要恢复时请创建新连接。</p>
      </DialogFrame>
    </Modal>
  </div>
}
