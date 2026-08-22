import { useMemo, useState } from 'react'

import { Button, Card, Form, Icons, Input, Label, TextField } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import { gatewayOriginSetupCommands } from '../openclawOriginSetup'

type ChatController = OpenClawChatController

export function OpenClawSetupPanel({ chat }: { chat: ChatController }) {
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

  return <>
    <div className="quiet-scroll-region min-h-0 min-w-0 overflow-x-hidden overflow-y-auto p-4" data-testid="agent-scroll-region">
      <Card variant="secondary" className="p-4">
        <Card.Title>连接你的 OpenClaw</Card.Title>
        <Card.Description className="mt-1">本地地址已经填好。首次连接粘贴 Gateway token，或直接粘贴 dashboard 完整地址。</Card.Description>
        <Form className="mt-4 grid gap-3" onSubmit={(event) => { event.preventDefault(); void connect() }}>
          <TextField fullWidth value={url} onChange={setUrl} isRequired>
            <Label>OpenClaw Gateway URL</Label>
            <Input aria-label="OpenClaw Gateway URL" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
          </TextField>
          <TextField fullWidth value={authInput} onChange={setAuthInput} isRequired>
            <Label>Gateway token 或 dashboard 地址</Label>
            <Input aria-label="OpenClaw Gateway token" type="password" autoComplete="new-password" autoCapitalize="off" autoCorrect="off" spellCheck={false} />
          </TextField>
          <div className="grid min-w-0 grid-cols-2 gap-2" data-testid="openclaw-setup-actions">
            <Button
              type="submit"
              className="h-auto min-h-10 min-w-0 whitespace-normal px-2 py-2 text-center [overflow-wrap:anywhere]"
              isDisabled={!url.trim() || !authInput.trim() || chat.status === 'connecting'}
            >
              {chat.status === 'connecting' ? '正在连接…' : '连接并授权'}
            </Button>
            <Button
              type="button"
              variant="secondary"
              className="h-auto min-h-10 min-w-0 whitespace-normal px-2 py-2 text-center [overflow-wrap:anywhere]"
              isDisabled={!url.trim() || chat.status === 'connecting'}
              onPress={() => void chat.connect(undefined, url)}
            >
              使用已配对设备重连
            </Button>
          </div>
        </Form>
      </Card>

      {chat.issue && <Card variant="secondary" className="mt-3 border-warning/40 p-4" role="alert">
        <Card.Title>{chat.issue.message}</Card.Title>
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
    <div className="border-t border-separator p-3">
      <p className="type-meta text-muted">Gateway token 只保留在这个连接表单中；配对成功后会立即从表单清除。</p>
    </div>
  </>
}
