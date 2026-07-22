import { useEffect, useMemo, useRef, useState, type Key } from 'react'

import {
  Button,
  Card,
  ComboBox,
  Form,
  Icons,
  Input,
  Label,
  ListBox,
  Popover,
  TextArea,
  TextField,
  Tooltip,
} from '../../design-system'
import { buildAgentHandoffPrompt, type AgentContextItem } from '../workbench-live/agentContext'
import { HandoffComposer } from '../workbench-live/HandoffComposer'
import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import type { useOpenClawChat } from './useOpenClawChat'

type ChatController = ReturnType<typeof useOpenClawChat>

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

function contextLabel(item: AgentContextItem): string {
  return item.sourceName ? `${item.sourceName} · ${item.title}` : item.title
}

function ContextRow({ item, onRemove }: { item: AgentContextItem; onRemove: () => void }) {
  const label = contextLabel(item)
  return <div data-composer-context-item className="flex h-8 min-w-0 items-center gap-2 rounded-lg bg-default px-2">
    <span className="type-label min-w-0 flex-1 truncate" title={label}>{label}</span>
    <Button size="sm" variant="ghost" isIconOnly className="size-7 shrink-0" aria-label={`移除 ${label}`} onPress={onRemove}>
      <Icons.X size={13} aria-hidden="true" />
    </Button>
  </div>
}

function ContextSummary({ value }: { value: WorkbenchAgentContextValue }) {
  const count = value.draft.items.length
  if (!count) return null
  return <div className="mb-2 min-w-0 rounded-xl border border-separator bg-surface-secondary p-2" aria-label={`已附带 ${count} 条信息`}>
    <div className="mb-1.5 flex min-w-0 items-center justify-between gap-2 px-1">
      <span className="type-label text-muted">已附带 {count} 条</span>
      <Popover>
        <Popover.Trigger className="type-label shrink-0 rounded-lg px-1.5 py-1 text-accent hover:bg-default focus-visible:outline-2 focus-visible:outline-focus">查看全部</Popover.Trigger>
        <Popover.Content placement="top end" offset={8} className="z-50 w-[min(340px,calc(100vw-24px))] p-0">
          <Popover.Dialog aria-label="管理全部上下文" className="max-h-[min(520px,70dvh)] min-w-0 overflow-x-hidden p-3">
            <Popover.Heading className="type-page-title mb-2">已附带 {count} 条信息</Popover.Heading>
            <div className="quiet-scroll-region grid min-w-0 gap-1.5 overflow-x-hidden overflow-y-auto">
              {value.draft.items.map((item) => <ContextRow key={item.articleId} item={item} onRemove={() => value.removeItem(item.articleId)} />)}
            </div>
          </Popover.Dialog>
        </Popover.Content>
      </Popover>
    </div>
    <div className="grid min-w-0 gap-1">
      {value.draft.items.slice(0, 2).map((item) => <ContextRow key={item.articleId} item={item} onRemove={() => value.removeItem(item.articleId)} />)}
    </div>
  </div>
}

function formatContextWindow(value?: number): string {
  if (!value) return ''
  if (value >= 1_000_000) return `${Math.round(value / 100_000) / 10}M 上下文`
  if (value >= 1000) return `${Math.round(value / 1000)}k 上下文`
  return `${value} 上下文`
}

