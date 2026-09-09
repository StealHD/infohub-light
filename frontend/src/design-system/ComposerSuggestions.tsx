import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { useInteractOutside } from 'react-aria/useInteractOutside'
import { Activity, BookOpen, Bot, Brain, GitCompareArrows, Paperclip, Plus, Sparkles } from './icons'
import { Popover } from 'react-aria-components'
import { RefreshButton } from './RefreshButton'

const suggestionIcons = { Activity, BookOpen, Bot, Brain, GitCompareArrows, Paperclip, Plus, Sparkles }
export type ComposerSuggestion = { id: string; group: string; title: string; description: string; disabled?: boolean; icon?: keyof typeof suggestionIcons }
export function ComposerSuggestions({ anchor, id, items, activeId, loading, error, onChoose, onClose, onRetry, onHighlight }: {
  anchor: RefObject<HTMLTextAreaElement | null>
  id: string
  items: ComposerSuggestion[]
  activeId?: string
  loading: boolean
  error?: string
  onHighlight?: (id: string) => void
  onChoose: (id: string) => void
  onClose: () => void
  onRetry: () => Promise<void>
}) {
  const [target, setTarget] = useState<HTMLElement | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let active = true
    const input = anchor.current
    void Promise.resolve().then(() => { if (active && input) setTarget(input.closest<HTMLElement>('[data-prompt-input]') ?? input) })
    return () => { active = false }
  }, [anchor])
  const surfaceAnchor = useMemo(() => ({ current: target }), [target])
  const showGroups = new Set(items.map((item) => item.group)).size > 1
  useInteractOutside({ ref: panelRef, onInteractOutside: onClose })
  if (!target) return null
  return <Popover ref={panelRef} isOpen isNonModal triggerRef={surfaceAnchor} containerPadding={12} placement="top start" offset={8} onOpenChange={(open) => { if (!open) onClose() }}
    className="composer-suggestions z-50 w-[var(--trigger-width)] max-w-[calc(100vw-24px)] overflow-hidden rounded-[var(--inteliscope-radius-panel)] border border-separator bg-overlay p-1 outline-none">
    <div className="quiet-scroll-region @container max-h-[min(320px,45dvh)] overflow-y-auto overscroll-contain">
      {loading && <p role="status" className="type-meta px-2 py-2 text-muted">正在读取 Skills…</p>}
      {error && <div className="px-2 py-2"><p role="status" className="type-meta text-warning">{error}</p><RefreshButton size="sm" variant="ghost" pending={loading} label="重试 Skills" onPress={onRetry} /></div>}
      <div id={id} role="listbox" aria-label="Agent 快捷候选" aria-describedby={`${id}-instructions`}>
        {items.map((item, index) => { const Icon = suggestionIcons[item.icon ?? 'Sparkles']; return <div key={item.id}>
          {items[index - 1]?.group !== item.group && <p className={showGroups ? 'type-label px-2 pb-1 pt-2 text-muted' : 'sr-only'}>{item.group}</p>}
          <div id={`${id}-${index}`} role="option" aria-selected={item.id === activeId} aria-disabled={item.disabled || undefined}
            onMouseMove={() => { if (!item.disabled) onHighlight?.(item.id) }} onMouseDown={(event) => event.preventDefault()} onClick={() => { if (!item.disabled) onChoose(item.id) }}
            className={`flex min-h-8 min-w-0 items-center gap-2 rounded-[var(--inteliscope-radius-control)] px-2 py-1.5 pointer-coarse:min-h-11 ${item.id === activeId ? 'bg-default' : item.disabled ? '' : 'hover:bg-default'} ${item.disabled ? 'cursor-not-allowed text-muted' : 'cursor-pointer text-foreground'}`}>
            <Icon size={16} className="shrink-0" aria-hidden="true" />
            <span className="flex min-w-0 flex-1 items-baseline gap-x-2 @max-[480px]:flex-col">
              <span className="type-control max-w-[45%] shrink-0 [overflow-wrap:anywhere] @max-[480px]:max-w-full">{item.title}</span>
              <span className={`type-meta min-w-0 max-w-full flex-1 text-muted ${item.disabled ? '[overflow-wrap:anywhere]' : 'truncate'}`} title={item.description}>{item.description}</span>
            </span>
          </div>
        </div> })}
      </div>
      {!items.length && !loading && <p className="type-meta px-2 py-2 text-muted">没有匹配项。Esc 关闭后可按普通文本发送。</p>}
    </div>
    <p id={`${id}-instructions`} className="sr-only">↑↓ 选择 · Enter 确认 · Esc 关闭</p>
  </Popover>
}
