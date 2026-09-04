import { forwardRef, type ButtonHTMLAttributes, type ComponentProps, type MouseEvent, type ReactNode } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Button } from './Button'

import { Tooltip, type TooltipContentProps } from './AnchoredTooltip'
import { RefreshCw } from './icons'
import { TooltipTriggerButton } from './TooltipTriggerButton'

export const REFRESH_FEEDBACK_MIN_MS = 400

type RefreshButtonProps = Omit<ComponentProps<typeof Button>, 'children' | 'isPending'> & {
  iconSize?: number
  label?: string
  pending: boolean
  pendingLabel?: string
}

type RefreshActionStateProps = {
  isDisabled: boolean
  onActivate?: (event: unknown) => unknown
  pending: boolean
}

function useRefreshActionState({ isDisabled, onActivate, pending }: RefreshActionStateProps) {
  const [holdingFeedback, setHoldingFeedback] = useState(false)
  const activationLocked = useRef(false)
  const operationPending = useRef(false)
  const minimumElapsed = useRef(false)
  const feedbackTimer = useRef<number | null>(null)
  const pendingRef = useRef(pending)
  const visualPending = pending || holdingFeedback

  const releaseIfComplete = useCallback(() => {
    if (!activationLocked.current || !minimumElapsed.current || operationPending.current || pendingRef.current) return
    activationLocked.current = false
    setHoldingFeedback(false)
  }, [])

  useEffect(() => {
    pendingRef.current = pending
    if (!pending) releaseIfComplete()
  }, [pending, releaseIfComplete])

  useEffect(() => () => {
    if (feedbackTimer.current !== null) window.clearTimeout(feedbackTimer.current)
    activationLocked.current = false
  }, [])

  function activate(event: unknown) {
    if (activationLocked.current || pending || isDisabled) return
    activationLocked.current = true
    operationPending.current = false
    minimumElapsed.current = false
    setHoldingFeedback(true)
    feedbackTimer.current = window.setTimeout(() => {
      feedbackTimer.current = null
      minimumElapsed.current = true
      releaseIfComplete()
    }, REFRESH_FEEDBACK_MIN_MS)

    let result: unknown
    try {
      result = onActivate?.(event)
    } catch (error) {
      if (feedbackTimer.current !== null) window.clearTimeout(feedbackTimer.current)
      feedbackTimer.current = null
      activationLocked.current = false
      setHoldingFeedback(false)
      throw error
    }

    if (result && typeof (result as PromiseLike<unknown>).then === 'function') {
      operationPending.current = true
      const settle = () => {
        operationPending.current = false
        releaseIfComplete()
      }
      Promise.resolve(result).then(settle, settle)
    }
  }

  return { activate, visualPending }
}

export const RefreshButton = forwardRef<HTMLButtonElement, RefreshButtonProps>(function RefreshButton({
  iconSize = 15,
  isDisabled = false,
  isIconOnly = false,
  label = '刷新',
  onPress,
  pending,
  pendingLabel,
  ...props
}, ref) {
  const { activate, visualPending } = useRefreshActionState({
    isDisabled,
    onActivate: onPress as ((event: unknown) => unknown) | undefined,
    pending,
  })
  const accessibleLabel = visualPending
    ? pendingLabel || `正在${label}`
    : props['aria-label'] || (isIconOnly ? label : undefined)

  return <Button
    {...props}
    ref={ref}
    aria-label={accessibleLabel}
    isDisabled={isDisabled || visualPending}
    isIconOnly={isIconOnly}
    onPress={(event) => activate(event)}
  >
    <span data-refresh-button-content aria-busy={visualPending || undefined} className="inline-flex items-center justify-center gap-2">
      <RefreshCw size={iconSize} className={visualPending ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />
      {!isIconOnly && <span>{label}</span>}
    </span>
  </Button>
})

type RefreshIconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'aria-label' | 'children' | 'disabled' | 'onClick'> & {
  iconSize?: number
  isDisabled?: boolean
  label: string
  onPress?: (event: MouseEvent<HTMLButtonElement>) => unknown
  pending: boolean
  pendingLabel?: string
  tooltip: ReactNode
  tooltipDelay?: number
  tooltipProps?: Omit<TooltipContentProps, 'children'>
}

export const RefreshIconButton = forwardRef<HTMLButtonElement, RefreshIconButtonProps>(function RefreshIconButton({
  iconSize = 15,
  isDisabled = false,
  label,
  onPress,
  pending,
  pendingLabel,
  tooltip,
  tooltipDelay = 500,
  tooltipProps,
  ...props
}, ref) {
  const { activate, visualPending } = useRefreshActionState({
    isDisabled,
    onActivate: onPress as ((event: unknown) => unknown) | undefined,
    pending,
  })
  const accessibleLabel = visualPending ? pendingLabel || `正在${label}` : label

  return <Tooltip delay={tooltipDelay}>
    <TooltipTriggerButton
      {...props}
      ref={ref}
      aria-label={accessibleLabel}
      aria-busy={visualPending || undefined}
      disabled={isDisabled || visualPending}
      onClick={(event) => activate(event)}
    >
      <RefreshCw size={iconSize} className={visualPending ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />
    </TooltipTriggerButton>
    <Tooltip.Content {...tooltipProps}>{tooltip}</Tooltip.Content>
  </Tooltip>
})
