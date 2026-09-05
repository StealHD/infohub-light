import { useEffect, useMemo, useState, type RefObject } from 'react'
import { Activity, BookOpen, Bot, Brain, GitCompareArrows, Paperclip, Plus, Sparkles, X } from './icons'
import { Popover } from 'react-aria-components'
import { RefreshButton } from './RefreshButton'
import { Button } from './Button'

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
  useEffect(() => {
    let active = true
    const input = anchor.current
    void Promise.resolve().then(() => { if (active && input) setTarget(input.closest<HTMLElement>('[data-prompt-input]') ?? input) })
    return () => { active = false }
  }, [anchor])
  const surfaceAnchor = useMemo(() => ({ current: target }), [target])
  function dismiss() { onClose(); anchor.current?.focus() }
  if (!target) return null
  return <Popover isOpen isNonModal triggerRef={surfaceAnchor} containerPadding={12} placement="top start" offset={8} onOpenChange={(open) => { if (!open) onClose() }}
    className="composer-suggestions z-50 w-[var(--trigger-width)] max-w-[calc(100vw-24px)] overflow-hidden rounded-[var(--inteliscope-radius-panel)] border border-separator bg-overlay p-2 outline-none">
    <div className="flex min-w-0 items-center justify-between gap-2 border-b border-separator pb-1">
      <span className="type-control min-w-0 px-2">快捷选择</span>
      <Button isIconOnly size="sm" variant="ghost" preventFocusOnPress aria-label="关闭快捷候选" onPress={dismiss}><X size={16} aria-hidden="true" /></Button>
    </div>
    <div className="quiet-scroll-region max-h-[min(480px,60dvh)] overflow-y-auto overscroll-contain">
      {loading && <p role="status" className="type-meta px-2 py-2 text-muted">正在读取 Skills…</p>}
      {error && <div className="px-2 py-2"><p role="status" className="type-meta text-warning">{error}</p><RefreshButton size="sm" variant="ghost" pending={loading} label="重试 Skills" onPress={onRetry} /></div>}
      <div id={id} role="listbox" aria-label="Agent 快捷候选">
        {items.map((item, index) => { const Icon = suggestionIcons[item.icon ?? 'Sparkles']; return <div key={item.id}>
          {items[index - 1]?.group !== item.group && <p className="sr-only">{item.group}</p>}
          <div id={`${id}-${index}`} role="option" aria-selected={item.id === activeId} aria-disabled={item.disabled || undefined}
            onMouseMove={() => { if (!item.disabled) onHighlight?.(item.id) }} onMouseDown={(event) => event.preventDefault()} onClick={() => { if (!item.disabled) onChoose(item.id) }}
            className={`flex min-h-11 min-w-0 cursor-pointer items-center gap-2 rounded-[var(--inteliscope-radius-pill)] px-2 py-2 pointer-coarse:min-h-11 ${item.id === activeId ? 'bg-default text-foreground' : 'text-muted hover:bg-default'} ${item.disabled ? 'cursor-not-allowed' : ''}`}>
            <Icon size={17} className="shrink-0" aria-hidden="true" />
            <span className="type-control max-w-[45%] shrink-0 [overflow-wrap:anywhere]">{item.title}</span>
            <span className="type-meta min-w-0 flex-1 text-muted [overflow-wrap:anywhere]">{item.description}</span>
          </div>
        </div> })}
      </div>
      {!items.length && !loading && <p className="type-meta px-2 py-2 text-muted">没有匹配项。Esc 关闭后可按普通文本发送。</p>}
    </div>
    <p className="type-meta px-2 pt-1 text-muted">↑↓ 选择 · Enter 确认 · Esc 关闭</p>
  </Popover>
}
