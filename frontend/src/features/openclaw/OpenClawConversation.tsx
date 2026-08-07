import { useEffect, useId, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type Key, type ReactNode } from 'react'

import {
  anchoredTooltipProps,
  Button,
  Card,
  ChatSource,
  ChatSources,
  Form,
  Header,
  ImageGalleryModal,
  Icons,
  Input,
  Label,
  ListBox,
  PromptInput,
  PromptInputBody,
  PromptInputToolbar,
  Select,
  StatusIndicator,
  TextArea,
  TextField,
  Tooltip,
  TooltipTriggerButton,
} from '../../design-system'
import { buildAgentHandoffPrompt, type AgentContextItem } from '../workbench-live/agentContext'
import { HandoffComposer } from '../workbench-live/HandoffComposer'
import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'
import type { useOpenClawChat } from './useOpenClawChat'
import type {
  OpenClawContextUsage,
  OpenClawModelOption,
  OpenClawRunActivity,
  OpenClawRunPhase,
  OpenClawRunTrace,
} from './useOpenClawChat'
import {
  OPENCLAW_MAX_IMAGES_PER_TURN,
  OPENCLAW_MAX_TOTAL_IMAGE_BYTES,
  normalizeOpenClawImage,
  releaseOpenClawImageAttachment,
  type OpenClawImageAttachment,
  type OpenClawMessageImage,
} from './openclawMedia'

type ChatController = ReturnType<typeof useOpenClawChat>

type FormattedMessageTime = {
  label: string
  title: string
  dateTime: string
}

const CONTEXT_RING_CIRCUMFERENCE = 2 * Math.PI * 7

