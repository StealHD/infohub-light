import { useEffect, useId, useMemo, useRef, useState, type Key, type ReactNode } from 'react'

import {
  anchoredTooltipProps,
  Button,
  Card,
  Form,
  Header,
  Icons,
  Input,
  Label,
  ListBox,
  Popover,
  Select,
  TextArea,
  TextField,
  Tooltip,
  TooltipTriggerButton,
} from '../../design-system'
import { buildAgentHandoffPrompt, type AgentContextItem } from '../workbench-live/agentContext'
import { HandoffComposer } from '../workbench-live/HandoffComposer'
import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import type { useOpenClawChat } from './useOpenClawChat'
import type { OpenClawContextUsage, OpenClawModelOption } from './useOpenClawChat'

type ChatController = ReturnType<typeof useOpenClawChat>

type FormattedMessageTime = {
  label: string
  title: string
  dateTime: string
}

const contextTokenFormatter = new Intl.NumberFormat('zh-CN')
const CONTEXT_RING_CIRCUMFERENCE = 2 * Math.PI * 7

export function OpenClawContextUsageIndicator({ usage }: {
  usage: OpenClawContextUsage | null
}) {
  const progressValue = usage ? Math.min(100, usage.percent) : 0
  const label = usage ? `上下文占用 ${usage.percent}%` : '上下文占用暂无可信用量'
  return <Tooltip delay={250}>
    <TooltipTriggerButton
      aria-label={label}
      className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground"
    >
      <svg
        role="progressbar"
        aria-label="上下文占用"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={usage ? progressValue : undefined}
        aria-valuetext={usage ? `${usage.percent}%` : '暂无可信用量'}
        viewBox="0 0 20 20"
        className="size-5"
      >
        <circle cx="10" cy="10" r="7" fill="none" stroke="currentColor" strokeWidth="2" className="text-border" />
        {usage && <circle
          cx="10"
          cy="10"
          r="7"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray={CONTEXT_RING_CIRCUMFERENCE}
          strokeDashoffset={CONTEXT_RING_CIRCUMFERENCE * (1 - progressValue / 100)}
          transform="rotate(-90 10 10)"
          className="text-accent"
        />}
      </svg>
    </TooltipTriggerButton>
    <Tooltip.Content placement="top" offset={8}>
      {usage
        ? `${contextTokenFormatter.format(usage.usedTokens)} / ${contextTokenFormatter.format(usage.contextTokens)} · ${usage.percent}%`
        : '暂无可信用量'}
    </Tooltip.Content>
  </Tooltip>
}

function padTimePart(value: number): string {
  return String(value).padStart(2, '0')
}

function formatOpenClawMessageTime(
  value: number | undefined | null,
  now = Date.now(),
): FormattedMessageTime | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const date = new Date(value)
  const current = new Date(now)
  if (!Number.isFinite(date.getTime()) || !Number.isFinite(current.getTime())) return null
  const clock = `${padTimePart(date.getHours())}:${padTimePart(date.getMinutes())}`
  const today = date.getFullYear() === current.getFullYear()
    && date.getMonth() === current.getMonth()
    && date.getDate() === current.getDate()
  const fullDate = `${date.getFullYear()}-${padTimePart(date.getMonth() + 1)}-${padTimePart(date.getDate())}`
  return {
    label: today ? clock : `${padTimePart(date.getMonth() + 1)}-${padTimePart(date.getDate())} ${clock}`,
    title: `${fullDate} ${clock}:${padTimePart(date.getSeconds())}`,
    dateTime: date.toISOString(),
  }
}

const OPENCLAW_LINK_PATTERN = /\[([^\]\r\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<]+)/giu
const BARE_LINK_TRAILING_PUNCTUATION = /[.,!?;:，。！？；：、)\]}"']$/u

function safeHttpUrl(value: string): string | null {
  try {
    const parsed = new URL(value)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? value : null
  } catch {
    return null
  }
}

function trimBareLink(value: string): { href: string; trailing: string } {
  let href = value
  let trailing = ''
  while (href && BARE_LINK_TRAILING_PUNCTUATION.test(href.at(-1) ?? '')) {
    trailing = `${href.at(-1)}${trailing}`
    href = href.slice(0, -1)
  }
  return { href, trailing }
}

