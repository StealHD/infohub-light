import { useEffect, useRef, useState } from 'react'

import {
  Icons,
  Tooltip,
  TooltipTriggerButton,
  bottomAnchoredTooltipProps,
  topAnchoredTooltipProps,
} from '../../design-system'

type CopyFeedback = 'success' | 'error' | null

export function CopySummaryAction({ label, text }: { label: string; text: string }) {
  const [feedback, setFeedback] = useState<CopyFeedback>(null)
  const [helpOpen, setHelpOpen] = useState(false)
  const resetTimer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(resetTimer.current), [])

  async function copySummary() {
    window.clearTimeout(resetTimer.current)
    try {
      if (typeof navigator.clipboard?.writeText !== 'function') throw new Error('Clipboard API unavailable')
      await navigator.clipboard.writeText(text)
      setFeedback('success')
    } catch {
      setFeedback('error')
    }
    resetTimer.current = window.setTimeout(() => setFeedback(null), 2800)
  }

  return <>
    <Tooltip
      delay={feedback ? 0 : 500}
      isOpen={feedback !== null || helpOpen}
      onOpenChange={setHelpOpen}
    >
      <TooltipTriggerButton
        data-copy-state={feedback ?? 'idle'}
        className={`size-8 rounded-lg hover:bg-default hover:text-foreground active:scale-95 pointer-coarse:size-11 motion-reduce:transform-none ${feedback === 'success' ? 'bg-default text-success' : feedback === 'error' ? 'bg-default text-danger' : 'text-muted'}`}
        aria-label={`复制摘要 ${label}`}
        onClick={() => void copySummary()}
      >{feedback === 'success'
        ? <Icons.Check size={15} aria-hidden="true" />
        : <Icons.Copy size={15} aria-hidden="true" />}</TooltipTriggerButton>
      <Tooltip.Content {...(feedback ? topAnchoredTooltipProps : bottomAnchoredTooltipProps)}>
        {feedback === 'success' ? '已复制' : feedback === 'error' ? '复制失败' : '复制摘要'}
      </Tooltip.Content>
    </Tooltip>
    {feedback && <span role="status" aria-live="polite" className="sr-only">
      {feedback === 'success' ? '摘要已复制' : '复制失败，请手动复制'}
    </span>}
  </>
}
