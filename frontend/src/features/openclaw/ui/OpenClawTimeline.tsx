import { useEffect, useRef, useState } from 'react'

import { Button, Card, ChatSource, ChatSources, ImageGalleryModal, Icons, PromptSuggestion } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawMessageImage } from '../openclawMedia'
import { OpenClawActivityTrace } from './OpenClawActivityTrace'
import { ConversationTurn, OpenClawImageGrid, type OpenClawImageViewerState } from './OpenClawMessageViews'
import type { OpenClawComposerPort } from './openclawComposerPort'

function suggestions(composer: OpenClawComposerPort) {
  if (composer.snapshot) return [
    { prompt: '概括最近变化', description: '基于当前专题快照提炼最近发生了什么。', icon: Icons.FileText },
    { prompt: '梳理时间脉络', description: '按发布时间整理变化顺序。', icon: Icons.GitCompareArrows },
    { prompt: '提炼风险与机会', description: '找出值得关注的风险和后续机会。', icon: Icons.ListChecks },
  ]
  if (composer.itemCount) return [
    { prompt: '总结这些内容', description: '归纳已选内容中的关键结论。', icon: Icons.FileText },
    { prompt: '比较关键信号', description: '找出相同趋势与值得关注的差异。', icon: Icons.GitCompareArrows },
    { prompt: '提炼行动线索', description: '把值得继续跟进的事项整理出来。', icon: Icons.ListChecks },
  ]
  return [
    { prompt: '诊断最近失败任务', description: '定位失败原因并给出下一步。', icon: Icons.Stethoscope },
    { prompt: '查看异常来源', description: '检查近期不可用或退化的来源。', icon: Icons.TriangleAlert },
    { prompt: '我有哪些订阅', description: '汇总当前订阅与可见范围。', icon: Icons.Rss },
  ]
}

