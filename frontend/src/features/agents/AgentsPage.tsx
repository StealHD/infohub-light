import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { AgentDelegation, AgentDelegationAccess } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { ContentCopyRounded, DeleteOutlineRounded, RefreshRounded, SmartToyRounded } from '../../ui/icons'
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Tooltip,
  Typography,
  uiRadii,
} from '../../ui'

const TOKEN_REFERENCE = '${INTELISCOPE_MCP_TOKEN}'
const READ_TOOLS = [
  'get_my_feed',
  'get_item',
  'list_subscriptions',
  'source_health',
  'list_jobs',
  'get_job',
] as const

const WRITE_TOOLS = [
  ...READ_TOOLS,
  'get_source_setup_guide',
  'list_available_sources',
  'prepare_create_subscription',
  'prepare_update_subscription',
  'prepare_delete_subscription',
  'apply_subscription_change',
  'diagnose_source',
  'diagnose_job',
] as const

type OneTimeCredential = {
  token: string
  access: AgentDelegationAccess
}

function configurationFor(mcpUrl: string, access: AgentDelegationAccess): string {
  const tools = access === 'subscriptions_write' ? WRITE_TOOLS : READ_TOOLS
  const config = JSON.stringify({
    url: mcpUrl,
    transport: 'streamable-http',
    connectTimeout: 10,
    timeout: 30,
    supportsParallelToolCalls: true,
    headers: { Authorization: `Bearer ${TOKEN_REFERENCE}` },
    toolFilter: { include: tools },
  })
  return [
    `openclaw mcp set inteliscope '${config}'`,
    'openclaw mcp doctor inteliscope --probe',
    'openclaw mcp status --verbose',
    'openclaw dashboard',
  ].join('\n')
}

function dateTime(value: string): string {
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium', timeStyle: 'short',
  }).format(parsed)
}

function statusLabel(connection: AgentDelegation): { label: string; color: 'success' | 'default' | 'warning' } {
  if (connection.status === 'active') return { label: '有效', color: 'success' }
  if (connection.status === 'expired') return { label: '已过期', color: 'warning' }
  return { label: '已吊销', color: 'default' }
}

