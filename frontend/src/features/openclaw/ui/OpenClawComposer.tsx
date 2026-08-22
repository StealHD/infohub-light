import { useRef, useState, type ChangeEvent, type DragEvent } from 'react'

import {
  anchoredTooltipProps,
  Button,
  ImageGalleryModal,
  Icons,
  PromptInput,
  PromptInputBody,
  PromptInputToolbar,
  TextArea,
  Tooltip,
  TooltipTriggerButton,
} from '../../../design-system'
import type { OpenClawChatController } from '../openclawContracts'
import { OPENCLAW_MAX_IMAGES_PER_TURN } from '../openclawMedia'
import { OpenClawRuntimeControls } from './OpenClawRuntimeControls'
import type { OpenClawComposerPort } from './openclawComposerPort'
import { useOpenClawAttachments } from './useOpenClawAttachments'

function DraftAttachmentPreviews({
  attachments,
  onOpen,
  onRemove,
}: {
  attachments: ReturnType<typeof useOpenClawAttachments>['attachments']
  onOpen(index: number): void
  onRemove(id: string): void
}) {
  if (!attachments.length) return null
  return <div className="flex flex-wrap gap-2" aria-label={`已添加 ${attachments.length} 张图片`}>
    {attachments.map((attachment, index) => <div key={attachment.id} className="relative size-14 overflow-hidden rounded-lg border border-separator bg-default">
      <button type="button" className="size-full outline-none focus-visible:outline-2 focus-visible:outline-focus" aria-label={`预览第 ${index + 1} 张图片`} onClick={() => onOpen(index)}>
        <img src={attachment.previewUrl} alt="" className="size-full object-cover" />
      </button>
      <button type="button" className="absolute right-0.5 top-0.5 inline-flex size-5 items-center justify-center rounded-full bg-background/90 text-foreground outline-none hover:bg-default focus-visible:outline-2 focus-visible:outline-focus" aria-label={`移除第 ${index + 1} 张图片`} onClick={() => onRemove(attachment.id)}>
        <Icons.X size={12} aria-hidden="true" />
      </button>
    </div>)}
  </div>
}

