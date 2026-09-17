import { Fragment, useEffect, useRef, useState } from 'react'

import { Button, Card, ChatSource, ChatSources, ImageGalleryModal, Icons, StableAsyncButton } from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawMessageImage } from '../openclawMedia'
import { OpenClawActivityTrace } from './OpenClawActivityTrace'
import { OpenClawConversationIssue } from './OpenClawConversationIssue'
import { OpenClawFailureNotice } from './OpenClawFailureNotice'
import { ConversationTurn, OpenClawImageGrid, type OpenClawImageViewerState } from './OpenClawMessageViews'
import { OpenClawPromptSuggestions } from './OpenClawPromptSuggestions'
import type { OpenClawComposerPort } from './openclawComposerPort'

function CompactTimelineHeader({ chat }: { chat: OpenClawChatController }) {
  return <div className="mb-4 flex min-w-0 items-center justify-between gap-2">
    <span className="type-meta min-w-0 truncate text-muted">{chat.sessionKey ? 'Inscope 对话' : '正在准备对话'}</span>
    <div className="flex shrink-0 gap-1">
      <StableAsyncButton size="sm" variant="ghost" pending={chat.runtimeUpdating} pendingContent="新建中…" isDisabled={chat.isRunning} onPress={() => chat.newConversation()}><Icons.Plus size={14} />新对话</StableAsyncButton>
      <Button size="sm" variant="ghost" onPress={chat.disconnect}>断开</Button>
    </div>
  </div>
}

export function OpenClawTimeline({ chat, composer, variant = 'compact' }: {
  chat: OpenClawChatController
  composer: OpenClawComposerPort
  variant?: 'compact' | 'workspace'
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

  return <>
    <div
      ref={scrollRef}
      className={`quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain ${variant === 'workspace' ? 'px-4 pb-8 pt-6 min-[640px]:px-8' : 'px-[15px] pb-4 pt-[13px]'}`}
      data-testid="agent-scroll-region" data-page-scroll-region={variant === 'workspace' ? '' : undefined}
      aria-live="polite"
      onScroll={(event) => {
        const region = event.currentTarget
        followRef.current = region.scrollHeight - region.scrollTop - region.clientHeight <= 96
        if (followRef.current) setNewOutputBelow(false)
      }}
    >
      {variant !== 'workspace' && <CompactTimelineHeader chat={chat} />}
      {chat.toolsStatus === 'missing' && <Card variant="secondary" className="mb-3 min-w-0 border-warning/40 p-3" role="status">
        <Card.Title>未发现 Inscope 工具</Card.Title>
        <Card.Description className="mt-1">OpenClaw 已连接，但还需要在助手连接页面配置 Remote MCP 与 Skill。</Card.Description>
        <a className="type-control mt-2 inline-flex text-accent" href="/agents">打开助手连接</a>
      </Card>}
      {!chat.messages.length && !chat.streamText && !runTrace && <OpenClawPromptSuggestions composer={composer} variant={variant} />}
      <div data-testid="openclaw-timeline" data-conversation-variant={variant} className={`${variant === 'workspace' ? 'mx-auto w-full max-w-[var(--inteliscope-width-agent-conversation)] grid-cols-1 gap-x-0' : 'grid-cols-[12px_minmax(0,1fr)] gap-x-[9px]'} grid min-w-0 overflow-x-hidden`}>
        {chat.messages.map((message, index) => {
          const traceAttached = attachTerminalTrace && index === chat.messages.length - 1
          const contextSources = message.contextSources ?? []
          const remainingContextCount = Math.max(0, (message.contextCount ?? 0) - contextSources.length)
          return <Fragment key={message.id}><ConversationTurn
            role={message.role}
            text={message.text}
            createdAt={message.createdAt}
              status={message.status}
              hasNext={index < chat.messages.length - 1 || Boolean(chat.streamText) || showStandaloneTrace}
              variant={variant}
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
              onRefresh={(imageId) => chat.refreshMedia(message.id, imageId)}
            />}
            {message.status === 'aborted' && <div className="type-label mt-1.5 text-muted">已停止</div>}
            {message.diagnostic && <OpenClawFailureNotice diagnostic={message.diagnostic} text={message.text} />}
            {message.status === 'failed' && message.role === 'user' && <div className="mt-1.5 flex flex-wrap gap-1">
              <StableAsyncButton size="sm" variant="ghost" pending={chat.isRunning} pendingContent="重试中…" onPress={() => chat.retry(message.id)}>重试</StableAsyncButton>
              <Button size="sm" variant="ghost" isDisabled={chat.isRunning} onPress={() => composer.editFailed(message.id)}>重新编辑</Button>
            </div>}
            {traceAttached && runTrace && <OpenClawActivityTrace trace={runTrace} running={false} />}
          </ConversationTurn>
          </Fragment>
        })}
        {chat.streamText && <ConversationTurn role="assistant" text={chat.streamText} createdAt={chat.streamCreatedAt} hasNext={false} variant={variant}>
          {runTrace && <OpenClawActivityTrace trace={runTrace} running />}
        </ConversationTurn>}
        {showStandaloneTrace && runTrace && <ConversationTurn role="assistant" text="" createdAt={runTrace.startedAt} status={runTrace.status} hasNext={false} variant={variant}>
          <OpenClawActivityTrace trace={runTrace} running={chat.isRunning} />
        </ConversationTurn>}
      </div>
      {newOutputBelow && <Button size="sm" variant="secondary" className="sticky bottom-2 z-10 ml-auto mt-2 shadow-md" onPress={scrollToLatest}>
        有新回复 <Icons.ArrowDown size={14} aria-hidden="true" />
      </Button>}
      {chat.issue && <OpenClawConversationIssue message={chat.issue.message} variant={variant} />}
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