export function OpenClawTimeline({ chat, composer }: {
  chat: OpenClawChatController
  composer: OpenClawComposerPort
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const followRef = useRef(true)
  const [newOutputBelow, setNewOutputBelow] = useState(false)
  const [viewer, setViewer] = useState<OpenClawImageViewerState | null>(null)
  const runTrace = chat.runTrace
  const outputVersion = `${chat.messages.length}:${chat.streamText.length}:${runTrace?.phase ?? ''}:${runTrace?.activities.map((activity) => activity.status).join(',') ?? ''}`
  const attachTerminalTrace = Boolean(runTrace && !chat.isRunning && !chat.streamText && chat.messages.at(-1)?.role === 'assistant')
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

  function openImages(label: string, images: OpenClawMessageImage[], index: number, messageId?: string) {
    const selectedId = images[index]?.id
    const availableImages = images.filter((image) => Boolean(image.url))
    if (!availableImages.length) return
    setViewer({
      label,
      images: availableImages,
      index: Math.max(availableImages.findIndex((image) => image.id === selectedId), 0),
      messageId,
    })
  }

  function scrollToLatest() {
    const region = scrollRef.current
    if (!region) return
    followRef.current = true
    region.scrollTop = region.scrollHeight
    setNewOutputBelow(false)
  }

  function fillSuggestion(question: string) {
    composer.setQuestion(question)
    window.requestAnimationFrame(() => {
      document.querySelector<HTMLElement>('[aria-label="发送给 OpenClaw 的问题"]')?.focus()
    })
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
        <span className="type-meta min-w-0 truncate text-muted">{chat.sessionKey ? 'Inscope 对话' : '正在准备对话'}</span>
        <div className="flex shrink-0 gap-1">
          <Button size="sm" variant="ghost" isDisabled={chat.isRunning || chat.runtimeUpdating} onPress={() => void chat.newConversation()}><Icons.Plus size={14} />新对话</Button>
          <Button size="sm" variant="ghost" onPress={chat.disconnect}>断开</Button>
        </div>
      </div>
      {chat.toolsStatus === 'missing' && <Card variant="secondary" className="mb-3 min-w-0 border-warning/40 p-3" role="status">
        <Card.Title>未发现 Inscope 工具</Card.Title>
        <Card.Description className="mt-1">OpenClaw 已连接，但还需要在助手连接页面配置 Remote MCP 与 Skill。</Card.Description>
        <a className="type-control mt-2 inline-flex text-accent" href="/agents">打开助手连接</a>
      </Card>}
      {!chat.messages.length && !chat.streamText && !runTrace && <PromptSuggestion className="mx-auto max-w-sm py-3 text-center">
        <PromptSuggestion.Header>
          <PromptSuggestion.Title>从哪里开始？</PromptSuggestion.Title>
          <PromptSuggestion.Description className="mt-1">可以分析已选文章，也可以直接询问来源异常、任务失败或订阅配置。</PromptSuggestion.Description>
        </PromptSuggestion.Header>
        <PromptSuggestion.Items className="mt-4 text-left" aria-label="问题建议">
          {suggestions(composer).map(({ prompt, description, icon: Icon }) => <PromptSuggestion.Item key={prompt} aria-label={prompt} onPress={() => fillSuggestion(prompt)}>
            <Icon size={16} className="shrink-0 text-accent" aria-hidden="true" />
            <span className="min-w-0 flex-1">
              <PromptSuggestion.ItemTitle>{prompt}</PromptSuggestion.ItemTitle>
              <PromptSuggestion.ItemDescription>{description}</PromptSuggestion.ItemDescription>
            </span>
            <Icons.ArrowUpRight size={15} className="shrink-0 text-muted" aria-hidden="true" />
          </PromptSuggestion.Item>)}
        </PromptSuggestion.Items>
      </PromptSuggestion>}
      <div data-testid="openclaw-timeline" className="grid min-w-0 grid-cols-[12px_minmax(0,1fr)] gap-x-[9px] overflow-x-hidden">
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
            {Boolean(remainingContextCount) && <div className="type-label mt-1.5 text-muted">另附 {remainingContextCount} 条任务信息</div>}
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
              <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => composer.editFailed(message.id)}>重新编辑</Button>
            </div>}
            {traceAttached && runTrace && <OpenClawActivityTrace trace={runTrace} running={false} />}
          </ConversationTurn>
        })}
        {chat.streamText && <ConversationTurn role="assistant" text={chat.streamText} createdAt={chat.streamCreatedAt} hasNext={false}>
          {runTrace && <OpenClawActivityTrace trace={runTrace} running />}
        </ConversationTurn>}
        {showStandaloneTrace && runTrace && <ConversationTurn role="assistant" text="" createdAt={runTrace.startedAt} status={runTrace.status} hasNext={false}>
          <OpenClawActivityTrace trace={runTrace} running={chat.isRunning} />
        </ConversationTurn>}
      </div>
      {newOutputBelow && <Button size="sm" variant="secondary" className="sticky bottom-2 z-10 ml-auto mt-2 shadow-md" onPress={scrollToLatest}>
        有新回复 <Icons.ArrowDown size={14} aria-hidden="true" />
      </Button>}
      {chat.issue && <p role="alert" className="type-body mt-3 max-w-full break-words text-danger [overflow-wrap:anywhere]">{chat.issue.message}</p>}
    </div>
    <ImageGalleryModal
      isOpen={Boolean(viewer)}
      heading={viewer?.label ?? '图片预览'}
      images={(viewer?.images ?? []).flatMap((image) => image.url ? [{
        id: image.id, url: image.url, alt: image.alt, width: image.width, height: image.height,
      }] : [])}
      index={viewer?.index ?? 0}
      onIndexChange={(index) => setViewer((current) => current ? { ...current, index } : current)}
      onOpenChange={(open) => { if (!open) setViewer(null) }}
      onRefresh={(image) => { if (viewer?.messageId && image.id) void chat.refreshMedia(viewer.messageId, image.id) }}
    />
  </>
}
