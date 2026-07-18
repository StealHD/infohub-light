import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { AgentDelegation } from '../../api/types'
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
import { AdminPageHeader, AdminSection, HeroNotice } from './HeroAdminControls'

const TOKEN_REFERENCE = '${INTELISCOPE_MCP_TOKEN}'
const TOOL_FILTER = ['get_my_feed', 'get_item', 'list_subscriptions', 'source_health', 'list_jobs', 'get_job']

function agentConfiguration(mcpUrl: string): string {
  const config = JSON.stringify({
    url: mcpUrl,
    transport: 'streamable-http',
    connectTimeout: 10,
    timeout: 30,
    supportsParallelToolCalls: true,
    headers: { Authorization: `Bearer ${TOKEN_REFERENCE}` },
    toolFilter: { include: TOOL_FILTER },
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
  const [createPending, setCreatePending] = useState(false)
  const [oneTimeToken, setOneTimeToken] = useState<string | null>(null)
  const [renameTarget, setRenameTarget] = useState<AgentDelegation | null>(null)
  const [renameName, setRenameName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<AgentDelegation | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const configuration = useMemo(() => agentConfiguration(query.data?.mcp_url || '<MCP_URL>'), [query.data?.mcp_url])
  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.agentDelegations(user.id) })

  async function createConnection() {
    if (!createName.trim()) return
    setCreatePending(true)
    try {
      const result = await api.createAgentDelegation(createName.trim())
      setCreateOpen(false)
      setCreateName('')
      setOneTimeToken(result.token)
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

  return <div className="h-full overflow-y-auto">
    <PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
      <AdminPageHeader description="让你自己电脑上的 OpenClaw 只读访问当前账户的数据。" actions={<>
        <Button size="sm" variant="ghost" isIconOnly aria-label="刷新最近使用时间" onPress={() => void query.refetch()}><Icons.RefreshCw size={16} /></Button>
        <Button size="sm" isDisabled={creationDisabled} onPress={() => setCreateOpen(true)}><Icons.Bot size={16} />创建连接</Button>
      </>} />
      {notice && <HeroNotice title={notice} status="success" role="status" />}
      {error && <HeroNotice title={error} />}
      {!query.data.enabled && <HeroNotice title="管理员尚未启用 Remote MCP。" status="warning" role="status" />}
      {limitReached && <HeroNotice title={`已达到 ${query.data.max_active} 个有效连接上限。`} status="accent" role="status" />}

      <AdminSection title="连接方式" description="Inteliscope 不连接本地 Gateway，也不会在服务器运行 Agent。“最近使用”不能代表在线。"><code className="type-body block overflow-wrap-anywhere rounded-lg bg-default p-3">{query.data.mcp_url || '功能尚未启用'}</code></AdminSection>

      <AdminSection title="我的连接" description={`${activeCount}/${query.data.max_active} 个有效连接`}>
        <div className="grid gap-3">
        {!query.data.connections.length && <Card variant="transparent" className="p-6 text-center"><Card.Description>还没有助手连接。</Card.Description></Card>}
        {query.data.connections.map((connection) => {
          const status = statusLabel(connection)
          return <Card key={connection.id} variant="secondary" className="p-4">
            <div className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center">
              <div className="min-w-0 flex-1"><div className="flex items-center gap-2"><Card.Title className="truncate">{connection.name}</Card.Title><Chip size="sm" color={status.color} variant="soft"><Chip.Label>{status.label}</Chip.Label></Chip></div><Card.Description className="mt-1">{connection.last_used_at ? `最近使用 ${dateTime(connection.last_used_at)}` : '从未使用'} · 到期 {dateTime(connection.expires_at)} · {connection.token_prefix}…</Card.Description></div>
              <div className="flex gap-2"><Button size="sm" variant="ghost" aria-label={`重命名 ${connection.name}`} onPress={() => { setRenameTarget(connection); setRenameName(connection.name) }}>重命名</Button><Button size="sm" variant="danger" isDisabled={connection.status !== 'active'} aria-label={`吊销 ${connection.name}`} onPress={() => setRevokeTarget(connection)}>吊销</Button></div>
            </div>
          </Card>
        })}
        </div>
      </AdminSection>

      <AdminSection title="OpenClaw 配置" description="令牌保存在本机 ~/.openclaw/.env 并设置 0600 权限，不要配置 OAuth。"><div className="flex justify-end"><Button size="sm" variant="ghost" onPress={() => void copy(configuration, '配置已复制。')}><Icons.Copy size={15} />复制配置</Button></div><pre aria-label="OpenClaw 配置命令" tabIndex={0} className="type-meta mt-3 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-4">{configuration}</pre></AdminSection>
      <AdminSection title="故障排查"><ol className="type-body list-decimal space-y-2 pl-5 text-muted"><li>确认环境文件权限为 0600，并重新启动 OpenClaw。</li><li>运行 doctor 和 status；401 表示令牌无效、过期、已吊销或用户已禁用。</li><li>“最近使用”只表示服务收到过调用，不能判断本地 Agent 是否在线。</li></ol></AdminSection>
    </PageFrame>

    <Modal isOpen={createOpen} onOpenChange={(open) => !createPending && setCreateOpen(open)}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开创建连接</Modal.Trigger>
      <DialogFrame title="创建助手连接" footer={<><Button variant="ghost" isDisabled={createPending} onPress={() => setCreateOpen(false)}>取消</Button><Button isDisabled={!createName.trim() || createPending} onPress={() => void createConnection()}>{createPending ? '生成中…' : '生成一次性令牌'}</Button></>}>
        <Form onSubmit={(event) => { event.preventDefault(); void createConnection() }}><TextField autoFocus fullWidth isRequired value={createName} onChange={setCreateName}><Label>连接名称</Label><Input maxLength={80} /><p className="type-meta text-muted">令牌有效 {query.data.token_ttl_days} 天，只会显示一次。</p></TextField></Form>
      </DialogFrame>
    </Modal>

    <Modal isOpen={Boolean(oneTimeToken)} onOpenChange={() => undefined}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开一次性令牌</Modal.Trigger>
      <DialogFrame title="保存一次性令牌" dismissable={false} testId="one-time-token-backdrop" footer={<Button onPress={() => { setOneTimeToken(null); setNotice('一次性令牌已从页面清除。') }}>我已保存</Button>}>
        <HeroNotice title="关闭后无法恢复。" status="warning" role="status">请先保存到本机环境文件，再明确确认。</HeroNotice>
        <div className="mt-4 flex flex-col gap-2 min-[640px]:flex-row"><code className="min-w-0 flex-1 overflow-wrap-anywhere rounded-lg bg-default p-3">{oneTimeToken}</code><Button variant="ghost" onPress={() => oneTimeToken && void copy(oneTimeToken, '令牌已复制。')}><Icons.Copy size={15} />复制令牌</Button></div>
        <pre aria-label="本地令牌环境命令" className="type-meta mt-4 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{'INTELISCOPE_MCP_TOKEN=<一次性令牌>\nchmod 0600 ~/.openclaw/.env'}</pre>
        <pre aria-label="OpenClaw 配置命令" className="type-meta mt-3 overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{configuration}</pre>
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