function formatTokenK(value: number): string {
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value / 1000)}k`
}

export function OpenClawContextUsageIndicator({ usage }: {
  usage: OpenClawContextUsage | null
}) {
  const progressValue = usage ? Math.min(100, usage.percent) : 0
  const label = usage
    ? `上下文占用 ${formatTokenK(usage.usedTokens)} / ${formatTokenK(usage.contextTokens)}，${usage.percent}%`
    : '上下文占用暂无可信用量'
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
        ? `${formatTokenK(usage.usedTokens)} / ${formatTokenK(usage.contextTokens)} · ${usage.percent}%`
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
      {text && <div
          data-chat-message-body
          className="type-chat min-w-0 max-w-full whitespace-pre-wrap break-words [overflow-wrap:anywhere]"
        >
          <OpenClawMessageText text={text} />
        </div>}
      {children}
    </article>
  </>
}

type OpenClawImageViewerState = {
  label: string
  images: OpenClawMessageImage[]
  index: number
  messageId?: string
}

function OpenClawImageGrid({
  images,
  role,
  messageId,
  onOpen,
  onRefresh,
}: {
  images: OpenClawMessageImage[]
  role: 'user' | 'assistant'
  messageId?: string
  onOpen: (index: number) => void
  onRefresh?: (imageId: string) => void
}) {
  if (!images.length) return null
  const label = role === 'assistant' ? 'OpenClaw 返回的图片' : '你发送的图片'
  return <div className="mt-2 grid max-w-[520px] grid-cols-2 gap-2" role="group" aria-label={label}>
    {images.slice(0, 4).map((image, index) => image.url ? <button
      key={image.id}
      type="button"
      className={`relative min-w-0 overflow-hidden rounded-xl border border-separator bg-default/60 text-left outline-none focus-visible:outline-2 focus-visible:outline-focus ${images.length === 1 ? 'col-span-2 max-h-[320px]' : 'aspect-[4/3]'}`}
      aria-label={`查看${label}第 ${index + 1} 张`}
      onClick={() => onOpen(index)}
    >
      <img
        src={image.url}
        alt={image.alt || `${label}第 ${index + 1} 张`}
        width={image.width}
        height={image.height}
        referrerPolicy="no-referrer"
        className="size-full object-cover"
        onError={() => messageId && onRefresh?.(image.id)}
      />
      {index === 3 && images.length > 4 && <span className="type-control absolute inset-0 grid place-items-center bg-background/70 text-foreground">+{images.length - 4}</span>}
    </button> : <div
      key={image.id}
      className={`grid min-w-0 place-items-center rounded-xl border border-separator bg-default/60 p-3 text-center ${images.length === 1 ? 'col-span-2 min-h-32' : 'aspect-[4/3]'}`}
    >
      <div>
        <Icons.ImageOff size={18} className="mx-auto text-muted" aria-hidden="true" />
        <p className="type-label mt-1 text-muted">图片暂不可用</p>
        {messageId && onRefresh && <Button size="sm" variant="ghost" className="mt-1" onPress={() => onRefresh(image.id)}>重试</Button>}
      </div>
    </div>)}
  </div>
}

const runPhaseLabels: Record<OpenClawRunPhase, string> = {
  sending: '正在发送请求',
  waiting: '等待 OpenClaw 响应',
  thinking: '正在思考',
  using_tool: '正在使用工具',
  composing: '正在整理回答',
  streaming: '正在生成回答',
  stopping: '正在停止',
  completed: '处理完成',
  aborted: '已停止',
  failed: '处理失败',
}

const QUICK_ACTIVITY_THRESHOLD_MS = 400

function activityLabel(activity: OpenClawRunActivity): string {
  if (activity.status === 'running') return `正在${activity.label}`
  if (activity.status === 'failed') return `${activity.label}失败`
  if (activity.status === 'stopped') return `${activity.label}已停止`
  return `已${activity.label}`
}

function ActivityIcon({ activity }: { activity: OpenClawRunActivity }) {
  if (activity.status === 'running') return <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
  if (activity.status === 'failed') return <Icons.CircleX size={13} aria-hidden="true" />
  if (activity.status === 'stopped') return <Icons.Square size={11} aria-hidden="true" />
  return <Icons.Check size={13} aria-hidden="true" />
}

export function OpenClawActivityTrace({ trace, running }: {
  trace: OpenClawRunTrace
  running: boolean
}) {
  const [expandedOverride, setExpandedOverride] = useState<boolean | null>(null)
  const [now, setNow] = useState(trace.startedAt)
  const expanded = expandedOverride ?? running

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 400)
    return () => window.clearInterval(timer)
  }, [running])

  const endedAt = trace.endedAt ?? now
  const elapsedSeconds = Math.max(0, Math.floor((endedAt - trace.startedAt) / 1000))
  const activeTool = [...trace.activities].reverse().find((activity) => activity.status === 'running')
  const activeToolVisible = Boolean(activeTool && now - activeTool.startedAt >= QUICK_ACTIVITY_THRESHOLD_MS)
  const phaseLabel = trace.phase === 'using_tool' && activeTool && activeToolVisible
    ? `正在${activeTool.label}`
    : runPhaseLabels[trace.phase]
  const summary = trace.status === 'completed'
    ? `已完成 ${trace.activities.length} 个步骤`
    : trace.status === 'aborted'
      ? trace.activities.length ? `已停止 · 完成 ${trace.activities.filter((activity) => activity.status === 'completed').length} 个步骤` : '已停止，未生成回答'
      : trace.status === 'failed'
        ? '处理失败'
        : phaseLabel
  const quickCompletedCount = trace.activities.filter((activity) => (
    activity.id !== 'context'
    &&
    activity.status === 'completed'
    && activity.endedAt !== undefined
    && activity.endedAt - activity.startedAt < QUICK_ACTIVITY_THRESHOLD_MS
  )).length
  const detailedActivities = trace.activities.filter((activity) => {
    if (activity.id === 'context') return true
    if (activity.status === 'running') return now - activity.startedAt >= QUICK_ACTIVITY_THRESHOLD_MS
    if (activity.status !== 'completed' || activity.endedAt === undefined) return true
    return activity.endedAt - activity.startedAt >= QUICK_ACTIVITY_THRESHOLD_MS
  })
  const maxDetailedActivities = quickCompletedCount > 0 ? 2 : 3
  const visibleActivities = detailedActivities.slice(-maxDetailedActivities)
  const hiddenCount = Math.max(0, detailedActivities.length - visibleActivities.length)
  const tone = trace.status === 'failed' ? 'danger' : trace.status === 'aborted' ? 'neutral' : running ? 'accent' : 'success'

  return <div data-openclaw-activity data-run-status={trace.status} className="mt-2 min-w-0 rounded-xl border border-separator bg-default/45 px-2.5 py-2">
    <button
      type="button"
      className="flex min-h-7 w-full min-w-0 items-center gap-2 rounded-lg text-left focus-visible:outline-2 focus-visible:outline-focus"
      aria-expanded={expanded}
      onClick={() => setExpandedOverride(!expanded)}
    >
      <StatusIndicator
        label={summary}
        tone={tone}
        icon={running
          ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          : trace.status === 'failed'
            ? <Icons.CircleX size={13} aria-hidden="true" />
            : trace.status === 'aborted'
              ? <Icons.Square size={11} aria-hidden="true" />
              : <Icons.Check size={13} aria-hidden="true" />}
        className="min-w-0 flex-1"
      />
      <span aria-hidden="true" aria-live="off" className="type-meta shrink-0 tabular-nums text-muted">{elapsedSeconds}秒</span>
      <Icons.ChevronDown size={13} aria-hidden="true" className={`shrink-0 text-muted transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
    </button>
    <span className="sr-only" role="status">{phaseLabel}</span>
    {expanded && <div className="mt-1 grid gap-1 border-t border-separator pt-1.5">
      {hiddenCount > 0 && <span className="type-meta pl-5 text-muted">另有 {hiddenCount} 个较早步骤</span>}
      {quickCompletedCount > 0 && <div className="type-meta flex min-w-0 items-center gap-2 text-muted">
        <span className="grid size-3.5 shrink-0 place-items-center"><Icons.Check size={13} aria-hidden="true" /></span>
        <span className="min-w-0 truncate">已完成 {quickCompletedCount} 个快速步骤</span>
      </div>}
      {visibleActivities.length ? visibleActivities.map((activity) => <div
        key={activity.id}
        data-activity-status={activity.status}
        className={`type-meta flex min-w-0 items-center gap-2 ${activity.status === 'failed' ? 'text-danger' : activity.status === 'running' ? 'text-accent' : 'text-muted'}`}
      >
        <span className="grid size-3.5 shrink-0 place-items-center"><ActivityIcon activity={activity} /></span>
        <span className="min-w-0 truncate">{activityLabel(activity)}</span>
      </div>) : <span className="type-meta text-muted">{phaseLabel}</span>}
    </div>}
  </div>
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
  if (item.resourceType !== 'job' && item.sourceUrl) {
    return <div data-composer-context-item className="flex min-w-0">
      <ChatSource
        source={{ title: item.title, url: item.sourceUrl, sourceName: item.sourceName, sourceAvatarUrl: item.sourceAvatarUrl }}
        onRemove={onRemove}
        fullWidth
      />
    </div>
  }
  return <div data-composer-context-item className="flex h-8 min-w-0 items-center gap-2 rounded-lg bg-default px-2">
    <span className="type-label min-w-0 flex-1 truncate" title={label}>{label}</span>
    <Button size="sm" variant="ghost" isIconOnly className="size-7 shrink-0" aria-label={`移除 ${label}`} onPress={onRemove}>
      <Icons.X size={13} aria-hidden="true" />
    </Button>
  </div>
}

