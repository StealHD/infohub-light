/* eslint-disable react-refresh/only-export-components -- This module intentionally exposes a compound Tooltip component. */

import { useContext, type ComponentProps, type JSX, type MouseEventHandler, type PointerEventHandler, type ReactElement, type ReactNode } from 'react'
import {
  Focusable,
  OverlayArrow,
  Tooltip as ReactAriaTooltip,
  TooltipTrigger as ReactAriaTooltipTrigger,
  TooltipTriggerStateContext,
} from 'react-aria-components'

type TooltipRootProps = ComponentProps<typeof ReactAriaTooltipTrigger>
type IntrinsicProps<E extends keyof JSX.IntrinsicElements> = JSX.IntrinsicElements[E]
type TooltipTriggerProps<E extends keyof JSX.IntrinsicElements = 'button'> = {
  children?: ReactNode
  className?: string
  render?: (props: IntrinsicProps<E>) => ReactElement
} & Omit<IntrinsicProps<E>, 'children' | 'className' | 'ref'>
type TooltipContentProps = Omit<ComponentProps<typeof ReactAriaTooltip>, 'children'> & {
  children?: ReactNode
  showArrow?: boolean
}

function joinClassName(defaultClassName: string, className: TooltipContentProps['className']) {
  if (typeof className === 'function') return (values: Parameters<typeof className>[0]) => `${defaultClassName} ${className(values)}`
  return `${defaultClassName} ${className ?? ''}`
}

function TooltipRoot({ children, closeDelay = 120, delay = 500, ...props }: TooltipRootProps) {
  return <ReactAriaTooltipTrigger {...props} closeDelay={closeDelay} delay={delay}>
    {children}
  </ReactAriaTooltipTrigger>
}

function TooltipTrigger<E extends keyof JSX.IntrinsicElements = 'button'>({
  children,
  className = '',
  render,
  ...props
}: TooltipTriggerProps<E>) {
  const state = useContext(TooltipTriggerStateContext)
  const eventProps = props as {
    onPointerEnter?: PointerEventHandler<Element>
    onPointerLeave?: PointerEventHandler<Element>
    onMouseEnter?: MouseEventHandler<Element>
    onMouseLeave?: MouseEventHandler<Element>
  }
  const triggerProps = {
    ...props,
    className: `tooltip__trigger ${className}`,
    'data-slot': 'tooltip-trigger',
    onPointerEnter: ((event) => {
      eventProps.onPointerEnter?.(event)
      if (event.pointerType !== 'touch') state?.open()
    }) as PointerEventHandler,
    onPointerLeave: ((event) => {
      eventProps.onPointerLeave?.(event)
      if (event.pointerType !== 'touch') state?.close()
    }) as PointerEventHandler,
    onMouseEnter: ((event) => {
      eventProps.onMouseEnter?.(event)
      if (typeof PointerEvent === 'undefined') state?.open()
    }) as MouseEventHandler,
    onMouseLeave: ((event) => {
      eventProps.onMouseLeave?.(event)
      if (typeof PointerEvent === 'undefined') state?.close()
    }) as MouseEventHandler,
  } as unknown as IntrinsicProps<E>
  const element = render
    ? render(triggerProps)
    : <button {...(triggerProps as IntrinsicProps<'button'>)} type="button">{children}</button>
  const disabled = 'disabled' in props && Boolean(props.disabled)

  return <Focusable isDisabled={disabled}>{element}</Focusable>
}

function TooltipContent({ children, className, offset = 3, showArrow = false, ...props }: TooltipContentProps) {
  return <ReactAriaTooltip
    {...props}
    className={joinClassName('tooltip', className)}
    data-slot="tooltip-content"
    offset={offset || (showArrow ? 7 : 3)}
  >
    {showArrow && <TooltipArrow />}
    {children}
  </ReactAriaTooltip>
}

function TooltipArrow({ children, ...props }: ComponentProps<typeof OverlayArrow>) {
  return <OverlayArrow {...props} data-slot="tooltip-arrow">
    {children ?? <svg aria-hidden="true" fill="none" height="12" viewBox="0 0 12 12" width="12"><path d="M0 0C5.48483 8 6.5 8 12 0Z" /></svg>}
  </OverlayArrow>
}

export const Tooltip = Object.assign(TooltipRoot, {
  Root: TooltipRoot,
  Trigger: TooltipTrigger,
  Content: TooltipContent,
  Arrow: TooltipArrow,
})

export type { TooltipContentProps, TooltipRootProps, TooltipTriggerProps }
