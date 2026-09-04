import { forwardRef, type ComponentProps } from 'react'
import { useEffect, useRef, useState } from 'react'
import { Button } from './Button'

import { RefreshCw } from './icons'

export const REFRESH_FEEDBACK_MIN_MS = 400

type RefreshButtonProps = Omit<ComponentProps<typeof Button>, 'children' | 'isPending'> & {
  iconSize?: number
  label?: string
  pending: boolean
  pendingLabel?: string
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
  const [holdingFeedback, setHoldingFeedback] = useState(false)
  const activationLocked = useRef(false)
  const feedbackStartedAt = useRef(0)
  const visualPending = pending || holdingFeedback

  useEffect(() => {
    if (!holdingFeedback || pending) return
    const remaining = Math.max(0, REFRESH_FEEDBACK_MIN_MS - (Date.now() - feedbackStartedAt.current))
    const timeout = window.setTimeout(() => setHoldingFeedback(false), remaining)
    return () => window.clearTimeout(timeout)
  }, [holdingFeedback, pending])

  useEffect(() => {
    if (!visualPending) activationLocked.current = false
  }, [visualPending])

  const handlePress: NonNullable<ComponentProps<typeof Button>['onPress']> = (event) => {
    if (activationLocked.current || pending || isDisabled) return
    activationLocked.current = true
    feedbackStartedAt.current = Date.now()
    setHoldingFeedback(true)
    onPress?.(event)
  }
  const accessibleLabel = visualPending
    ? pendingLabel || `正在${label}`
    : props['aria-label'] || (isIconOnly ? label : undefined)

  return <Button
    {...props}
    ref={ref}
    aria-label={accessibleLabel}
    isDisabled={isDisabled || visualPending}
    isIconOnly={isIconOnly}
    onPress={handlePress}
  >
    <span data-refresh-button-content aria-busy={visualPending || undefined} className="inline-flex items-center justify-center gap-2">
      <RefreshCw size={iconSize} className={visualPending ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />
      {!isIconOnly && <span>{label}</span>}
    </span>
  </Button>
})
