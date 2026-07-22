/* eslint-disable react-refresh/only-export-components -- Vite entry point intentionally owns the development preview boundary. */
import { StrictMode, Suspense, lazy } from 'react'
import { createRoot } from 'react-dom/client'

import { AppBootstrap } from './AppBootstrap'

const HeroWorkbenchPreview = import.meta.env.DEV
  ? lazy(() => import('./features/workbench-heroui/HeroWorkbenchPreview').then(({ HeroWorkbenchPreview: Preview }) => ({ default: Preview })))
  : null
const heroPreviewRequested = HeroWorkbenchPreview && window.location.pathname === '/__preview/workbench-heroui'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {heroPreviewRequested
      ? <Suspense fallback={<main className="app-loading" role="status">正在准备 HeroUI 工作台预览…</main>}><HeroWorkbenchPreview /></Suspense>
      : <AppBootstrap />}
  </StrictMode>,
)
