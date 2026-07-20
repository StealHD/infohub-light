import { useMemo, useState } from 'react'

import {
  Button,
  Card,
  Chip,
  CompactSelect,
  Form,
  Icons,
  Input,
  Label,
  TextArea,
  TextField,
} from '../../design-system'
import { buildAgentHandoffPrompt, type AgentModelPreference } from '../workbench-live/agentContext'
import { HandoffComposer } from '../workbench-live/HandoffComposer'
import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import type { useOpenClawChat } from './useOpenClawChat'

type ChatController = ReturnType<typeof useOpenClawChat>

const modelOptions = [
  { id: 'auto', label: '自动 · OpenClaw 决定' },
  { id: 'fast', label: '速度优先' },
  { id: 'deep', label: '深度分析' },
]

export function gatewayOriginSetupCommands(origin: string) {
  const shellOrigin = origin.replaceAll("'", "'\\''")
  const shell = [
    `ORIGIN='${shellOrigin}'`,
    'CURRENT="$(openclaw config get gateway.controlUi.allowedOrigins --json 2>/dev/null || printf \'[]\')"',
    'MERGED="$(node -e \'const xs=JSON.parse(process.argv[1]); process.stdout.write(JSON.stringify([...new Set([...xs, process.argv[2]])]))\' "$CURRENT" "$ORIGIN")"',
    'openclaw config set gateway.controlUi.allowedOrigins "$MERGED" --strict-json',
    'openclaw gateway restart',
  ].join('\n')
  const powerShellOrigin = origin.replaceAll("'", "''")
  const powershell = [
    `$origin = '${powerShellOrigin}'`,
    '$current = openclaw config get gateway.controlUi.allowedOrigins --json | ConvertFrom-Json',
    '$merged = @($current + $origin | Sort-Object -Unique) | ConvertTo-Json -Compress',
    'openclaw config set gateway.controlUi.allowedOrigins $merged --strict-json',
    'openclaw gateway restart',
  ].join('\n')
  return { shell, powershell }
}

