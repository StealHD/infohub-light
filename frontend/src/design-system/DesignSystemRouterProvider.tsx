import { RouterProvider } from '@heroui/react'
import type { ReactNode } from 'react'
import { useHref, useNavigate } from 'react-router-dom'

export function DesignSystemRouterProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()

  return <RouterProvider navigate={(href) => navigate(href)} useHref={useHref}>
    {children}
  </RouterProvider>
}
