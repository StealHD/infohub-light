import { forwardRef, type ComponentProps, type ReactNode } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Button } from './Button'

type StableAsyncButtonProps = Omit<ComponentProps<typeof Button>, 'children' | 'isPending'> & {
  children: ReactNode
  pending: boolean
  pendingContent: ReactNode
}

export const StableAsyncButton = forwardRef<HTMLButtonElement, StableAsyncButtonProps>(function StableAsyncButton({
  children,
  isDisabled = false,
  onPress,
  pending,
  pendingContent,
  ...props
}, ref) {
  const [activationPending, setActivationPending] = useState(false)
  const activationLocked = useRef(false)
  const observedExternalPending = useRef(false)
  const pendingRef = useRef(pending)
  pendingRef.current = pending
  const effectivePending = pending || activationPending

  const releaseActivation = useCallback(() => {
    activationLocked.current = false
    observedExternalPending.current = false
    setActivationPending(false)
  }, [])

  useEffect(() => {
    if (!activationLocked.current) return
    if (pending) {
      observedExternalPending.current = true
      return
    }
    if (observedExternalPending.current) releaseActivation()
  }, [pending, releaseActivation])

  const handlePress: NonNullable<ComponentProps<typeof Button>['onPress']> = (event) => {
    if (activationLocked.current || pendingRef.current || isDisabled) return
    activationLocked.current = true
    setActivationPending(true)

    let result: unknown
    try {
      result = (onPress as ((pressEvent: typeof event) => unknown) | undefined)?.(event)
    } catch (error) {
      releaseActivation()
      throw error
    }

    if (result && typeof (result as PromiseLike<unknown>).then === 'function') {
      const releaseAfterPromise = () => {
        if (!pendingRef.current) releaseActivation()
      }
      Promise.resolve(result).then(releaseAfterPromise, releaseAfterPromise)
      return
    }

    window.requestAnimationFrame(() => {
      if (!pendingRef.current && !observedExternalPending.current) releaseActivation()
    })
  }

  return <Button
    {...props}
    ref={ref}
    isDisabled={isDisabled || effectivePending}
    onPress={handlePress}
  >
    <span
      data-stable-async-button-content
      aria-busy={effectivePending || undefined}
      className="grid place-items-center"
    >
      <span
        data-stable-async-button-state="idle"
        aria-hidden={effectivePending || undefined}
        className={`col-start-1 row-start-1 inline-flex items-center justify-center gap-2 ${effectivePending ? 'invisible' : ''}`}
      >{children}</span>
      <span
        data-stable-async-button-state="pending"
        aria-hidden={!effectivePending || undefined}
        className={`col-start-1 row-start-1 inline-flex items-center justify-center gap-2 ${effectivePending ? '' : 'invisible'}`}
      >{pendingContent}</span>
    </span>
  </Button>
})