function SetupPanel({ chat }: { chat: ChatController }) {
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
    <div className="min-h-0 overflow-y-auto p-4" data-testid="agent-scroll-region">
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
          <Button type="submit" isDisabled={!url.trim() || !authInput.trim() || chat.status === 'connecting'}>
            {chat.status === 'connecting' ? '正在连接…' : '连接并授权'}
          </Button>
          <Button
            type="button"
            variant="secondary"
            isDisabled={!url.trim() || chat.status === 'connecting'}
            onPress={() => void chat.connect(undefined, url)}
          >
            使用已配对设备重连
          </Button>
        </Form>
      </Card>

      {chat.issue && <Card variant="secondary" className="mt-3 border-warning/40 p-4" role="alert">
        <Card.Title>{chat.issue.message}</Card.Title>
        {chat.issue.kind === 'pairing' && <div className="type-body mt-3 grid gap-2 text-muted">
          <p>在运行 OpenClaw 的电脑执行：</p>
          <pre className="overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{`openclaw devices list\nopenclaw devices approve ${chat.issue.requestId || '<requestId>'}`}</pre>
          <p>批准后保留当前页面中的 token，再点击“连接并授权”。</p>
        </div>}
        {chat.issue.kind === 'origin' && <div className="type-body mt-3 grid gap-3 text-muted">
          <p>下面的命令只追加当前站点，不会覆盖已有 Origin，也不要配置通配符。</p>
          <div><div className="mb-1 flex items-center justify-between"><strong>macOS / Linux</strong><Button size="sm" variant="ghost" onPress={() => void copy(commands.shell)}><Icons.Copy size={14} />复制</Button></div><pre className="overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{commands.shell}</pre></div>
          <div><div className="mb-1 flex items-center justify-between"><strong>PowerShell</strong><Button size="sm" variant="ghost" onPress={() => void copy(commands.powershell)}><Icons.Copy size={14} />复制</Button></div><pre className="overflow-auto whitespace-pre-wrap rounded-lg bg-default p-3">{commands.powershell}</pre></div>
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

function ConnectedConversation({ chat, value }: { chat: ChatController; value: WorkbenchAgentContextValue }) {
  const canSend = Boolean(value.draft.question.trim() || value.draft.items.length)

  async function send() {
    if (!canSend) return
    await chat.send(buildAgentHandoffPrompt(value.draft), value.draft.modelPreference)
  }

  return <>
    <div className="min-h-0 overflow-y-auto p-4" data-testid="agent-scroll-region" aria-live="polite">
      <div className="mb-3 flex items-center justify-between gap-2">
        <span className="type-meta text-muted">{chat.sessionKey ? 'Inteliscope 对话' : '正在准备对话'}</span>
        <div className="flex gap-1"><Button size="sm" variant="ghost" onPress={() => void chat.newConversation()}><Icons.Plus size={14} />新对话</Button><Button size="sm" variant="ghost" onPress={chat.disconnect}>断开</Button></div>
      </div>
      {chat.toolsStatus === 'missing' && <Card variant="secondary" className="mb-3 border-warning/40 p-3" role="status"><Card.Title>未发现 Inteliscope 工具</Card.Title><Card.Description className="mt-1">OpenClaw 已连接，但还需要在助手连接页面配置 Remote MCP 与 Skill。</Card.Description><a className="type-control mt-2 inline-flex text-accent" href="/agents">打开助手连接</a></Card>}
      {!chat.messages.length && !chat.streamText && <Card variant="transparent" className="p-4 text-center"><Card.Description>可以分析已选文章，也可以直接询问来源异常、任务失败或订阅配置。</Card.Description></Card>}
      <div className="grid gap-3">
        {chat.messages.map((message) => <div key={message.id} className={`type-body whitespace-pre-wrap rounded-2xl p-3 ${message.role === 'user' ? 'ml-6 bg-accent/12' : 'mr-2 bg-surface-secondary'}`} data-chat-role={message.role}>{message.text}</div>)}
        {chat.streamText && <div className="type-body mr-2 whitespace-pre-wrap rounded-2xl bg-surface-secondary p-3" data-chat-role="assistant">{chat.streamText}</div>}
      </div>
      {chat.issue && <p role="alert" className="type-body mt-3 text-danger">{chat.issue.message}</p>}
    </div>
    <div className="border-t border-separator p-3">
      {value.draft.items.length > 0 && <div className="mb-2 flex flex-wrap gap-1.5" aria-label={`附带 ${value.draft.items.length} 篇文章`}>
        {value.draft.items.map((item) => <Chip key={item.articleId} size="sm" variant="soft"><Chip.Label>{item.sourceName ? `${item.title} · ${item.sourceName}` : item.title}</Chip.Label></Chip>)}
      </div>}
      <div className="rounded-2xl border border-separator bg-surface-secondary p-2 shadow-sm focus-within:border-border">
        <TextArea
          fullWidth
          variant="secondary"
          className="type-body"
          aria-label="发送给 OpenClaw 的问题"
          value={value.draft.question}
          maxLength={1200}
          rows={3}
          placeholder="分析文章，或询问来源和任务…"
          onChange={(event) => value.setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              void send()
            }
          }}
        />
        <div className="mt-2 flex items-center gap-1.5 px-1 pb-0.5">
          <span className="type-label shrink-0 text-muted">附带 {value.draft.items.length} 篇</span>
          <CompactSelect
            ariaLabel="模型偏好"
            value={value.draft.modelPreference}
            options={modelOptions}
            onChange={(preference) => value.setModelPreference(preference as AgentModelPreference)}
            className="flex-1"
          />
          {chat.isRunning ? <Button size="sm" variant="ghost" aria-label="停止 OpenClaw 回复" onPress={() => void chat.stop()}><Icons.Square size={15} />停止</Button> : <Button size="sm" isIconOnly className="size-9 rounded-full" aria-label="发送给 OpenClaw" isDisabled={!canSend || chat.status !== 'connected'} onPress={() => void send()}><Icons.ArrowUp size={16} /></Button>}
        </div>
      </div>
    </div>
  </>
}

export function OpenClawConversation({ chat, value }: { chat: ChatController; value: WorkbenchAgentContextValue }) {
  if (chat.status === 'disabled') return <>
    <div className="min-h-0 overflow-y-auto p-4" data-testid="agent-scroll-region">
      <Card variant="transparent" className="p-3"><Card.Description>站内 OpenClaw 对话尚未启用；仍可复制交接提示词到自己的 OpenClaw。</Card.Description></Card>
    </div>
    <HandoffComposer value={value} />
  </>
  if (chat.status !== 'connected' && chat.status !== 'reconnecting') return <SetupPanel key={chat.gatewayUrl} chat={chat} />
  return <ConnectedConversation chat={chat} value={value} />
}
