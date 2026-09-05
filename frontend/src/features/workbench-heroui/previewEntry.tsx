import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HeroWorkbenchPreview } from './HeroWorkbenchPreview'

createRoot(document.getElementById('root')!).render(
  <StrictMode><HeroWorkbenchPreview /></StrictMode>,
)
