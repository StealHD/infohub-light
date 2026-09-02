import { forwardRef, type ComponentProps, type ReactNode } from 'react'
import { Button } from '@heroui/react'

type StableAsyncButtonProps = Omit<ComponentProps<typeof Button>, 'children' | 'isPending'> & {
  children: ReactNode
  pending: boolean
  pendingContent: ReactNode
}

export const StableAsyncButton = forwardRef<HTMLButtonElement, StableAsyncButtonProps>(function StableAsyncButton({
  children,
  isDisabled = false,
  pending,
  pendingContent,
  ...props
}, ref) {
  return <Button
    {...props}
    ref={ref}
    isDisabled={isDisabled || pending}
  >
    <span
      data-stable-async-button-content
      aria-busy={pending || undefined}
      className="grid place-items-center"
    >
      <span
        data-stable-async-button-state="idle"
        aria-hidden={pending || undefined}
        className={`col-start-1 row-start-1 inline-flex items-center justify-center gap-2 ${pending ? 'invisible' : ''}`}
      >{children}</span>
      <span
        data-stable-async-button-state="pending"
        aria-hidden={!pending || undefined}
        className={`col-start-1 row-start-1 inline-flex items-center justify-center gap-2 ${pending ? '' : 'invisible'}`}
      >{pendingContent}</span>
    </span>
  </Button>
})
