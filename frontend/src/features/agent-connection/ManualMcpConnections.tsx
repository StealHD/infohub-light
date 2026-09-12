import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Card, Input, Label, Modal, StableAsyncButton, TextField, actionToast } from '../../design-system'
import { useAgentConnectionContext } from './AgentConnectionContext'
import { agentConfiguration, oneTimeTokenWriteCommand } from '../openclaw/openclawAgentConfiguration'
import { OpenClawConfigurationCard } from '../admin-heroui/HeroAgentDelegationViews'

export function ManualMcpConnections() {
  const { api, userId } = useAgentConnectionContext()
  const query = useQuery({ queryKey: ['manual-mcp', userId], queryFn: ({ signal }) => api.agentDelegations(signal) })
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [token, setToken] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  if (!query.data?.enabled) return null
  const configuration = agentConfiguration(query.data.mcp_url)
  async function create() {
    if (pending || !name.trim()) return
    setPending(true); setError('')
    try { const created = await api.createAgentDelegation(name.trim(), 'role_default'); setToken(created.token); await query.refetch() }
    catch { setError('创建未确认，请刷新连接列表核对。') }
    finally { setPending(false) }
  }
  return <Card variant="secondary" className="p-4 mt-4">
    <Card.Title>外部 MCP 连接</Card.Title>
    <Card.Description>权限跟随账号角色：管理员可管理订阅、系统设置和工作区诊断；成员可读取和管理订阅；只读成员只能读取。服务写入开关关闭时对应操作不可用。</Card.Description>
    <Button className="mt-3" variant="secondary" onPress={() => { setName(''); setToken(''); setError(''); setOpen(true) }}>创建外部连接</Button>
    <div className="mt-3"><OpenClawConfigurationCard title="更新 OpenClaw 配置" description="已有手动连接执行一次此命令，解除旧工具过滤限制；继续使用原令牌。托管个人 Agent 自动更新。" configuration={configuration} configurationLabel="更新 MCP 配置命令" onCopy={() => { void navigator.clipboard.writeText(configuration).then(() => actionToast.success('配置命令已复制')).catch(() => actionToast.danger('复制失败，请手动选择命令')) }} /></div>
    <Modal isOpen={open} onOpenChange={(value) => { if (!pending) { setOpen(value); if (!value) setToken('') } }}>
      <Modal.Backdrop isDismissable={!pending}><Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>创建外部 MCP 连接</Modal.Heading></Modal.Header>
        <Modal.Body>{token ? <OpenClawConfigurationCard title="保存一次性令牌" description="令牌仅显示一次，在外部 OpenClaw 主机执行，然后执行上方更新配置命令。" configuration={oneTimeTokenWriteCommand(token)} configurationLabel="保存令牌命令" onCopy={() => { void navigator.clipboard.writeText(oneTimeTokenWriteCommand(token)).catch(() => actionToast.danger('复制失败')) }} />
          : <TextField value={name} onChange={setName}><Label>连接名称</Label><Input /></TextField>}
          {error && <p role="alert" className="type-body mt-3">{error}</p>}
        </Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={() => { setOpen(false); setToken('') }}>关闭</Button>
          {!token && <StableAsyncButton pending={pending} pendingContent="创建中…" isDisabled={!name.trim()} onPress={create}>创建连接</StableAsyncButton>}
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </Card>
}
