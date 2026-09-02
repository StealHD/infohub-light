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
  onClick,
  onPress,
  pending,
  pendingContent,
  type,
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

  const nativeSubmit = type === 'submit' && !onPress
  const handleSubmitClick: NonNullable<ComponentProps<typeof Button>['onClick']> = (event) => {
    if (activationLocked.current || pendingRef.current || isDisabled) {
      event.preventDefault()
      return
    }
    activationLocked.current = true
    try {
      onClick?.(event)
    } catch (error) {
      releaseActivation()
      throw error
    }

    // Disabling a submitter during its click event cancels native form submission
    // in real browsers. Keep the synchronous ref lock, but publish pending only
    // after the browser has dispatched the form's submit event.
    window.setTimeout(() => {
      if (!activationLocked.current) return
      setActivationPending(true)
      window.requestAnimationFrame(() => {
        if (!pendingRef.current && !observedExternalPending.current) releaseActivation()
      })
    }, 0)
  }

  return <Button
    {...props}
    ref={ref}
    isDisabled={isDisabled || effectivePending}
    onClick={nativeSubmit ? handleSubmitClick : onClick}
    onPress={nativeSubmit ? undefined : handlePress}
    type={type}
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
