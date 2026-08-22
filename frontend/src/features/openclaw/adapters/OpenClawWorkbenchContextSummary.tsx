import { useId, useState } from 'react'

import { Button, ChatSource, Icons, Tooltip, TooltipTriggerButton } from '../../../design-system'
import type { AgentContextItem } from '../../workbench-live/agentContext'
import type { WorkbenchAgentContextValue } from '../../workbench-live/workbenchAgentContext'

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
export function OpenClawWorkbenchContextSummary({ value }: { value: WorkbenchAgentContextValue }) {
  const snapshot = value.draft.sourceSnapshot
  const count = snapshot?.itemCount ?? value.draft.items.length
  const hiddenItems = value.draft.items.slice(2)
  const hiddenItemsKey = hiddenItems.map((item) => item.articleId).join(':')
  const [expandedItemsKey, setExpandedItemsKey] = useState<string | null>(null)
  const expanded = Boolean(hiddenItems.length) && expandedItemsKey === hiddenItemsKey
  const hiddenItemsId = useId()

  if (!count) return null
  if (snapshot) return <div
    className="mb-2 flex min-w-0 items-center gap-2 rounded-xl border border-separator bg-surface-secondary p-2"
    aria-label={`已附带 ${snapshot.sourceName} 专题快照，共 ${snapshot.itemCount} 条信息`}
    data-source-snapshot-summary
  >
    <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent"><Icons.Layers3 size={15} aria-hidden="true" /></span>
    <span className="min-w-0 flex-1">
      <span className="type-control block truncate">{snapshot.sourceName}</span>
      <span className="type-label block truncate text-muted">{snapshot.windowLabel} · {snapshot.itemCount} 条只读快照</span>
    </span>
    <Button size="sm" variant="ghost" isIconOnly className="size-8 shrink-0" aria-label={`移除 ${snapshot.sourceName} 专题快照`} onPress={value.clearItems}>
      <Icons.X size={14} aria-hidden="true" />
    </Button>
  </div>
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