function RuntimeControls({ chat }: { chat: ChatController }) {
  const [open, setOpen] = useState(false)
  const currentModel = chat.models.find((model) => model.id === chat.runtimeSelection.modelId)
  const controlsDisabled = chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading
  const currentThinking = chat.thinkingOptions.find((option) => option.id === chat.runtimeSelection.thinkingLevel)
  const runtimeLabel = currentModel
    ? `${currentModel.name} · ${currentThinking?.label ?? '自动'}`
    : chat.runtimeLoading ? '正在读取模型…' : 'OpenClaw 当前设置'

  return <Popover isOpen={controlsDisabled ? false : open} onOpenChange={(next) => { if (!controlsDisabled && chat.models.length) setOpen(next) }}>
    <Popover.Trigger
      aria-label={`OpenClaw 运行设置：${runtimeLabel}`}
      aria-disabled={controlsDisabled || !chat.models.length}
      className={`type-control flex w-full min-w-0 max-w-full items-center gap-1 overflow-hidden rounded-lg px-1.5 py-1 focus-visible:outline-2 focus-visible:outline-focus ${controlsDisabled || !chat.models.length ? 'cursor-default text-muted' : 'text-foreground hover:bg-default'}`}
    >
      <span className="min-w-0 truncate">{runtimeLabel}</span>
      <Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" />
    </Popover.Trigger>
    <Popover.Content placement="top start" offset={8} className="z-50 w-[min(360px,calc(100vw-24px))] p-0">
      <Popover.Dialog aria-label="OpenClaw 运行设置" className="min-w-0 overflow-x-hidden p-3">
        <Popover.Heading className="type-page-title">当前对话运行设置</Popover.Heading>
        <p className="type-meta mt-1 text-muted">模型以 OpenClaw 返回的实际会话为准；切换时会保留当前上下文。</p>
        <ComboBox
          selectedKey={chat.runtimeSelection.modelId ?? undefined}
          onSelectionChange={(key: Key | null) => {
            if (key === null || String(key) === chat.runtimeSelection.modelId) return
            void chat.setModel(String(key)).then((success) => { if (success) setOpen(false) })
          }}
          isDisabled={controlsDisabled}
          className="mt-3 min-w-0"
        >
          <Label>模型</Label>
          <ComboBox.InputGroup className="min-w-0">
            <Input aria-label="搜索 OpenClaw 模型" className="type-control min-w-0" />
            <ComboBox.Trigger aria-label="显示 OpenClaw 模型"><Icons.ChevronDown size={14} aria-hidden="true" /></ComboBox.Trigger>
          </ComboBox.InputGroup>
          <ComboBox.Popover className="w-[min(336px,calc(100vw-40px))]">
            <ListBox items={chat.models}>
              {(model) => <ListBox.Item id={model.id} textValue={`${model.name} ${model.provider}`} className="min-w-0">
                <span className="type-control block min-w-0 truncate">{model.name}</span>
                <span className="type-meta block min-w-0 truncate text-muted">{model.provider}{formatContextWindow(model.contextWindow) ? ` · ${formatContextWindow(model.contextWindow)}` : ''}</span>
              </ListBox.Item>}
            </ListBox>
          </ComboBox.Popover>
        </ComboBox>
        <div className="mt-3 min-w-0">
          <span className="type-label text-muted">推理程度</span>
          <div className="mt-1.5 flex min-w-0 flex-wrap gap-1" role="group" aria-label="OpenClaw 推理档位">
            <Button
              size="sm"
              variant={chat.runtimeSelection.thinkingLevel === null ? 'primary' : 'ghost'}
              isDisabled={controlsDisabled}
              aria-pressed={chat.runtimeSelection.thinkingLevel === null}
              onPress={() => void chat.setThinking(null)}
            >自动</Button>
            {currentModel?.reasoning !== false && chat.thinkingOptions.map((option) => <Button
              key={option.id}
              size="sm"
              variant={chat.runtimeSelection.thinkingLevel === option.id ? 'primary' : 'ghost'}
              isDisabled={controlsDisabled}
              aria-pressed={chat.runtimeSelection.thinkingLevel === option.id}
              onPress={() => void chat.setThinking(option.id)}
            >{option.label}</Button>)}
          </div>
          {currentModel?.reasoning === false && <p className="type-meta mt-1.5 text-muted">此模型未提供推理档位。</p>}
        </div>
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}

