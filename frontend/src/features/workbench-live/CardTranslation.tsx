import { lazy, Suspense, type ReactNode } from 'react'
import { useAppContext } from '../../app/AppContext'
import type { WorkbenchCardModel } from './workbenchModel'

const TranslationContent = lazy(() => import('./CardTranslationContent'))
type Slots = { button: ReactNode; body: ReactNode }
export type CardTranslationProps = {
  card: WorkbenchCardModel
  readonly?: boolean
  onExpand: () => void
  children: (slots: Slots) => ReactNode
}

export function CardTranslation(props: CardTranslationProps) {
  const context = useAppContext()
  if (!context || typeof context.api.feedTranslation !== 'function') return props.children({ button: null, body: null })
  const placeholder = <span aria-hidden="true" className="size-8 shrink-0 pointer-coarse:size-11" />
  return <Suspense fallback={props.children({ button: placeholder, body: null })}>
    <TranslationContent {...props} context={context} />
  </Suspense>
}
