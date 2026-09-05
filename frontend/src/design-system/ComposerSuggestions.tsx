import type { RefObject } from 'react'
import { Popover } from 'react-aria-components'
import { RefreshButton } from './RefreshButton'
import { Button } from './Button'
import * as Icons from './icons'

export type ComposerSuggestion = { id: string; group: string; title: string; description: string; disabled?: boolean }
export function ComposerSuggestions({ anchor, id, items, activeId, loading, error, onChoose, onClose, onRetry }: {
  anchor: RefObject<HTMLTextAreaElement | null>
  id: string
  items: ComposerSuggestion[]
  activeId?: string
  loading: boolean
  error?: string
  onChoose: (id: string) => void
  onClose: () => void
  onRetry: () => Promise<void>
}) {
  function dismiss() { onClose(); anchor.current?.focus() }
  return <Popover isOpen isNonModal triggerRef={anchor} placement="top start" offset={8} onOpenChange={(open) => { if (!open) onClose() }}
    className="z-50 w-[min(360px,calc(100vw-24px))] max-w-[var(--trigger-width)] overflow-hidden rounded-[var(--inteliscope-radius-panel)] border border-separator bg-surface p-2 outline-none">
    <div className="flex min-w-0 items-center justify-between gap-2 border-b border-separator pb-1">
      <span className="type-control min-w-0 px-2">快捷选择</span>
      <Button isIconOnly size="sm" variant="ghost" preventFocusOnPress aria-label="关闭快捷候选" onPress={dismiss}><Icons.X size={16} aria-hidden="true" /></Button>
    </div>
    <div className="quiet-scroll-region max-h-[min(320px,40dvh)] overflow-y-auto overscroll-contain">
      {loading && <p role="status" className="type-meta px-2 py-2 text-muted">正在读取 Skills…</p>}
      {error && <div className="px-2 py-2"><p role="status" className="type-meta text-warning">{error}</p><RefreshButton size="sm" variant="ghost" pending={loading} label="重试 Skills" onPress={onRetry} /></div>}
      <div id={id} role="listbox" aria-label="Agent 快捷候选">
        {items.map((item, index) => <div key={item.id}>
          {items[index - 1]?.group !== item.group && <p className="type-label px-2 py-1 text-muted">{item.group}</p>}
          <div id={`${id}-${index}`} role="option" aria-selected={item.id === activeId} aria-disabled={item.disabled || undefined}
            onMouseDown={(event) => event.preventDefault()} onClick={() => { if (!item.disabled) onChoose(item.id) }}
            className={`min-h-10 min-w-0 cursor-pointer rounded-[var(--inteliscope-radius-control)] px-2 py-2 pointer-coarse:min-h-11 ${item.id === activeId ? 'bg-accent/15 text-foreground' : 'text-muted hover:bg-default'} ${item.disabled ? 'cursor-not-allowed' : ''}`}>
            <span className="type-control line-clamp-2 [overflow-wrap:anywhere]">{item.title}</span>
            <span className="type-meta line-clamp-2 [overflow-wrap:anywhere]">{item.description}</span>
          </div>
        </div>)}
      </div>
      {!items.length && !loading && <p className="type-meta px-2 py-2 text-muted">没有匹配项。Esc 关闭后可按普通文本发送。</p>}
    </div>
    <p className="type-meta px-2 pt-1 text-muted">↑↓ 选择 · Enter 确认 · Esc 关闭</p>
  </Popover>
}