function OpenClawMessageText({ text }: { text: string }) {
  const nodes: ReactNode[] = []
  let cursor = 0
  for (const match of text.matchAll(OPENCLAW_LINK_PATTERN)) {
    const index = match.index ?? 0
    if (index > cursor) nodes.push(text.slice(cursor, index))
    const markdownLabel = match[1]
    const markdownUrl = match[2]
    const bareCandidate = match[3]
    const bare = bareCandidate ? trimBareLink(bareCandidate) : null
    const href = safeHttpUrl(markdownUrl ?? bare?.href ?? '')
    if (!href) {
      nodes.push(match[0])
    } else {
      nodes.push(<a
        key={`${index}-${href}`}
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-accent underline decoration-accent/50 underline-offset-[3px]"
      >{markdownLabel ?? bare?.href}</a>)
      if (bare?.trailing) nodes.push(bare.trailing)
    }
    cursor = index + match[0].length
  }
  if (cursor < text.length) nodes.push(text.slice(cursor))
  return <>{nodes}</>
}

function MessageTimestamp({ value }: { value?: number | null }) {
  const formatted = formatOpenClawMessageTime(value)
  if (!formatted) return null
  return <time
    className="type-label text-muted"
    dateTime={formatted.dateTime}
    title={formatted.title}
    aria-label={formatted.title}
  >{formatted.label}</time>
}

function ConversationTurn({
  role,
  text,
  createdAt,
  status,
  hasNext,
  children,
}: {
  role: 'user' | 'assistant'
  text: string
  createdAt?: number | null
  status?: string
  hasNext: boolean
  children?: ReactNode
}) {
  return <>
    <div data-chat-marker className="flex min-h-full flex-col items-center self-stretch" aria-hidden="true">
      <span className={`mt-1.5 size-[5px] shrink-0 rounded-full ${role === 'assistant' ? 'bg-accent' : 'bg-muted'}`} />
      {hasNext && <span className="mt-[5px] min-h-8 w-px flex-1 bg-separator" />}
    </div>
    <article
      className={`min-w-0 max-w-full ${hasNext ? 'pb-4' : ''}`}
      data-chat-role={role}
      data-chat-status={status}
    >
      <div className="mb-[5px] flex min-w-0 items-baseline gap-1.5">
        <span className={`type-label ${role === 'assistant' ? 'text-accent' : 'text-muted'}`}>
          {role === 'assistant' ? 'OpenClaw' : '你'}
        </span>
        <MessageTimestamp value={createdAt} />
      </div>
      <div
        data-chat-message-body
        className="type-chat min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
      >
        <OpenClawMessageText text={text} />
      </div>
      {children}
    </article>
  </>
}

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

const AUTO_THINKING_KEY = '__auto__'

function groupModelsByProvider(models: OpenClawModelOption[]) {
  const groups: Array<{ provider: string; models: OpenClawModelOption[] }> = []
  const byProvider = new Map<string, OpenClawModelOption[]>()
  for (const model of models) {
    const existing = byProvider.get(model.provider)
    if (existing) {
      existing.push(model)
      continue
    }
    const providerModels = [model]
    byProvider.set(model.provider, providerModels)
    groups.push({ provider: model.provider, models: providerModels })
  }
  return groups
}

