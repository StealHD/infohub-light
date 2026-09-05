import { Button, Icons, StatusIndicator } from '../../design-system'
import type { OpenClawChatController } from '../openclaw'
import type { WorkbenchAgentContextValue } from '../workbench-live/workbenchAgentContext'

export function AgentContextPanel({
  chat,
  context,
}: {
  chat: OpenClawChatController
  context: WorkbenchAgentContextValue
}) {
  return <div className="quiet-scroll-region h-full overflow-y-auto" data-agent-context-panel>
    <section className="border-b border-separator px-4 py-4">
      <h2 className="type-page-title">运行状态</h2>
      <div className="mt-3 grid gap-2">
        <StatusIndicator
          tone={chat.status === 'connected' ? 'success' : chat.status === 'error' ? 'danger' : 'neutral'}
          label={chat.status === 'connected' ? 'Gateway 已连接' : chat.status === 'reconnecting' ? 'Gateway 重连中' : 'Gateway 未连接'}
        />
        {chat.contextUsage && <p className="type-meta text-muted">上下文使用 {Math.round(chat.contextUsage.percent)}%</p>}
      </div>
    </section>

    <section className="px-4 py-4">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="type-page-title">Feed 上下文</h2>
          <p className="type-body mt-1 text-muted">从信息流交接的内容保留在同一份草稿中。</p>
        </div>
        {(context.draft.sourceSnapshot || context.draft.items.length > 0) && <Button size="sm" variant="ghost" onPress={context.clearItems}>清空</Button>}
      </div>
      <div className="mt-4 divide-y divide-separator border-y border-separator">
        {context.draft.sourceSnapshot && <div className="py-3">
          <strong className="type-control block truncate">{context.draft.sourceSnapshot.sourceName}</strong>
          <span className="type-meta text-muted">{context.draft.sourceSnapshot.itemCount} 条快照 · {context.draft.sourceSnapshot.windowLabel}</span>
        </div>}
        {context.draft.items.map((item) => <div key={item.articleId} className="flex min-w-0 items-center gap-2 py-3">
          <Icons.FileText size={15} className="shrink-0 text-muted" aria-hidden="true" />
          <span className="type-control min-w-0 flex-1 truncate">{item.title}</span>
          <Button size="sm" variant="ghost" isIconOnly aria-label={`移除 ${item.title}`} onPress={() => context.removeItem(item.articleId)}><Icons.X size={14} /></Button>
        </div>)}
      </div>
      {!context.draft.sourceSnapshot && !context.draft.items.length && <p className="type-body mt-4 text-muted">尚未选择 Feed 内容，可以直接开始对话。</p>}
    </section>
  </div>
}
