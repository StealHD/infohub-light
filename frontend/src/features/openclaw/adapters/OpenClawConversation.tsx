import { Card } from '../../../design-system'
import { useEffect, useRef } from 'react'
import { buildAgentHandoffPrompt } from '../../workbench-live/agentHandoffPrompt'
import { HandoffComposer } from '../../workbench-live/HandoffComposer'
import type { WorkbenchAgentContextValue } from '../../workbench-live/workbenchAgentContext'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawImageAttachment } from '../openclawMedia'
import { OpenClawConversationShell } from '../ui/OpenClawConversationShell'
import type { OpenClawComposerPort } from '../ui/openclawComposerPort'
import { OpenClawWorkbenchContextSummary } from './OpenClawWorkbenchContextSummary'
import { useComposerCommands } from './useComposerCommands'
import { escapeSkillReferences, wrapSkillHandoff } from '../chat/openclawSkillInvocation'

function useOpenClawWorkbenchAdapter(
  chat: OpenClawChatController,
  value: WorkbenchAgentContextValue,
): OpenClawComposerPort {
  const latest = useRef(value)
  useEffect(() => { latest.current = value }, [value])
  const commands = useComposerCommands(chat)
  return {
    ...commands,
    selectedSkill: value.draft.selectedSkill,
    materials: value.draft.sourceSnapshot ? [{ id: 'snapshot', title: value.draft.sourceSnapshot.sourceName }] : value.draft.items.map((item) => ({ id: item.articleId, title: item.title })),
    selectSkill: (skill, question) => value.restoreComposer(question, value.draft.items, value.draft.sourceSnapshot, skill),
    question: value.draft.question,
    itemCount: value.draft.items.length,
    snapshot: value.draft.sourceSnapshot
      ? { sourceName: value.draft.sourceSnapshot.sourceName, itemCount: value.draft.sourceSnapshot.itemCount }
      : null,
    contextSummary: <OpenClawWorkbenchContextSummary value={value} />,
    setQuestion: value.setQuestion,
    async send(attachments: OpenClawImageAttachment[]) {
      const draft = {
        ...value.draft,
        items: value.draft.items.map((item) => ({ ...item })),
      }
      const displayText = draft.question.trim()
        || (draft.sourceSnapshot
          ? `分析 ${draft.sourceSnapshot.sourceName} 的 ${draft.sourceSnapshot.itemCount} 条专题快照`
          : draft.items.length ? `分析已附带的 ${draft.items.length} 条信息` : '')
      const sent = await chat.send({
        displayText,
        gatewayPrompt: draft.selectedSkill ? wrapSkillHandoff(buildAgentHandoffPrompt(draft, { imageCount: attachments.length }), draft.selectedSkill) : escapeSkillReferences(buildAgentHandoffPrompt(draft, { imageCount: attachments.length })),
        selectedSkill: draft.selectedSkill,
        contextItems: draft.items,
        contextCount: draft.sourceSnapshot?.itemCount ?? draft.items.length,
        sourceSnapshot: draft.sourceSnapshot,
        attachments,
      })
      if (sent && latest.current.draft === value.draft) value.clearComposer()
      return sent
    },
    editFailed(messageId: string) {
      const request = chat.takeFailedMessage(messageId)
      if (!request) return
      value.restoreComposer(request.displayText, request.contextItems, request.sourceSnapshot, request.selectedSkill)
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('[aria-label="发送给 OpenClaw 的问题"]')?.focus()
      })
    },
  }
}

export function OpenClawWorkbenchPanel({
  chat,
  value,
  variant = 'compact',
}: {
  chat: OpenClawChatController
  value: WorkbenchAgentContextValue
  variant?: 'compact' | 'workspace'
}) {
  const composer = useOpenClawWorkbenchAdapter(chat, value)
  if (chat.status === 'disabled') return <>
    <div className={`quiet-scroll-region min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto ${variant === 'workspace' ? 'px-4 py-10 min-[640px]:px-8' : 'p-4'}`} data-testid="agent-scroll-region" data-page-scroll-region={variant === 'workspace' ? '' : undefined}>
      <Card variant="transparent" className={`${variant === 'workspace' ? 'mx-auto max-w-[var(--inteliscope-width-agent-conversation)] px-0 py-6' : 'p-3'}`}>
        <Card.Description>站内 OpenClaw 对话尚未启用；仍可复制交接提示词到自己的 OpenClaw。</Card.Description>
      </Card>
    </div>
    <div className={variant === 'workspace' ? 'mx-auto w-full max-w-[var(--inteliscope-width-agent-composer)] px-2 pb-[calc(12px+env(safe-area-inset-bottom))]' : ''}><HandoffComposer value={value} /></div>
  </>
  return <OpenClawConversationShell chat={chat} composer={composer} variant={variant} />
}