function ConnectedConversation({ chat, value }: { chat: ChatController; value: WorkbenchAgentContextValue }) {
  const canSend = Boolean(value.draft.question.trim() || value.draft.items.length)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const followRef = useRef(true)

  useEffect(() => {
    if (!followRef.current) return
    const region = scrollRef.current
    if (!region) return
    window.requestAnimationFrame(() => { region.scrollTop = region.scrollHeight })
  }, [chat.messages.length, chat.streamText])

  async function send() {
    if (!canSend || chat.isRunning) return
    const draft = {
      ...value.draft,
      items: value.draft.items.map((item) => ({ ...item })),
    }
    const displayText = draft.question.trim() || `分析已附带的 ${draft.items.length} 条信息`
    const pending = chat.send({
      displayText,
      gatewayPrompt: buildAgentHandoffPrompt(draft),
      contextItems: draft.items,
    })
    value.clearComposer()
    await pending
  }

  function editFailed(messageId: string) {
    const request = chat.takeFailedMessage(messageId)
    if (!request) return
    value.restoreComposer(request.displayText, request.contextItems)
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-label="发送给 OpenClaw 的问题"]')?.focus())
  }

  return <>
    <div
      ref={scrollRef}
      className="quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto p-4"
      data-testid="agent-scroll-region"
      aria-live="polite"
      onScroll={(event) => {
        const region = event.currentTarget
        followRef.current = region.scrollHeight - region.scrollTop - region.clientHeight <= 96
      }}
    >
      <div className="mb-3 flex min-w-0 items-center justify-between gap-2">
        <span className="type-meta min-w-0 truncate text-muted">{chat.sessionKey ? 'Inteliscope 对话' : '正在准备对话'}</span>
        <div className="flex shrink-0 gap-1"><Button size="sm" variant="ghost" isDisabled={chat.isRunning || chat.runtimeUpdating} onPress={() => void chat.newConversation()}><Icons.Plus size={14} />新对话</Button><Button size="sm" variant="ghost" onPress={chat.disconnect}>断开</Button></div>
      </div>
      {chat.toolsStatus === 'missing' && <Card variant="secondary" className="mb-3 min-w-0 border-warning/40 p-3" role="status"><Card.Title>未发现 Inteliscope 工具</Card.Title><Card.Description className="mt-1">OpenClaw 已连接，但还需要在助手连接页面配置 Remote MCP 与 Skill。</Card.Description><a className="type-control mt-2 inline-flex text-accent" href="/agents">打开助手连接</a></Card>}
      {!chat.messages.length && !chat.streamText && <Card variant="transparent" className="min-w-0 p-4 text-center"><Card.Description>可以分析已选文章，也可以直接询问来源异常、任务失败或订阅配置。</Card.Description></Card>}
      <div className="grid min-w-0 gap-3 overflow-x-hidden">
        {chat.messages.map((message) => <div
          key={message.id}
          className={`type-body min-w-0 max-w-full whitespace-pre-wrap break-words rounded-2xl p-3 [overflow-wrap:anywhere] ${message.role === 'user' ? 'ml-6 bg-accent/12' : 'mr-2 bg-surface-secondary'}`}
          data-chat-role={message.role}
          data-chat-status={message.status}
        >
          <div className="min-w-0 max-w-full [overflow-wrap:anywhere]">{message.text}</div>
          {Boolean(message.contextCount) && <div className="type-label mt-2 text-muted">附带 {message.contextCount} 条信息</div>}
          {message.status === 'aborted' && <div className="type-label mt-2 text-muted">已停止</div>}
          {message.status === 'failed' && message.role === 'user' && <div className="mt-2 flex flex-wrap gap-1">
            <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => void chat.retry(message.id)}>重试</Button>
            <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => editFailed(message.id)}>重新编辑</Button>
          </div>}
        </div>)}
        {chat.streamText && <div className="type-body mr-2 min-w-0 max-w-full whitespace-pre-wrap break-words rounded-2xl bg-surface-secondary p-3 [overflow-wrap:anywhere]" data-chat-role="assistant">{chat.streamText}</div>}
      </div>
      {chat.issue && <p role="alert" className="type-body mt-3 max-w-full break-words text-danger [overflow-wrap:anywhere]">{chat.issue.message}</p>}
    </div>
    <div data-testid="openclaw-composer-dock" className="min-w-0 shrink-0 overflow-x-hidden border-t border-separator p-3">
      <ContextSummary value={value} />
      <div data-testid="openclaw-composer" className="grid min-w-0 grid-rows-[minmax(96px,auto)_36px] gap-2 rounded-2xl border border-separator bg-surface-secondary p-2 shadow-sm focus-within:border-border">
        <TextArea
          fullWidth
          variant="secondary"
          className="type-body min-h-24 min-w-0 max-w-full [overflow-wrap:anywhere]"
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
        <div data-testid="openclaw-composer-toolbar" className="grid min-w-0 grid-cols-[minmax(0,1fr)_36px] items-end gap-1.5 px-1 pb-0.5">
          <RuntimeControls chat={chat} />
          {chat.isRunning ? <Tooltip delay={250}>
            <Tooltip.Trigger className="contents"><Button
              size="sm"
              isIconOnly
              aria-label="停止生成"
              isDisabled={chat.isStopping}
              onPress={() => void chat.stop()}
              className="size-9 shrink-0 rounded-full"
            ><Icons.Square size={14} fill="currentColor" aria-hidden="true" /></Button></Tooltip.Trigger>
            <Tooltip.Content>{chat.isStopping ? '正在停止…' : '停止生成'}</Tooltip.Content>
          </Tooltip> : <Button size="sm" isIconOnly className="size-9 shrink-0 rounded-full" aria-label="发送给 OpenClaw" isDisabled={!canSend || chat.status !== 'connected'} onPress={() => void send()}><Icons.ArrowUp size={16} /></Button>}
        </div>
        {chat.runtimeIssue && <p role="status" className="type-label mt-1 max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">{chat.runtimeIssue}</p>}
        {chat.modelSwitchFallback && <Button
          size="sm"
          variant="ghost"
          className="mt-1 max-w-full"
          isDisabled={chat.isRunning || chat.runtimeUpdating}
          onPress={() => void chat.switchToBlankConversation()}
        >新建空白对话并切换到 {chat.modelSwitchFallback.modelName}</Button>}
      </div>
    </div>
  </>
}

export function OpenClawConversation({ chat, value }: { chat: ChatController; value: WorkbenchAgentContextValue }) {
  if (chat.status === 'disabled') return <>
    <div className="quiet-scroll-region min-h-0 min-w-0 overflow-x-hidden overflow-y-auto p-4" data-testid="agent-scroll-region">
      <Card variant="transparent" className="p-3"><Card.Description>站内 OpenClaw 对话尚未启用；仍可复制交接提示词到自己的 OpenClaw。</Card.Description></Card>
    </div>
    <HandoffComposer value={value} />
  </>
  if (chat.status !== 'connected' && chat.status !== 'reconnecting') return <SetupPanel key={chat.gatewayUrl} chat={chat} />
  return <ConnectedConversation chat={chat} value={value} />
}
