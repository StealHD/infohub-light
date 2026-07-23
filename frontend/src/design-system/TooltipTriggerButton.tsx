import { forwardRef, type ButtonHTMLAttributes, type MutableRefObject, type Ref } from 'react'

import { Tooltip } from './AnchoredTooltip'

type TooltipTriggerButtonProps = ButtonHTMLAttributes<HTMLButtonElement>

const triggerButtonBase = 'inline-flex items-center justify-center outline-none transition-[background-color,color,transform,box-shadow] disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-focus'

function hasUnconditionalBackground(className: string): boolean {
  return className.split(/\s+/u).some((token) => /^!?bg-/u.test(token))
}

function assignRef<T>(ref: Ref<T> | undefined, value: T | null) {
  if (typeof ref === 'function') ref(value)
  else if (ref) (ref as MutableRefObject<T | null>).current = value
}

export const TooltipTriggerButton = forwardRef<HTMLButtonElement, TooltipTriggerButtonProps>(function TooltipTriggerButton(
  { className = '', disabled = false, type = 'button', ...buttonProps },
  forwardedRef,
) {
  const defaultBackground = hasUnconditionalBackground(className) ? '' : 'bg-transparent'
  return <Tooltip.Trigger<'button'> disabled={disabled} render={(triggerProps) => <button
    {...triggerProps}
    {...buttonProps}
    disabled={disabled}
    ref={(element) => {
      assignRef(triggerProps.ref as Ref<HTMLButtonElement> | undefined, element)
      assignRef(forwardedRef, element)
    }}
    type={type}
    className={`${typeof triggerProps.className === 'string' ? triggerProps.className : ''} ${triggerButtonBase} ${defaultBackground} ${className}`}
  />} />
})