export function OpenClawComposer({ chat, composer }: {
  chat: OpenClawChatController
  composer: OpenClawComposerPort
}) {
  const composingRef = useRef(false)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [previewIndex, setPreviewIndex] = useState<number | null>(null)
  const attachmentState = useOpenClawAttachments(chat.imageInputAvailable)
  const attachmentModelBlocked = Boolean(attachmentState.attachments.length && !chat.currentModelSupportsImages)
  const canSend = Boolean(composer.question.trim() || composer.itemCount || composer.snapshot || attachmentState.attachments.length)
    && !attachmentModelBlocked

  async function send() {
    if (!canSend || chat.isRunning) return
    if (await composer.send(attachmentState.attachments)) attachmentState.markSent()
  }

  function onImageInput(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    void attachmentState.append(files)
  }

  return <div data-testid="openclaw-composer-dock" className="min-w-0 shrink-0 overflow-hidden p-2">
    {chat.status === 'reconnecting' && <div role="status" className="type-meta mb-2 flex min-w-0 items-center gap-2 rounded-lg bg-warning/10 px-2 py-1.5 text-warning">
      <Icons.WifiOff size={14} className="shrink-0" aria-hidden="true" />
      <span className="min-w-0 flex-1 truncate">连接中断，正在重连{chat.reconnectAttempt > 0 ? ` · 第 ${chat.reconnectAttempt} 次` : ''}</span>
      <Button size="sm" variant="ghost" onPress={chat.retryConnection}>立即重试</Button>
    </div>}
    {composer.contextSummary}
    <PromptInput
      data-testid="openclaw-composer"
      className="grid grid-rows-[minmax(80px,auto)_36px] gap-2 p-2"
      onDragOver={(event: DragEvent<HTMLDivElement>) => {
        if (!chat.imageInputAvailable || !Array.from(event.dataTransfer.types).includes('Files')) return
        event.preventDefault()
      }}
      onDrop={(event: DragEvent<HTMLDivElement>) => {
        if (!chat.imageInputAvailable) return
        event.preventDefault()
        void attachmentState.append(Array.from(event.dataTransfer.files))
      }}
    >
      <PromptInputBody className="grid gap-2">
        <DraftAttachmentPreviews attachments={attachmentState.attachments} onOpen={setPreviewIndex} onRemove={attachmentState.remove} />
        <TextArea
          fullWidth
          variant="secondary"
          data-testid="openclaw-composer-textarea"
          className="type-body !min-h-20 !max-h-[180px] min-w-0 max-w-full resize-none !rounded-none !border-0 !bg-transparent px-1 py-1 !shadow-none outline-none focus:!ring-0 focus:!ring-offset-0 focus-visible:outline-none overflow-y-auto overscroll-y-contain [field-sizing:content] [overflow-wrap:anywhere]"
          aria-label="发送给 OpenClaw 的问题"
          value={composer.question}
          maxLength={1200}
          rows={2}
          placeholder="分析文章，或询问来源和任务…"
          onChange={(event) => composer.setQuestion(event.target.value)}
          onPaste={(event) => {
            const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith('image/'))
            if (!files.length || !chat.imageInputAvailable) return
            event.preventDefault()
            void attachmentState.append(files)
          }}
          onCompositionStart={() => { composingRef.current = true }}
          onCompositionEnd={() => { composingRef.current = false }}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || event.shiftKey) return
            if (composingRef.current || event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229) return
            event.preventDefault()
            void send()
          }}
        />
      </PromptInputBody>
      <PromptInputToolbar data-testid="openclaw-composer-toolbar" className="grid grid-cols-[36px_minmax(0,1fr)_36px] px-1 pb-0.5">
        <Tooltip delay={250}>
          <TooltipTriggerButton
            aria-label="添加图片"
            disabled={!chat.imageInputAvailable || chat.isRunning || attachmentState.attachments.length >= OPENCLAW_MAX_IMAGES_PER_TURN}
            onClick={() => fileInputRef.current?.click()}
            className="size-9 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground"
          ><Icons.ImagePlus size={17} aria-hidden="true" /></TooltipTriggerButton>
          <Tooltip.Content {...anchoredTooltipProps}>{!chat.imageInputAvailable
            ? '图片输入尚未启用'
            : attachmentState.attachments.length >= OPENCLAW_MAX_IMAGES_PER_TURN
              ? `每次最多 ${OPENCLAW_MAX_IMAGES_PER_TURN} 张图片`
              : '添加图片'}</Tooltip.Content>
        </Tooltip>
        <input ref={fileInputRef} type="file" accept="image/jpeg,image/png,image/webp" multiple className="sr-only" aria-label="选择图片" onChange={onImageInput} />
        <OpenClawRuntimeControls chat={chat} />
        <Tooltip delay={250}>
          <TooltipTriggerButton
            aria-label={chat.isRunning ? '停止生成' : '发送给 OpenClaw'}
            disabled={chat.isRunning ? chat.isStopping : !canSend || chat.status !== 'connected'}
            onClick={chat.isRunning ? () => void chat.stop() : () => void send()}
            className="size-9 shrink-0 rounded-full bg-accent text-accent-foreground hover:bg-accent-hover"
          >{chat.isRunning ? <Icons.Square size={14} fill="currentColor" aria-hidden="true" /> : <Icons.ArrowUp size={16} aria-hidden="true" />}</TooltipTriggerButton>
          <Tooltip.Content {...anchoredTooltipProps}>{chat.isRunning ? (chat.isStopping ? '正在停止…' : '停止生成') : '发送给 OpenClaw'}</Tooltip.Content>
        </Tooltip>
      </PromptInputToolbar>
      {attachmentState.issue && <p role="alert" className="type-label max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">{attachmentState.issue}</p>}
      {attachmentModelBlocked && <p role="status" className="type-label max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">当前模型不支持图片，请切换到标有“支持图片”的模型后发送。</p>}
      {chat.runtimeIssue && <p role="status" className="type-label mt-1 max-w-full break-words px-1 text-warning [overflow-wrap:anywhere]">{chat.runtimeIssue}</p>}
      {chat.modelSwitchFallback && <Button size="sm" variant="ghost" className="mt-1 max-w-full" isDisabled={chat.isRunning || chat.runtimeUpdating} onPress={() => void chat.switchToBlankConversation()}>
        新建空白对话并切换到 {chat.modelSwitchFallback.modelName}
      </Button>}
    </PromptInput>
    <ImageGalleryModal
      isOpen={previewIndex !== null}
      heading="待发送图片"
      images={attachmentState.attachments.map((image, index) => ({ id: image.id, url: image.previewUrl, alt: `待发送第 ${index + 1} 张图片`, width: image.width, height: image.height }))}
      index={previewIndex ?? 0}
      onIndexChange={setPreviewIndex}
      onOpenChange={(open) => { if (!open) setPreviewIndex(null) }}
    />
  </div>
}