function ContextSummary({ value }: { value: WorkbenchAgentContextValue }) {
  const count = value.draft.items.length
  const hiddenItems = value.draft.items.slice(2)
  const hiddenItemsKey = hiddenItems.map((item) => item.articleId).join(':')
  const [expandedItemsKey, setExpandedItemsKey] = useState<string | null>(null)
  const expanded = Boolean(hiddenItems.length) && expandedItemsKey === hiddenItemsKey
  const hiddenItemsId = useId()

  if (!count) return null
  return <div
    className="mb-2 min-w-0 rounded-xl border border-separator bg-surface-secondary p-2"
    aria-label={`已附带 ${count} 条信息`}
    data-context-summary-expanded={expanded ? 'true' : 'false'}
  >
    <div className="mb-1 flex min-w-0 items-center gap-1 px-1">
      {hiddenItems.length > 0
        ? <Tooltip delay={250}>
          <TooltipTriggerButton
            aria-label={expanded ? `收起剩余 ${hiddenItems.length} 条信息` : `向上展开剩余 ${hiddenItems.length} 条信息`}
            aria-controls={hiddenItemsId}
            aria-expanded={expanded}
            className="min-h-8 w-full min-w-0 justify-start gap-1.5 rounded-lg px-1.5 text-accent hover:bg-default pointer-coarse:min-h-11"
            onClick={() => setExpandedItemsKey((current) => current === hiddenItemsKey ? null : hiddenItemsKey)}
          >
            <span className="type-label min-w-0 truncate text-muted">已附带 {count} 条</span>
            <Icons.ChevronUp size={15} aria-hidden="true" className={`transition-transform duration-[var(--inteliscope-motion-deliberate)] motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
          </TooltipTriggerButton>
          <Tooltip.Content placement="top" offset={8}>
            {expanded ? `收起剩余 ${hiddenItems.length} 条信息` : `向上展开剩余 ${hiddenItems.length} 条信息`}
          </Tooltip.Content>
        </Tooltip>
        : <span className="type-label min-w-0 flex-1 text-muted">已附带 {count} 条</span>}
      <Tooltip delay={250}>
        <TooltipTriggerButton
          aria-label={`移除全部 ${count} 条信息`}
          className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11"
          onClick={() => {
            setExpandedItemsKey(null)
            value.clearItems()
          }}
        >
          <Icons.Trash2 size={14} aria-hidden="true" />
        </TooltipTriggerButton>
        <Tooltip.Content placement="top" offset={8}>移除全部 {count} 条信息</Tooltip.Content>
      </Tooltip>
    </div>
    <div className="grid min-w-0 gap-1">
      {value.draft.items.slice(0, 2).map((item) => <ContextRow key={item.articleId} item={item} onRemove={() => value.removeItem(item.articleId)} />)}
    </div>
    {hiddenItems.length > 0 && <div
      id={hiddenItemsId}
      aria-hidden={!expanded}
      inert={!expanded}
      className={`grid min-w-0 transition-[grid-template-rows,opacity] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none ${expanded ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}
    >
      <div className="min-h-0 overflow-hidden">
        <div className="grid max-h-[min(520px,70dvh)] min-w-0 gap-1 overflow-x-hidden overflow-y-auto pt-1">
          {hiddenItems.map((item) => <ContextRow key={item.articleId} item={item} onRemove={() => value.removeItem(item.articleId)} />)}
        </div>
      </div>
    </div>}
  </div>
}

function formatContextWindow(value?: number): string {
  if (!value) return ''
  if (value >= 1_000_000) return `${Math.round(value / 100_000) / 10}M 上下文`
  if (value >= 1000) return `${Math.round(value / 1000)}k 上下文`
  return `${value} 上下文`
}

function formatModelThinking(model: OpenClawModelOption): string {
  if (model.reasoning === false) return '不支持思考档位'
  if (model.thinkingLevels?.length) return `思考：${model.thinkingLevels.map((option) => option.label).join('、')}`
  return ''
}

function formatModelCapabilities(model: OpenClawModelOption): string {
  return [formatContextWindow(model.contextWindow), model.supportsImages ? '支持图片' : '', formatModelThinking(model)].filter(Boolean).join(' · ')
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
    className="flex min-w-0 items-center gap-1 overflow-hidden"
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
      className="w-fit min-w-0 max-w-[180px] shrink overflow-hidden"
    >
      <Select.Trigger
        aria-label={`OpenClaw 模型：${modelLabel}`}
        className={`type-control flex min-h-8 w-fit min-w-0 max-w-[180px] items-center gap-1 overflow-hidden rounded-lg border-0 bg-default/80 px-2 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${modelDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
      >
        <span className="min-w-0 flex-1 truncate">{modelLabel}</span>
        <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
      </Select.Trigger>
      <Select.Popover placement="top start" offset={8} className="z-50 max-h-[min(360px,calc(100dvh-24px))] w-[min(280px,calc(100vw-24px))] overflow-hidden">
        <ListBox aria-label="OpenClaw 模型" className="max-h-[min(360px,calc(100dvh-24px))] overflow-y-auto overscroll-contain">
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
                {formatModelCapabilities(model) && <span className="type-meta block min-w-0 truncate text-muted">
                  {formatModelCapabilities(model)}
                </span>}
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
          className={`type-control flex min-h-8 shrink-0 items-center gap-1 rounded-lg border-0 bg-default/80 px-2 shadow-none focus-visible:outline-2 focus-visible:outline-focus ${thinkingDisabled ? 'text-muted' : 'text-foreground hover:bg-default'}`}
        >
          <span>{thinkingLabel}</span>
          <Select.Indicator><Icons.ChevronDown size={12} className="shrink-0 text-muted" aria-hidden="true" /></Select.Indicator>
        </Select.Trigger>
        <Select.Popover placement="top end" offset={8} className="z-50 w-[min(220px,calc(100vw-24px))]">
          <ListBox aria-label="OpenClaw 思考程度">
            <ListBox.Section id="thinking-options">
              <Header className="type-label px-2 py-1.5 text-muted">
                {currentModel ? `${currentModel.provider} · ${currentModel.name}` : '当前模型'}
              </Header>
              {thinkingItems.map((option) => <ListBox.Item key={option.id} id={option.id} textValue={option.label} className="grid min-w-0 grid-cols-[minmax(0,1fr)_16px] items-center gap-2">
                <span className="min-w-0">
                  <span className="type-control block">{option.label}</span>
                  {option.description && <span className="type-meta block text-muted">{option.description}</span>}
                </span>
                <ListBox.ItemIndicator className="text-accent" />
              </ListBox.Item>)}
            </ListBox.Section>
          </ListBox>
        </Select.Popover>
      </Select>
      {thinkingUnavailableReason && <span id={thinkingDescriptionId} className="sr-only">{thinkingUnavailableReason}</span>}
    </div>
  </div>
}

function ConnectedConversation({ chat, value }: { chat: ChatController; value: WorkbenchAgentContextValue }) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const composingRef = useRef(false)
  const followRef = useRef(true)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const draftAttachmentsRef = useRef<OpenClawImageAttachment[]>([])
  const [newOutputBelow, setNewOutputBelow] = useState(false)
  const [attachments, setAttachments] = useState<OpenClawImageAttachment[]>([])
  const [attachmentIssue, setAttachmentIssue] = useState<string | null>(null)
  const [viewer, setViewer] = useState<OpenClawImageViewerState | null>(null)
  const attachmentModelBlocked = Boolean(attachments.length && !chat.currentModelSupportsImages)
  const canSend = Boolean(value.draft.question.trim() || value.draft.items.length || attachments.length) && !attachmentModelBlocked
  const runTrace = chat.runTrace
  const outputVersion = `${chat.messages.length}:${chat.streamText.length}:${runTrace?.phase ?? ''}:${runTrace?.activities.map((activity) => activity.status).join(',') ?? ''}`
  const attachTerminalTrace = Boolean(
    runTrace
    && !chat.isRunning
    && !chat.streamText
    && chat.messages.at(-1)?.role === 'assistant',
  )
  const showStandaloneTrace = Boolean(runTrace && !chat.streamText && !attachTerminalTrace)

  useEffect(() => {
    const region = scrollRef.current
    if (!region) return
    if (!followRef.current) {
      setNewOutputBelow(true)
      return
    }
    window.requestAnimationFrame(() => {
      region.scrollTop = region.scrollHeight
      setNewOutputBelow(false)
    })
  }, [outputVersion])

  useEffect(() => {
    draftAttachmentsRef.current = attachments
  }, [attachments])

  useEffect(() => () => {
    draftAttachmentsRef.current.forEach(releaseOpenClawImageAttachment)
  }, [])

  async function appendImageFiles(files: File[]) {
    if (!files.length || !chat.imageInputAvailable) return
    let next = [...attachments]
    const errors: string[] = []
    for (const file of files) {
      if (next.length >= OPENCLAW_MAX_IMAGES_PER_TURN) {
        errors.push(`每次最多添加 ${OPENCLAW_MAX_IMAGES_PER_TURN} 张图片。`)
        break
      }
      try {
        const image = await normalizeOpenClawImage(file, next.length + 1)
        if (next.reduce((total, candidate) => total + candidate.byteLength, 0) + image.byteLength > OPENCLAW_MAX_TOTAL_IMAGE_BYTES) {
          releaseOpenClawImageAttachment(image)
          errors.push('本次图片总大小超过 12 MiB 限制。')
          continue
        }
        next = [...next, image]
      } catch (error) {
        errors.push(error instanceof Error ? error.message : '无法添加图片。')
      }
    }
    setAttachments(next)
    setAttachmentIssue(errors[0] ?? null)
  }

  function onImageInput(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    void appendImageFiles(files)
  }

  function removeAttachment(id: string) {
    setAttachments((current) => {
      const removed = current.find((attachment) => attachment.id === id)
      if (removed) releaseOpenClawImageAttachment(removed)
      return current.filter((attachment) => attachment.id !== id)
    })
    setAttachmentIssue(null)
  }

  function openImages(label: string, images: OpenClawMessageImage[], index: number, messageId?: string) {
    const selectedId = images[index]?.id
    const availableImages = images.filter((image) => Boolean(image.url))
    const availableIndex = availableImages.findIndex((image) => image.id === selectedId)
    if (!availableImages.length) return
    setViewer({ label, images: availableImages, index: Math.max(availableIndex, 0), messageId })
  }

  function scrollToLatest() {
    const region = scrollRef.current
    if (!region) return
    followRef.current = true
    region.scrollTop = region.scrollHeight
    setNewOutputBelow(false)
  }

  function fillSuggestion(question: string) {
    value.setQuestion(question)
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>('[aria-label="发送给 OpenClaw 的问题"]')?.focus())
  }

  async function send() {
    if (!canSend || chat.isRunning) return
    const draft = {
      ...value.draft,
      items: value.draft.items.map((item) => ({ ...item })),
    }
    const displayText = draft.question.trim() || (draft.items.length ? `分析已附带的 ${draft.items.length} 条信息` : '')
    const sent = await chat.send({
      displayText,
      gatewayPrompt: buildAgentHandoffPrompt(draft, { imageCount: attachments.length }),
      contextItems: draft.items,
      attachments,
    })
    if (sent) {
      value.clearComposer()
      setAttachments([])
      setAttachmentIssue(null)
    }
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
      className="quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-[15px] pb-4 pt-[13px]"
      data-testid="agent-scroll-region"
      aria-live="polite"
      onScroll={(event) => {
        const region = event.currentTarget
        followRef.current = region.scrollHeight - region.scrollTop - region.clientHeight <= 96
        if (followRef.current) setNewOutputBelow(false)
      }}
    >
      <div className="mb-4 flex min-w-0 items-center justify-between gap-2">
        <span className="type-meta min-w-0 truncate text-muted">{chat.sessionKey ? 'Inteliscope 对话' : '正在准备对话'}</span>
        <div className="flex shrink-0 gap-1"><Button size="sm" variant="ghost" isDisabled={chat.isRunning || chat.runtimeUpdating} onPress={() => void chat.newConversation()}><Icons.Plus size={14} />新对话</Button><Button size="sm" variant="ghost" onPress={chat.disconnect}>断开</Button></div>
      </div>
      {chat.toolsStatus === 'missing' && <Card variant="secondary" className="mb-3 min-w-0 border-warning/40 p-3" role="status"><Card.Title>未发现 Inteliscope 工具</Card.Title><Card.Description className="mt-1">OpenClaw 已连接，但还需要在助手连接页面配置 Remote MCP 与 Skill。</Card.Description><a className="type-control mt-2 inline-flex text-accent" href="/agents">打开助手连接</a></Card>}
      {!chat.messages.length && !chat.streamText && !runTrace && <Card variant="transparent" className="min-w-0 p-4 text-center">
        <Card.Description>可以分析已选文章，也可以直接询问来源异常、任务失败或订阅配置。</Card.Description>
        <div className="mt-3 flex flex-wrap justify-center gap-1.5" aria-label="问题建议">
          {(value.draft.items.length
            ? ['总结这些内容', '比较关键信号', '提炼行动线索']
            : ['诊断最近失败任务', '查看异常来源', '我有哪些订阅']
          ).map((suggestion) => <Button key={suggestion} size="sm" variant="ghost" onPress={() => fillSuggestion(suggestion)}>{suggestion}</Button>)}
        </div>
      </Card>}
      <div
        data-testid="openclaw-timeline"
        className="grid min-w-0 grid-cols-[12px_minmax(0,1fr)] gap-x-[9px] overflow-x-hidden"
      >
        {chat.messages.map((message, index) => {
          const traceAttached = attachTerminalTrace && index === chat.messages.length - 1
          const contextSources = message.contextSources ?? []
          const remainingContextCount = Math.max(0, (message.contextCount ?? 0) - contextSources.length)
          return <ConversationTurn
            key={message.id}
            role={message.role}
            text={message.text}
            createdAt={message.createdAt}
            status={message.status}
            hasNext={index < chat.messages.length - 1 || Boolean(chat.streamText) || showStandaloneTrace}
          >
            {Boolean(contextSources.length) && <ChatSources className="mt-2" label="本条消息引用的来源">
              {contextSources.map((source, sourceIndex) => <ChatSource key={`${source.url}:${sourceIndex}`} source={source} compact />)}
            </ChatSources>}
            {Boolean(remainingContextCount) && <div className="type-label mt-1.5 text-muted">
              另附 {remainingContextCount} 条任务信息
            </div>}
            {Boolean(message.images?.length) && <OpenClawImageGrid
              images={message.images ?? []}
              role={message.role}
              messageId={message.id}
              onOpen={(imageIndex) => openImages(message.role === 'assistant' ? 'OpenClaw 返回的图片' : '你发送的图片', message.images ?? [], imageIndex, message.id)}
              onRefresh={(imageId) => { void chat.refreshMedia(message.id, imageId) }}
            />}
            {message.status === 'aborted' && <div className="type-label mt-1.5 text-muted">已停止</div>}
            {message.status === 'failed' && message.role === 'user' && <div className="mt-1.5 flex flex-wrap gap-1">
              <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => void chat.retry(message.id)}>重试</Button>
              <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => editFailed(message.id)}>重新编辑</Button>
            </div>}
            {traceAttached && runTrace && <OpenClawActivityTrace key={runTrace.runId ?? runTrace.startedAt} trace={runTrace} running={false} />}
          </ConversationTurn>
        })}
        {chat.streamText && <ConversationTurn
          role="assistant"
          text={chat.streamText}
          createdAt={chat.streamCreatedAt}
          hasNext={false}
        >{runTrace && <OpenClawActivityTrace key={runTrace.runId ?? runTrace.startedAt} trace={runTrace} running />}</ConversationTurn>}
        {showStandaloneTrace && runTrace && <ConversationTurn
          role="assistant"
          text=""
          createdAt={runTrace.startedAt}
          status={runTrace.status}
          hasNext={false}
        ><OpenClawActivityTrace key={runTrace.runId ?? runTrace.startedAt} trace={runTrace} running={chat.isRunning} /></ConversationTurn>}
      </div>
      {newOutputBelow && <Button
        size="sm"
        variant="secondary"
        className="sticky bottom-2 z-10 ml-auto mt-2 shadow-md"
        onPress={scrollToLatest}
      >有新回复 <Icons.ArrowDown size={14} aria-hidden="true" /></Button>}
      {chat.issue && <p role="alert" className="type-body mt-3 max-w-full break-words text-danger [overflow-wrap:anywhere]">{chat.issue.message}</p>}
    </div>
    <ImageGalleryModal
      isOpen={Boolean(viewer)}
      heading={viewer?.label ?? '图片预览'}
      images={(viewer?.images ?? []).flatMap((image) => image.url ? [{
        id: image.id,
        url: image.url,
        alt: image.alt,
        width: image.width,
        height: image.height,
      }] : [])}
      index={viewer?.index ?? 0}
      onIndexChange={(index) => setViewer((current) => current ? { ...current, index } : current)}
      onOpenChange={(open) => { if (!open) setViewer(null) }}
      onRefresh={(image) => {
        if (viewer?.messageId && image.id) void chat.refreshMedia(viewer.messageId, image.id)
      }}
    />
    <div data-testid="openclaw-composer-dock" className="min-w-0 shrink-0 overflow-hidden border-t border-separator p-3">
      {chat.status === 'reconnecting' && <div role="status" className="type-meta mb-2 flex min-w-0 items-center gap-2 rounded-lg bg-warning/10 px-2 py-1.5 text-warning">
        <Icons.WifiOff size={14} className="shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">连接中断，正在重连{chat.reconnectAttempt > 0 ? ` · 第 ${chat.reconnectAttempt} 次` : ''}</span>
        <Button size="sm" variant="ghost" onPress={chat.retryConnection}>立即重试</Button>
      </div>}
      <ContextSummary value={value} />
      <PromptInput
        data-testid="openclaw-composer"
        className="grid grid-rows-[minmax(64px,auto)_36px] gap-2 p-2"
        onDragOver={(event: DragEvent<HTMLDivElement>) => {
          if (!chat.imageInputAvailable || !Array.from(event.dataTransfer.types).includes('Files')) return
          event.preventDefault()
        }}
        onDrop={(event: DragEvent<HTMLDivElement>) => {
          if (!chat.imageInputAvailable) return
          event.preventDefault()
          void appendImageFiles(Array.from(event.dataTransfer.files))
        }}
      >
        <PromptInputBody className="grid gap-2">
          {attachments.length > 0 && <div className="flex flex-wrap gap-2" aria-label={`已添加 ${attachments.length} 张图片`}>
            {attachments.map((attachment, index) => <div key={attachment.id} className="relative size-14 overflow-hidden rounded-lg border border-separator bg-default">
              <button
                type="button"
                className="size-full outline-none focus-visible:outline-2 focus-visible:outline-focus"
                aria-label={`预览第 ${index + 1} 张图片`}
                onClick={() => openImages('待发送图片', attachments.map((image, imageIndex) => ({
                  id: image.id,
                  alt: `待发送第 ${imageIndex + 1} 张图片`,
                  mimeType: image.mimeType,
                  width: image.width,
                  height: image.height,
                  url: image.previewUrl,
                })), index)}
              ><img src={attachment.previewUrl} alt="" className="size-full object-cover" /></button>
              <button
                type="button"
                className="absolute right-0.5 top-0.5 inline-flex size-5 items-center justify-center rounded-full bg-background/90 text-foreground outline-none hover:bg-default focus-visible:outline-2 focus-visible:outline-focus"
                aria-label={`移除第 ${index + 1} 张图片`}
                onClick={() => removeAttachment(attachment.id)}
              ><Icons.X size={12} aria-hidden="true" /></button>
            </div>)}
          </div>}
          <TextArea
            fullWidth
            variant="secondary"
            className="type-body min-h-16 max-h-[160px] min-w-0 max-w-full resize-none overflow-y-auto overscroll-y-contain [field-sizing:content] [overflow-wrap:anywhere]"
            aria-label="发送给 OpenClaw 的问题"
            value={value.draft.question}
            maxLength={1200}
            rows={2}
            placeholder="分析文章，或询问来源和任务…"
            onChange={(event) => value.setQuestion(event.target.value)}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'))
              if (!files.length || !chat.imageInputAvailable) return
              event.preventDefault()
              void appendImageFiles(files)
            }}
            onCompositionStart={() => { composingRef.current = true }}
            onCompositionEnd={() => { composingRef.current = false }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                if (
                  composingRef.current
                  || event.nativeEvent.isComposing
                  || event.nativeEvent.keyCode === 229
                ) return
                event.preventDefault()
                void send()
              }
            }}
          />
        </PromptInputBody>
        <PromptInputToolbar data-testid="openclaw-composer-toolbar" className="grid grid-cols-[36px_minmax(0,1fr)_36px] px-1 pb-0.5">
          <Tooltip delay={250}>
            <TooltipTriggerButton
              aria-label="添加图片"
              disabled={!chat.imageInputAvailable || chat.isRunning || attachments.length >= OPENCLAW_MAX_IMAGES_PER_TURN}
              onClick={() => fileInputRef.current?.click()}
              className="size-9 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground"
            ><Icons.ImagePlus size={17} aria-hidden="true" /></TooltipTriggerButton>
            <Tooltip.Content {...anchoredTooltipProps}>{!chat.imageInputAvailable
              ? '图片输入尚未启用'
              : attachments.length >= OPENCLAW_MAX_IMAGES_PER_TURN
                ? `每次最多 ${OPENCLAW_MAX_IMAGES_PER_TURN} 张图片`
                : '添加图片'}</Tooltip.Content>
          </Tooltip>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            multiple
            className="sr-only"
            aria-label="选择图片"
            onChange={onImageInput}
          />
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
        </PromptInputToolbar>
        {attachmentIssue && <p role="alert" className="type-label max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">{attachmentIssue}</p>}
        {attachmentModelBlocked && <p role="status" className="type-label max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">当前模型不支持图片，请切换到标有“支持图片”的模型后发送。</p>}
        {chat.runtimeIssue && <p role="status" className="type-label mt-1 max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">{chat.runtimeIssue}</p>}
        {chat.modelSwitchFallback && <Button
          size="sm"
          variant="ghost"
          className="mt-1 max-w-full"
          isDisabled={chat.isRunning || chat.runtimeUpdating}
          onPress={() => void chat.switchToBlankConversation()}
        >新建空白对话并切换到 {chat.modelSwitchFallback.modelName}</Button>}
      </PromptInput>
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
