import { Button as HeroButton } from '@heroui/react'
import { forwardRef, type ComponentProps } from 'react'

type ButtonProps = ComponentProps<typeof HeroButton>

function coarsePointerClass(className: ButtonProps['className'], isIconOnly: boolean): ButtonProps['className'] {
  if (!isIconOnly) return className
  const target = 'pointer-coarse:min-h-11 pointer-coarse:min-w-11'
  if (typeof className === 'function') return (values) => `${className(values)} ${target}`
  return `${className ?? ''} ${target}`.trim()
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button({
  className,
  isIconOnly = false,
  ...props
}, ref) {
  return <HeroButton
    {...props}
    ref={ref}
    className={coarsePointerClass(className, isIconOnly)}
    isIconOnly={isIconOnly}
  />
})