function RuntimeControls({ chat }: { chat: ChatController }) {
  const thinkingDescriptionId = useId()
  const currentModel = chat.models.find((model) => model.id === chat.runtimeSelection.modelId)
  const currentThinking = chat.thinkingOptions.find((option) => option.id === chat.runtimeSelection.thinkingLevel)
  const modelGroups = useMemo(() => groupModelsByProvider(chat.models), [chat.models])
  const controlsDisabled = chat.isRunning || chat.runtimeUpdating || chat.runtimeLoading
  const modelDisabled = controlsDisabled || !chat.models.length
  const thinkingUnavailableReason = !currentModel
    ? '尚未取得当前模型信息。'
    : currentModel.reasoning === false
      ? '此模型未提供推理档位。'
      : !chat.thinkingOptions.length
        ? 'OpenClaw 未返回此模型的可选推理档位。'
        : ''
  const thinkingDisabled = controlsDisabled || Boolean(thinkingUnavailableReason)
  const modelLabel = currentModel?.name ?? (chat.runtimeLoading ? '正在读取模型…' : 'OpenClaw 当前设置')
  const thinkingLabel = currentThinking?.label ?? '自动'
  const thinkingItems: Array<{ id: string; label: string; description?: string }> = [
    {
      id: AUTO_THINKING_KEY,
      label: '自动',
      description: thinkingUnavailableReason || '使用 OpenClaw 默认设置',
    },
    ...(thinkingUnavailableReason
      ? []
      : chat.thinkingOptions.map((option) => ({ ...option, description: undefined }))),
  ]

  return <div
    data-testid="openclaw-runtime-controls"
    className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-0.5 overflow-hidden"
  >
    <OpenClawContextUsageIndicator usage={chat.contextUsage} />

    <Select
      aria-label={`OpenClaw 模型：${modelLabel}`}
      selectedKey={chat.runtimeSelection.modelId ?? undefined}
      onSelectionChange={(key: Key | null) => {
        if (key === null || String(key) === chat.runtimeSelection.modelId) return
        void chat.setModel(String(key))
      }}
      isDisabled={modelDisabled}
      className="min-w-0 overflow-hidden"
    >
      <Select.Trigger
        aria-label={`OpenClaw 模型：${modelLabel}`}
        className={`type-control flex min-h-8 w-full min-w-0 max-w-full items-center gap-1 overflow-hidden rounded-lg border-0 bg-transparent px-1.5 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${modelDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
      >
        <span className="min-w-0 truncate">{modelLabel}</span>
        <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
      </Select.Trigger>
      <Select.Popover placement="top start" offset={8} className="z-50 w-[min(320px,calc(100vw-24px))]">
        <ListBox aria-label="OpenClaw 模型">
          {modelGroups.map((group) => <ListBox.Section key={group.provider} id={`provider:${group.provider}`}>
            <Header className="type-label px-2 py-1.5 text-muted">{group.provider}</Header>
            {group.models.map((model) => <ListBox.Item
              key={model.id}
              id={model.id}
              textValue={`${model.provider} ${model.name}`}
              className="grid min-w-0 grid-cols-[minmax(0,1fr)_16px] items-center gap-2"
            >
              <span className="min-w-0">
                <span className="type-control block min-w-0 truncate">{model.name}</span>
                {formatContextWindow(model.contextWindow) && <span className="type-meta block min-w-0 truncate text-muted">{formatContextWindow(model.contextWindow)}</span>}
              </span>
              <ListBox.ItemIndicator className="text-accent" />
            </ListBox.Item>)}
          </ListBox.Section>)}
        </ListBox>
      </Select.Popover>
    </Select>

    <div className="shrink-0" title={thinkingUnavailableReason || undefined}>
      <Select
        aria-label={`OpenClaw 思考程度：${thinkingLabel}`}
        selectedKey={chat.runtimeSelection.thinkingLevel ?? AUTO_THINKING_KEY}
        onSelectionChange={(key: Key | null) => {
          if (key === null) return
          const next = String(key) === AUTO_THINKING_KEY ? null : String(key)
          if (next === chat.runtimeSelection.thinkingLevel) return
          void chat.setThinking(next)
        }}
        isDisabled={thinkingDisabled}
        className="min-w-0"
      >
        <Select.Trigger
          aria-label={`OpenClaw 思考程度：${thinkingLabel}`}
          aria-describedby={thinkingUnavailableReason ? thinkingDescriptionId : undefined}
          className={`type-control flex min-h-8 shrink-0 items-center gap-1 rounded-lg border-0 bg-transparent px-1.5 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${thinkingDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
        >
          <span>{thinkingLabel}</span>
          <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
        </Select.Trigger>
        <Select.Popover placement="top end" offset={8} className="z-50 w-[min(220px,calc(100vw-24px))]">
          <ListBox items={thinkingItems} aria-label="OpenClaw 思考程度">
            {(option) => <ListBox.Item id={option.id} textValue={option.label} className="grid min-w-0 grid-cols-[minmax(0,1fr)_16px] items-center gap-2">
              <span className="min-w-0">
                <span className="type-control block">{option.label}</span>
                {option.description && <span className="type-meta block text-muted">{option.description}</span>}
              </span>
              <ListBox.ItemIndicator className="text-accent" />
            </ListBox.Item>}
          </ListBox>
        </Select.Popover>
      </Select>
      {thinkingUnavailableReason && <span id={thinkingDescriptionId} className="sr-only">{thinkingUnavailableReason}</span>}
    </div>
  </div>
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
      className="quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto px-[15px] pb-4 pt-[13px]"
      data-testid="agent-scroll-region"
      aria-live="polite"
      onScroll={(event) => {
        const region = event.currentTarget
        followRef.current = region.scrollHeight - region.scrollTop - region.clientHeight <= 96
      }}
    >
      <div className="mb-4 flex min-w-0 items-center justify-between gap-2">
        <span className="type-meta min-w-0 truncate text-muted">{chat.sessionKey ? 'Inteliscope 对话' : '正在准备对话'}</span>
        <div className="flex shrink-0 gap-1"><Button size="sm" variant="ghost" isDisabled={chat.isRunning || chat.runtimeUpdating} onPress={() => void chat.newConversation()}><Icons.Plus size={14} />新对话</Button><Button size="sm" variant="ghost" onPress={chat.disconnect}>断开</Button></div>
      </div>
      {chat.toolsStatus === 'missing' && <Card variant="secondary" className="mb-3 min-w-0 border-warning/40 p-3" role="status"><Card.Title>未发现 Inteliscope 工具</Card.Title><Card.Description className="mt-1">OpenClaw 已连接，但还需要在助手连接页面配置 Remote MCP 与 Skill。</Card.Description><a className="type-control mt-2 inline-flex text-accent" href="/agents">打开助手连接</a></Card>}
      {!chat.messages.length && !chat.streamText && <Card variant="transparent" className="min-w-0 p-4 text-center"><Card.Description>可以分析已选文章，也可以直接询问来源异常、任务失败或订阅配置。</Card.Description></Card>}
      <div
        data-testid="openclaw-timeline"
        className="grid min-w-0 grid-cols-[12px_minmax(0,1fr)] gap-x-[9px] overflow-x-hidden"
      >
        {chat.messages.map((message, index) => <ConversationTurn
          key={message.id}
          role={message.role}
          text={message.text}
          createdAt={message.createdAt}
          status={message.status}
          hasNext={index < chat.messages.length - 1 || Boolean(chat.streamText)}
        >
          {Boolean(message.contextCount) && <div className="type-label mt-1.5 text-muted">附带 {message.contextCount} 条信息</div>}
          {message.status === 'aborted' && <div className="type-label mt-1.5 text-muted">已停止</div>}
          {message.status === 'failed' && message.role === 'user' && <div className="mt-1.5 flex flex-wrap gap-1">
            <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => void chat.retry(message.id)}>重试</Button>
            <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => editFailed(message.id)}>重新编辑</Button>
          </div>}
        </ConversationTurn>)}
        {chat.streamText && <ConversationTurn
          role="assistant"
          text={chat.streamText}
          createdAt={chat.streamCreatedAt}
          hasNext={false}
        />}
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
          <Tooltip delay={250}>
            <TooltipTriggerButton
              aria-label={chat.isRunning ? '停止生成' : '发送给 OpenClaw'}
              disabled={chat.isRunning ? chat.isStopping : !canSend || chat.status !== 'connected'}
              onClick={chat.isRunning ? () => void chat.stop() : () => void send()}
              className="size-9 shrink-0 rounded-full bg-accent text-accent-foreground hover:bg-accent-hover"
            >{chat.isRunning
              ? <Icons.Square size={14} fill="currentColor" aria-hidden="true" />
              : <Icons.ArrowUp size={16} aria-hidden="true" />}
            </TooltipTriggerButton>
            <Tooltip.Content {...anchoredTooltipProps}>{chat.isRunning ? (chat.isStopping ? '正在停止…' : '停止生成') : '发送给 OpenClaw'}</Tooltip.Content>
          </Tooltip>
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
