import type { ReactNode } from 'react'

import { DesignSystemRouterProvider } from './DesignSystemRouterProvider'
import './theme.css'

export function DesignSystemProvider({ children }: { children: ReactNode }) {
  return <DesignSystemRouterProvider>
    <div
      className="inteliscope-design-system"
      data-theme="dark"
      data-inteliscope-theme="graphite-purple"
      data-ui-system="heroui"
    >
      {children}
    </div>
  </DesignSystemRouterProvider>
}
