import type { ReactNode } from 'react'
import { toast } from '@heroui/react'

type ActionToastOptions = {
  description?: ReactNode
  onRetry?: () => void
  retryLabel?: string
  timeout?: number
}

type ActionToastVariant = 'success' | 'warning' | 'danger' | 'info'

const DEFAULT_TIMEOUTS: Record<ActionToastVariant, number> = {
  success: 4_000,
  info: 4_000,
  warning: 8_000,
  danger: 8_000,
}

function showActionToast(variant: ActionToastVariant, title: ReactNode, options: ActionToastOptions = {}) {
  let toastId = ''
  let actionHandled = false
  const toastOptions = {
    description: options.description,
    timeout: options.timeout ?? DEFAULT_TIMEOUTS[variant],
    ...(options.onRetry
      ? {
          actionProps: {
            children: options.retryLabel ?? '重试',
            onPress: () => {
              if (actionHandled) return
              actionHandled = true
              toast.close(toastId)
              options.onRetry?.()
            },
          },
        }
      : {}),
  }

  switch (variant) {
    case 'success':
      toastId = toast.success(title, toastOptions)
      break
    case 'warning':
      toastId = toast.warning(title, toastOptions)
      break
    case 'danger':
      toastId = toast.danger(title, toastOptions)
      break
    case 'info':
      toastId = toast.info(title, toastOptions)
      break
  }
  return toastId
}

export const actionToast = {
  success: (title: ReactNode, options?: ActionToastOptions) => showActionToast('success', title, options),
  warning: (title: ReactNode, options?: ActionToastOptions) => showActionToast('warning', title, options),
  danger: (title: ReactNode, options?: ActionToastOptions) => showActionToast('danger', title, options),
  info: (title: ReactNode, options?: ActionToastOptions) => showActionToast('info', title, options),
  clear: () => toast.clear(),
}
