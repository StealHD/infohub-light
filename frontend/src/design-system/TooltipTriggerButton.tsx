import { forwardRef, type ButtonHTMLAttributes, type MouseEvent, type MutableRefObject, type Ref } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { Tooltip } from './AnchoredTooltip'

type TooltipTriggerButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick'> & {
  onClick?: (event: MouseEvent<HTMLButtonElement>) => unknown
  pending?: boolean
}

const triggerButtonBase = 'inline-flex items-center justify-center outline-none transition-[background-color,color,transform,box-shadow] disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:min-h-11 pointer-coarse:min-w-11'

function hasUnconditionalBackground(className: string): boolean {
  return className.split(/\s+/u).some((token) => /^!?bg-/u.test(token))
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === 'function') ref(value)
  else if (ref) (ref as MutableRefObject<T | null>).current = value
}

export const TooltipTriggerButton = forwardRef<HTMLButtonElement, TooltipTriggerButtonProps>(function TooltipTriggerButton(
  { 'aria-busy': ariaBusy, className = '', disabled = false, onClick, pending, type = 'button', ...buttonProps },
  forwardedRef,
) {
  const [activationPending, setActivationPending] = useState(false)
  const activationLocked = useRef(false)
  const observedExternalPending = useRef(false)
  const pendingRef = useRef(Boolean(pending))
  const managedAsyncAction = pending !== undefined
  const effectivePending = Boolean(pending) || activationPending

  const releaseActivation = useCallback(() => {
    activationLocked.current = false
    observedExternalPending.current = false
    setActivationPending(false)
  }, [])

  useEffect(() => {
    pendingRef.current = Boolean(pending)
    if (!managedAsyncAction || !activationLocked.current) return
    if (pending) {
      observedExternalPending.current = true
      return
    }
    if (observedExternalPending.current) releaseActivation()
  }, [managedAsyncAction, pending, releaseActivation])

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (!managedAsyncAction) {
      onClick?.(event)
      return
    }
    if (activationLocked.current || pending || pendingRef.current || disabled) {
      event.preventDefault()
      return
    }
    activationLocked.current = true
    setActivationPending(true)

    let result: unknown
    try {
      result = onClick?.(event)
    } catch (error) {
      releaseActivation()
      throw error
    }

    if (result && typeof (result as PromiseLike<unknown>).then === 'function') {
      const settle = () => {
        if (!pendingRef.current) releaseActivation()
      }
      Promise.resolve(result).then(settle, settle)
      return
    }

    window.requestAnimationFrame(() => {
      if (!pendingRef.current && !observedExternalPending.current) releaseActivation()
    })
  }

  const defaultBackground = hasUnconditionalBackground(className) ? '' : 'bg-transparent'
  const effectiveDisabled = disabled || (managedAsyncAction && effectivePending)
  return <Tooltip.Trigger<'button'> disabled={effectiveDisabled} render={(triggerProps) => <button
    {...triggerProps}
    {...buttonProps}
    aria-busy={ariaBusy ?? (managedAsyncAction && effectivePending ? true : undefined)}
    disabled={effectiveDisabled}
    onClick={handleClick}
    ref={(element) => {
      assignRef(triggerProps.ref as Ref<HTMLButtonElement> | undefined, element)
      assignRef(forwardedRef, element)
    }}
    type={type}
    className={`${typeof triggerProps.className === 'string' ? triggerProps.className : ''} ${triggerButtonBase} ${defaultBackground} ${className}`}
  />} />
})