export function AgentsPage() {
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
  const [oneTimeCredential, setOneTimeCredential] = useState<OneTimeCredential | null>(null)
  const [renameTarget, setRenameTarget] = useState<AgentDelegation | null>(null)
  const [renameName, setRenameName] = useState('')
  const [revokeTarget, setRevokeTarget] = useState<AgentDelegation | null>(null)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const configuration = useMemo(
    () => configurationFor(query.data?.mcp_url || '<MCP_URL>', 'read'),
    [query.data?.mcp_url],
  )
  const oneTimeConfiguration = useMemo(
    () => configurationFor(
      query.data?.mcp_url || '<MCP_URL>',
      oneTimeCredential?.access || 'read',
    ),
    [oneTimeCredential?.access, query.data?.mcp_url],
  )

  const refresh = () => void queryClient.invalidateQueries({ queryKey: queryKeys.agentDelegations(user.id) })
  function openCreateDialog() {
    setCreateName('')
    setCreateAccess('read')
    setCreateOpen(true)
  }
  async function createConnection() {
    setCreatePending(true)
    try {
      const result = await api.createAgentDelegation(createName.trim(), createAccess)
      setCreateOpen(false)
      setCreateName('')
      setOneTimeCredential({ token: result.token, access: createAccess })
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
    onSuccess: () => {
      setRenameTarget(null)
      setRenameName('')
      setNotice('连接名称已更新。')
      setError('')
      refresh()
    },
    onError: (caught) => setError(caught instanceof ApiError ? caught.message : '重命名失败。'),
  })
  const revoke = useMutation({
    mutationFn: () => api.revokeAgentDelegation(revokeTarget!.id),
    onSuccess: () => {
      setRevokeTarget(null)
      setNotice('连接已永久吊销。')
      setError('')
      refresh()
    },
    onError: (caught) => setError(caught instanceof ApiError ? caught.message : '吊销失败。'),
  })

  async function copy(value: string, message: string) {
    try {
      await navigator.clipboard.writeText(value)
      setNotice(message)
      setError('')
    } catch {
      setError('无法写入剪贴板，请手动复制。')
    }
  }

  if (query.isLoading) return <Stack role="status" spacing={2} sx={{ p: { xs: 2, md: 3 } }}><Typography variant="h4">助手连接</Typography><Typography color="text.secondary">正在读取连接…</Typography></Stack>
  if (query.isError || !query.data) return <Stack role="alert" spacing={2} sx={{ p: { xs: 2, md: 3 } }}><Typography variant="h4">助手连接</Typography><Alert severity="error" action={<Button color="inherit" onClick={() => void query.refetch()}>重试</Button>}>连接列表读取失败。</Alert></Stack>

  const activeCount = query.data.connections.filter((connection) => connection.status === 'active').length
  const limitReached = activeCount >= query.data.max_active
  const creationDisabled = !query.data.enabled || limitReached

  return <Box sx={{ height: '100%', overflow: 'auto', p: { xs: 2, md: 3 }, maxWidth: 1200, mx: 'auto' }}>
    <Stack spacing={3}>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' }, justifyContent: 'space-between' }}>
        <Box><Typography component="h1" variant="h4" sx={{ fontWeight: 800 }}>助手连接</Typography><Typography color="text.secondary">让你自己电脑上的 OpenClaw 按所选权限访问当前账户。</Typography></Box>
        <Stack direction="row" spacing={1}>
          <Tooltip title="页面聚焦时也会更新；最近使用不代表 Agent 在线">
            <IconButton aria-label="刷新最近使用时间" onClick={() => void query.refetch()}><RefreshRounded /></IconButton>
          </Tooltip>
          <Button variant="contained" startIcon={<SmartToyRounded />} disabled={creationDisabled} onClick={openCreateDialog}>创建连接</Button>
        </Stack>
      </Stack>

      {notice && <Alert severity="success" onClose={() => setNotice('')}>{notice}</Alert>}
      {error && <Alert severity="error" onClose={() => setError('')}>{error}</Alert>}
      {!query.data.enabled && <Alert severity="warning">管理员尚未启用 Remote MCP。</Alert>}
      {limitReached && <Alert severity="info">已达到 {query.data.max_active} 个有效连接上限。</Alert>}

      <Paper variant="outlined" sx={{ p: { xs: 2, md: 2.5 }, borderRadius: uiRadii.panel }}>
        <Stack spacing={1}><Typography variant="h6" sx={{ fontWeight: 750 }}>连接方式</Typography><Typography color="text.secondary" variant="body2">Inteliscope 不连接你的本地 Gateway，也不会在服务器运行 Agent。每个用户在自己的电脑运行 OpenClaw，并通过下方 Remote MCP 地址读取自己的数据。</Typography><Box component="code" sx={{ p: 1.5, bgcolor: 'surfaceContainer', borderRadius: 1, overflowWrap: 'anywhere' }}>{query.data.mcp_url || '功能尚未启用'}</Box></Stack>
      </Paper>

      <Stack spacing={1.5}>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}><Typography variant="h6" sx={{ fontWeight: 750 }}>我的连接</Typography><Typography color="text.secondary" variant="body2">{activeCount}/{query.data.max_active} 个有效连接</Typography></Stack>
        {!query.data.connections.length && <Paper variant="outlined" sx={{ p: 3, borderRadius: uiRadii.panel, textAlign: 'center' }}><Typography color="text.secondary">还没有助手连接。</Typography></Paper>}
        {query.data.connections.map((connection) => {
          const status = statusLabel(connection)
          return <Paper component="article" key={connection.id} variant="outlined" sx={{ p: 2, borderRadius: uiRadii.panel }}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ alignItems: { sm: 'center' } }}>
              <Box sx={{ flex: 1, minWidth: 0 }}><Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}><Typography component="h2" variant="h6" noWrap>{connection.name}</Typography><Chip size="small" label={status.label} color={status.color} /><Chip size="small" variant="outlined" label={connection.access === 'subscriptions_write' ? '可管理订阅' : '只读'} /></Stack><Typography variant="body2" color="text.secondary">{connection.last_used_at ? `最近使用 ${dateTime(connection.last_used_at)}` : '从未使用'} · 到期 {dateTime(connection.expires_at)} · {connection.token_prefix}…</Typography></Box>
              <Stack direction="row" spacing={1}><Button size="small" startIcon={<ContentCopyRounded />} onClick={() => void copy(configurationFor(query.data.mcp_url, connection.access), `${connection.name} 配置已复制。`)} aria-label={`复制 ${connection.name} 配置`}>复制配置</Button><Button size="small" onClick={() => { setRenameTarget(connection); setRenameName(connection.name) }} aria-label={`重命名 ${connection.name}`}>重命名</Button><Button size="small" color="error" disabled={connection.status !== 'active'} startIcon={<DeleteOutlineRounded />} onClick={() => setRevokeTarget(connection)} aria-label={`吊销 ${connection.name}`}>吊销</Button></Stack>
            </Stack>
          </Paper>
        })}
        <Typography color="text.secondary" variant="body2">可管理订阅不包括密钥、共享来源、任务、Feed 条目状态或刷新操作。</Typography>
      </Stack>

      <Paper variant="outlined" sx={{ p: { xs: 2, md: 2.5 }, borderRadius: uiRadii.panel }}>
        <Stack spacing={1.5}><Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between' }}><Typography variant="h6" sx={{ fontWeight: 750 }}>OpenClaw 配置</Typography><Button size="small" startIcon={<ContentCopyRounded />} onClick={() => void copy(configuration, '配置已复制。')}>复制配置</Button></Stack><Box component="pre" data-testid="openclaw-config-page" aria-label="OpenClaw 配置命令" tabIndex={0} sx={{ m: 0, p: 2, bgcolor: 'surfaceContainer', borderRadius: 1, overflow: 'auto', whiteSpace: 'pre-wrap', fontSize: 13 }}>{configuration}</Box><Typography color="text.secondary" variant="body2">令牌保存在本机 <Box component="code">~/.openclaw/.env</Box>，文件权限设为 0600。不要设置 OAuth，也不要运行 <Box component="code">openclaw mcp login</Box>。</Typography></Stack>
      </Paper>

      <Paper variant="outlined" sx={{ p: { xs: 2, md: 2.5 }, borderRadius: uiRadii.panel }}><Typography variant="h6" sx={{ fontWeight: 750, mb: 1 }}>故障排查</Typography><Stack component="ol" spacing={0.75} sx={{ pl: 2.5, my: 0 }}><Typography component="li" variant="body2">确认 <Box component="code">~/.openclaw/.env</Box> 权限为 0600，并已重新启动 OpenClaw。</Typography><Typography component="li" variant="body2">运行 doctor 和 status；401 表示令牌无效、过期、已吊销或用户已禁用。</Typography><Typography component="li" variant="body2">“最近使用”只表示服务器最近收到过调用，不能判断本地 Agent 是否在线。</Typography></Stack></Paper>
    </Stack>

    <Dialog open={createOpen} onClose={() => !createPending && setCreateOpen(false)} fullWidth maxWidth="sm" aria-labelledby="create-agent-title"><DialogTitle id="create-agent-title">创建助手连接</DialogTitle><DialogContent><Stack spacing={1}><TextField autoFocus fullWidth margin="dense" label="连接名称" value={createName} onChange={(event) => setCreateName(event.target.value)} slotProps={{ htmlInput: { maxLength: 80 } }} helperText={`令牌有效 ${query.data.token_ttl_days} 天，只会显示一次。`} /><TextField select fullWidth margin="dense" label="访问权限" value={createAccess} onChange={(event) => setCreateAccess(event.target.value as AgentDelegationAccess)}><MenuItem value="read">只读</MenuItem>{user.role !== 'viewer' && <MenuItem value="subscriptions_write" disabled={!query.data.subscription_writes_enabled}>可管理订阅</MenuItem>}</TextField>{user.role !== 'viewer' && !query.data.subscription_writes_enabled && <Typography color="text.secondary" variant="body2">管理员尚未启用订阅管理连接；你仍可创建只读连接。</Typography>}<Typography color="text.secondary" variant="body2">只读连接可读取信息流、订阅、来源健康和任务摘要。可管理订阅连接还可准备并确认私有来源和订阅变更，但不能管理密钥、共享来源、任务、Feed 条目状态或刷新操作。</Typography></Stack></DialogContent><DialogActions><Button onClick={() => setCreateOpen(false)} disabled={createPending}>取消</Button><Button variant="contained" disabled={!createName.trim() || createPending} onClick={() => void createConnection()}>{createPending ? '生成中…' : '生成一次性令牌'}</Button></DialogActions></Dialog>

    <Dialog open={Boolean(oneTimeCredential)} onClose={() => undefined} fullWidth maxWidth="md" aria-labelledby="one-time-token-title"><DialogTitle id="one-time-token-title">保存一次性令牌</DialogTitle><DialogContent><Alert severity="warning" sx={{ mb: 2 }}>关闭后无法恢复。请先保存到本机环境文件，再明确确认。</Alert><Stack spacing={2}><Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} sx={{ alignItems: { sm: 'center' } }}><Box component="code" sx={{ flex: 1, p: 1.5, bgcolor: 'surfaceContainer', borderRadius: 1, overflowWrap: 'anywhere' }}>{oneTimeCredential?.token}</Box><Button startIcon={<ContentCopyRounded />} onClick={() => oneTimeCredential && void copy(oneTimeCredential.token, '令牌已复制。')}>复制令牌</Button></Stack><Box><Typography variant="subtitle2" gutterBottom>1. 写入本机环境文件并限制权限</Typography><Box component="pre" aria-label="本地令牌环境命令" tabIndex={0} sx={{ p: 1.5, bgcolor: 'surfaceContainer', borderRadius: 1, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{'INTELISCOPE_MCP_TOKEN=<一次性令牌>\nchmod 0600 ~/.openclaw/.env'}</Box></Box><Box><Typography variant="subtitle2" gutterBottom>2. 配置并检查 OpenClaw</Typography><Box component="pre" data-testid="openclaw-config" aria-label="OpenClaw 配置命令" tabIndex={0} sx={{ p: 1.5, bgcolor: 'surfaceContainer', borderRadius: 1, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{oneTimeConfiguration}</Box></Box></Stack></DialogContent><Divider /><DialogActions><Button variant="contained" onClick={() => { setOneTimeCredential(null); setNotice('一次性令牌已从页面清除。') }}>我已保存</Button></DialogActions></Dialog>

    <Dialog open={Boolean(renameTarget)} onClose={() => !rename.isPending && setRenameTarget(null)} fullWidth maxWidth="sm" aria-labelledby="rename-agent-title"><DialogTitle id="rename-agent-title">重命名助手连接</DialogTitle><DialogContent><TextField autoFocus fullWidth margin="dense" label="连接名称" value={renameName} onChange={(event) => setRenameName(event.target.value)} slotProps={{ htmlInput: { maxLength: 80 } }} /></DialogContent><DialogActions><Button onClick={() => setRenameTarget(null)} disabled={rename.isPending}>取消</Button><Button variant="contained" onClick={() => rename.mutate()} disabled={!renameName.trim() || rename.isPending}>保存名称</Button></DialogActions></Dialog>

    <Dialog open={Boolean(revokeTarget)} onClose={() => !revoke.isPending && setRevokeTarget(null)} aria-labelledby="revoke-agent-title"><DialogTitle id="revoke-agent-title">吊销助手连接</DialogTitle><DialogContent><Typography>吊销后无法恢复，OpenClaw 的下一次请求会立即失败。需要恢复时请创建新连接。</Typography></DialogContent><DialogActions><Button onClick={() => setRevokeTarget(null)} disabled={revoke.isPending}>取消</Button><Button color="error" variant="contained" onClick={() => revoke.mutate()} disabled={revoke.isPending}>确认吊销</Button></DialogActions></Dialog>
  </Box>
}
