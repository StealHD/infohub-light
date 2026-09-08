import { isManagedGateway } from '../gateway/openclawManaged'
import { OpenClawManagedSetup } from './OpenClawManagedSetup'
import { useMemo, useState } from 'react'

import { Button, Card, Form, Icons, Input, Label, StableAsyncButton, TextField } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import { gatewayOriginSetupCommands } from '../openclawOriginSetup'

type ChatController = OpenClawChatController

export function OpenClawSetupPanel({ chat, variant = 'compact' }: {
  chat: ChatController
  variant?: 'compact' | 'workspace'
}) {
  const [url, setUrl] = useState(chat.gatewayUrl)
  const [authInput, setAuthInput] = useState('')
  const [copyNotice, setCopyNotice] = useState('')
  const commands = useMemo(() => gatewayOriginSetupCommands(window.location.origin), [])

  async function connect() {
    const success = await chat.connect(authInput, url)
    if (success) setAuthInput('')
  }

  async function copy(value: string) {
    try {
      await navigator.clipboard.writeText(value)
      setCopyNotice('命令已复制')
    } catch {
      setCopyNotice('复制失败，请手动选择')
    }
  }

  if (isManagedGateway(chat.gatewayUrl)) return <OpenClawManagedSetup chat={chat} variant={variant} />
  const form = <>
    <h2 className="type-section-title">连接你的 OpenClaw</h2>
    <p className="type-body mt-1 text-muted">本地地址已经填好。首次连接粘贴 Gateway token，或直接粘贴 dashboard 完整地址。</p>
    <Form className="mt-5 grid gap-3" onSubmit={(event) => { event.preventDefault(); void connect() }}>
      <TextField fullWidth value={url} onChange={setUrl} isRequired>
        <Label>OpenClaw Gateway URL</Label>
        <Input aria-label="OpenClaw Gateway URL" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      </TextField>
      <TextField fullWidth value={authInput} onChange={setAuthInput} isRequired>
        <Label>Gateway token 或 dashboard 地址</Label>
        <Input aria-label="OpenClaw Gateway token" type="password" autoComplete="new-password" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
      </TextField>
      <div className={`grid min-w-0 items-stretch gap-2 ${variant === 'workspace' ? 'grid-cols-1 min-[640px]:grid-cols-2' : 'grid-cols-2'}`} data-testid="openclaw-setup-actions">
        <StableAsyncButton type="submit" className="h-auto min-h-10 w-full min-w-0 whitespace-normal px-2 py-2 text-center [overflow-wrap:anywhere]" pending={chat.status === 'connecting'} pendingContent="正在连接…" isDisabled={!url.trim() || !authInput.trim()}>连接并授权</StableAsyncButton>
        <StableAsyncButton type="button" variant="secondary" className="h-auto min-h-10 w-full min-w-0 whitespace-normal px-2 py-2 text-center [overflow-wrap:anywhere]" pending={chat.status === 'connecting'} pendingContent="正在连接…" isDisabled={!url.trim() || chat.status === 'connecting'} onPress={() => chat.connect(undefined, url)}>使用已配对设备重连</StableAsyncButton>
      </div>
    </Form>
    {variant === 'workspace' && <p className="type-meta mt-4 border-t border-separator pt-4 text-muted">Gateway token 只保留在这个连接表单中；配对成功后会立即从表单清除。</p>}
  </>

  return <>
    <div className={`quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto ${variant === 'workspace' ? 'px-4 py-10 min-[768px]:px-8 min-[768px]:py-16' : 'p-4'}`} data-testid="agent-scroll-region" data-page-scroll-region={variant === 'workspace' ? '' : undefined}>
      <div className={variant === 'workspace' ? 'mx-auto w-full max-w-xl' : ''}>
      {variant === 'workspace'
        ? <section className="py-2 min-[768px]:py-6">{form}</section>
        : <Card variant="secondary" className="p-4">{form}</Card>}

      {chat.issue && <Card variant="secondary" className="mt-3 border-warning/40 p-4" role="alert">
        <p className="type-body">{chat.issue.message}</p>
        {chat.issue.kind === 'pairing' && <div className="type-body mt-3 grid gap-2 text-muted">
          <p>在运行 OpenClaw 的电脑执行：</p>
          <pre className="max-w-full whitespace-pre-wrap break-words rounded-lg bg-default p-3 [overflow-wrap:anywhere]">{`openclaw devices list\nopenclaw devices approve ${chat.issue.requestId || '<requestId>'}`}</pre>
          <p>批准后保留当前页面中的 token，再点击“连接并授权”。</p>
        </div>}
        {chat.issue.kind === 'origin' && <div className="type-body mt-3 grid gap-3 text-muted">
          <p>下面的命令只追加当前站点，不会覆盖已有 Origin，也不要配置通配符。</p>
          <div><div className="mb-1 flex items-center justify-between"><strong>macOS / Linux</strong><Button size="sm" variant="ghost" onPress={() => void copy(commands.shell)}><Icons.Copy size={14} />复制</Button></div><pre className="max-w-full whitespace-pre-wrap break-words rounded-lg bg-default p-3 [overflow-wrap:anywhere]">{commands.shell}</pre></div>
          <div><div className="mb-1 flex items-center justify-between"><strong>PowerShell</strong><Button size="sm" variant="ghost" onPress={() => void copy(commands.powershell)}><Icons.Copy size={14} />复制</Button></div><pre className="max-w-full whitespace-pre-wrap break-words rounded-lg bg-default p-3 [overflow-wrap:anywhere]">{commands.powershell}</pre></div>
          <span role="status">{copyNotice}</span>
        </div>}
        {chat.issue.kind === 'network' && <Card.Description className="mt-2">如果 Chromium 弹出“访问本地网络”权限，请允许后重试；远程 Gateway 必须使用 wss://。</Card.Description>}
      </Card>}
      </div>
    </div>
    {variant === 'compact' && <div className="border-t border-separator p-3"><p className="type-meta text-muted">Gateway token 只保留在这个连接表单中；配对成功后会立即从表单清除。</p></div>}
  </>
}
