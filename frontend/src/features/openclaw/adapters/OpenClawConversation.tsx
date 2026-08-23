import { Card } from '../../../design-system'
import { buildAgentHandoffPrompt } from '../../workbench-live/agentContext'
import { HandoffComposer } from '../../workbench-live/HandoffComposer'
import type { WorkbenchAgentContextValue } from '../../workbench-live/workbenchAgentContext'
import type { OpenClawChatController } from '../openclawContracts'
import type { OpenClawImageAttachment } from '../openclawMedia'
import { OpenClawConversationShell } from '../ui/OpenClawConversationShell'
import type { OpenClawComposerPort } from '../ui/openclawComposerPort'
import { OpenClawWorkbenchContextSummary } from './OpenClawWorkbenchContextSummary'

function createOpenClawWorkbenchAdapter(
  chat: OpenClawChatController,
  value: WorkbenchAgentContextValue,
): OpenClawComposerPort {
  return {
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
        gatewayPrompt: buildAgentHandoffPrompt(draft, { imageCount: attachments.length }),
        contextItems: draft.items,
        contextCount: draft.sourceSnapshot?.itemCount ?? draft.items.length,
        sourceSnapshot: draft.sourceSnapshot,
        attachments,
      })
      if (sent) value.clearComposer()
      return sent
    },
    editFailed(messageId: string) {
      const request = chat.takeFailedMessage(messageId)
      if (!request) return
      value.restoreComposer(request.displayText, request.contextItems, request.sourceSnapshot)
      window.requestAnimationFrame(() => {
        document.querySelector<HTMLElement>('[aria-label="发送给 OpenClaw 的问题"]')?.focus()
      })
    },
  }
}

export function OpenClawWorkbenchPanel({
  chat,
  value,
}: {
  chat: OpenClawChatController
  value: WorkbenchAgentContextValue
}) {
  const composer = createOpenClawWorkbenchAdapter(chat, value)
  if (chat.status === 'disabled') return <>
    <div className="quiet-scroll-region min-h-0 min-w-0 overflow-x-hidden overflow-y-auto p-4" data-testid="agent-scroll-region">
      <Card variant="transparent" className="p-3">
        <Card.Description>站内 OpenClaw 对话尚未启用；仍可复制交接提示词到自己的 OpenClaw。</Card.Description>
      </Card>
    </div>
    <HandoffComposer value={value} />
  </>
  return <OpenClawConversationShell chat={chat} composer={composer} />
}
