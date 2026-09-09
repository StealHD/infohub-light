import { useEffect, useRef, useState } from 'react'
import { Button, Checkbox, Input, Label, Modal, StableAsyncButton } from '../../design-system'
import type { AgentConnection } from '../../api/agentConnectionService'
import { ApiError } from '../../api/client'
import { useAgentConnectionContext } from './AgentConnectionContext'

const install = 'python scripts/provision_openclaw_agent.py install --root ~/.openclaw --bundle-dir ./personal-agent'
const verify = 'python scripts/provision_openclaw_agent.py verify --root ~/.openclaw --bundle-dir ./personal-agent --receipt ./receipt.json'

export function AgentSetupDialog({ state, onClose, onRefresh }: {
  state: AgentConnection; onClose: () => void; onRefresh: () => Promise<unknown>
}) {
  const { api } = useAgentConnectionContext()
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [receipt, setReceipt] = useState('')
  const [prepared, setPrepared] = useState(state.state === 'pending_verification')
  const [activated, setActivated] = useState(false)
  const latch = useRef(false)
  const alive = useRef(true)
  const fileVersion = useRef(0)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; fileVersion.current += 1 }
  }, [])
  const run = async (operation: () => Promise<void>) => {
    if (latch.current) return
    latch.current = true; setBusy(true); setError('')
    try { await operation(); if (alive.current) await onRefresh() }
    catch (error) { if (alive.current) setError(error instanceof ApiError ? error.message
      : '操作结果未确认。请刷新接入状态后再手动重试。') }
    finally { latch.current = false; if (alive.current) setBusy(false) }
  }
  const download = async () => {
    const result = await api.agentConnectionBundle()
    if (!alive.current) return
    const bytes = Uint8Array.from(atob(result.archive_base64), (character) => character.charCodeAt(0))
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/gzip' }))
    const anchor = document.createElement('a')
    anchor.href = url; anchor.download = 'personal-agent.tar.gz'
    document.body.append(anchor); anchor.click(); anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <Modal isOpen onOpenChange={(open) => { if (!open && !latch.current) onClose() }}>
    <Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={busy}><Modal.Container size="lg"><Modal.Dialog>
      <Modal.Header><Modal.Heading>配置个人 Agent</Modal.Heading></Modal.Header>
      <Modal.Body className="grid gap-4">
        {activated ? <p role="status" className="type-body">个人绑定已验证。关闭后进入 OpenClaw 连接；模型沿用 OpenClaw 配置，聊天和通知尚未测试。</p> : <>
          <p className="type-body">为当前账号建立独立 Agent，不修改已有数据连接。网页负责准备和激活；配置需安装到你管理的 OpenClaw 主机，不会自动重启 Gateway。</p>
          <Checkbox isSelected={confirmed} onChange={setConfirmed} isDisabled={busy}>
            <Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>
            <Checkbox.Content><Label>我是此 OpenClaw 的管理员，确认配置包仅用于本人受信任主机</Label></Checkbox.Content>
          </Checkbox>
          {!prepared ? <StableAsyncButton pending={busy} pendingContent="正在准备…" isDisabled={!confirmed} onPress={() => void run(async () => {
            const result = await api.prepareAgentConnection()
            if (result.state !== 'pending_verification') throw new Error('Refresh required')
            if (alive.current) setPrepared(true)
          })}>准备个人接入</StableAsyncButton> : <>
            <section className="grid gap-2"><h3 className="type-page-title">1. 下载个人配置</h3>
              <p className="type-body">包含本人只读数据令牌。不要分享或提交 Git，安装后删除下载副本。下载失败可重试，不会新建第二个 Agent。</p>
              <StableAsyncButton pending={busy} pendingContent="正在处理…" isDisabled={!confirmed} onPress={() => void run(download)}>下载配置包</StableAsyncButton>
            </section>
            <section className="grid gap-2"><h3 className="type-page-title">2. 在 OpenClaw 主机安装并验证</h3>
              <p className="type-body">在本项目代码目录解压配置包，使用已有 Python 环境执行。安装后按该主机原有方式重载 Gateway，再执行验证命令。</p>
              {["tar -xzf personal-agent.tar.gz", install, verify].map((command) => <code key={command} className="type-meta break-all rounded-lg bg-default p-3">{command}</code>)}
              <p className="type-meta text-muted">使用自定义 OpenClaw 目录时替换 --root。验证只检查配置和 MCP 读取，不调用模型或发送通知。</p>
            </section>
            <section className="grid gap-2"><h3 className="type-page-title">3. 提交验证回执</h3>
              <Label htmlFor="agent-setup-receipt">选择刚生成的 receipt.json（1 小时内有效）</Label>
              <Input id="agent-setup-receipt" type="file" accept=".json,application/json" disabled={busy} onChange={(event) => {
                const version = ++fileVersion.current
                const file = event.target.files?.[0]; setReceipt(''); setError('')
                if (!file) return
                if (file.size > 8192) { setError('回执文件不能超过 8 KB。'); return }
                void file.text().then((text) => {
                  if (alive.current && version === fileVersion.current) setReceipt(text)
                }).catch(() => { if (alive.current && version === fileVersion.current) setError('无法读取回执，请重新选择。') })
              }} />
              <StableAsyncButton pending={busy} pendingContent="正在验证…" isDisabled={!confirmed || !receipt} onPress={() => void run(async () => {
                await api.activateAgentConnection(receipt)
                if (alive.current) { setReceipt(''); setActivated(true) }
              })}>验证并完成接入</StableAsyncButton>
            </section>
          </>}
        </>}
        {error && <p role="alert" className="type-body text-danger">{error}</p>}
      </Modal.Body>
      <Modal.Footer><Button variant="ghost" isDisabled={busy} onPress={onClose}>关闭</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop>
  </Modal>
}
