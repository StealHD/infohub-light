import { useEffect, useState, type AnimationEvent, type Key, type ReactNode } from 'react'

import {
  Alert,
  Card,
  ListBox,
  Select,
  Skeleton,
} from '@heroui/react'

import * as Icons from './icons'

export type PageFrameWidth = 'reading' | 'admin' | 'settings' | 'auth'

export type ViewBarAction = {
  ariaLabel: string
  icon: ReactNode
  isDisabled?: boolean
  onPress: () => void
}

export type CompactSelectOption = {
  id: string
  label: string
  description?: string
}

export type LoadingRevealProps = {
  loading: boolean
  label: string
  name: string
  skeleton: ReactNode
  children: ReactNode
  className?: string
}

const pageWidths: Record<PageFrameWidth, string> = {
  reading: 'max-w-[var(--inteliscope-width-reading)]',
  admin: 'max-w-[var(--inteliscope-width-admin)]',
  settings: 'max-w-[var(--inteliscope-width-settings)]',
  auth: 'max-w-[var(--inteliscope-width-auth)]',
}

export function PageFrame({ width, children, className = '' }: {
  width: PageFrameWidth
  children: ReactNode
  className?: string
}) {
  return <div data-page-frame={width} className={`mx-auto w-full ${pageWidths[width]} ${className}`}>{children}</div>
}

export function PageHeader({ title, leading, actions, className = '' }: { title: string; leading?: ReactNode; actions?: ReactNode; className?: string }) {
  return <header data-page-header data-header-visual="quiet-studio" data-page-header-appearance="inset" className={`flex h-[var(--inteliscope-size-page-header-surface)] shrink-0 items-center gap-2 border border-foreground/10 bg-surface/75 px-3 [margin-block:var(--inteliscope-inset-page-header-block)] [margin-inline:var(--inteliscope-inset-page-header-inline)] rounded-[var(--inteliscope-radius-page-header)] supports-[backdrop-filter:blur(1px)]:backdrop-blur-xl min-[768px]:px-4 ${className}`}>
    {leading}
    <h1 className="type-page-title min-w-0 flex-1 truncate">{title}</h1>
    {actions}
  </header>
}

export function PageIntro({ description, actions }: { description: string; actions?: ReactNode }) {
  return <div data-page-intro className="flex flex-col gap-3 min-[640px]:flex-row min-[640px]:items-center min-[640px]:justify-between">
    <p className="type-body max-w-3xl text-muted">{description}</p>
    {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
  </div>
}

export function ViewBar({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div data-view-bar className={`flex min-h-10 w-full items-center gap-1 rounded-xl border border-separator/80 bg-surface-secondary/70 px-2.5 ${className}`}>{children}</div>
}

export type ScrollAdaptiveViewBarState = 'expanded' | 'floating'
export type ScrollAdaptiveViewBarAppearance = 'quiet' | 'command'

export function ScrollAdaptiveViewBar({ children, state, appearance = 'quiet', className = '' }: {
  children: ReactNode
  state: ScrollAdaptiveViewBarState
  appearance?: ScrollAdaptiveViewBarAppearance
  className?: string
}) {
  const floating = state === 'floating'
  const surface = appearance === 'command'
    ? `${floating ? 'w-[calc(100%-16px)] max-w-[var(--inteliscope-width-reading)] bg-surface/90 supports-[backdrop-filter:blur(1px)]:backdrop-blur-lg' : 'w-full max-w-full bg-surface-secondary/85'} min-h-12 rounded-2xl border border-border/90 px-1.5 py-1 shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_8%,transparent)] min-[640px]:rounded-[var(--inteliscope-radius-pill)]`
    : floating
      ? 'min-h-10 w-[calc(100%-16px)] max-w-[var(--inteliscope-width-reading)] rounded-full border border-separator/80 bg-surface-secondary/80 px-3 shadow-[inset_0_1px_0_var(--surface)] supports-[backdrop-filter:blur(1px)]:backdrop-blur-lg'
      : 'min-h-10 w-full max-w-full rounded-2xl border border-separator/70 bg-surface-secondary/55 px-3 shadow-[inset_0_1px_0_var(--surface)]'
  return <div
    data-scroll-adaptive-view-bar
    data-view-bar-state={state}
    data-view-bar-appearance={appearance}
    className={`mx-auto flex items-center gap-1 transition-[width,max-width,border-radius,border-color,background-color,box-shadow] duration-[var(--inteliscope-motion-deliberate)] ease-out motion-reduce:transition-none ${surface} ${className}`}
  >{children}</div>
}

export function PageSection({ title, description, children, className = '', id }: {
  title: string
  description?: string
  children: ReactNode
  className?: string
  id?: string
}) {
  return <Card id={id} tabIndex={id ? -1 : undefined} data-page-section variant="secondary" className={`scroll-mt-4 gap-0 border border-separator bg-surface-secondary p-4 shadow-none focus-visible:outline-2 focus-visible:outline-focus min-[640px]:p-5 ${className}`}>
    <Card.Header className="px-0 pt-0">
      <div>
        <Card.Title className="type-page-title">{title}</Card.Title>
        {description && <Card.Description className="type-body mt-1 text-muted">{description}</Card.Description>}
      </div>
    </Card.Header>
    <Card.Content className="px-0 pb-0">{children}</Card.Content>
  </Card>
}

export function CompactSelect({ ariaLabel, value, options, onChange, className = '', isDisabled = false }: {
  ariaLabel: string
  value: string
  options: CompactSelectOption[]
  onChange: (value: string) => void
  className?: string
  isDisabled?: boolean
}) {
  return <Select
    aria-label={ariaLabel}
    selectedKey={value}
    onSelectionChange={(key: Key | null) => key !== null && onChange(String(key))}
    isDisabled={isDisabled}
    className={`quiet-compact-select min-w-0 ${className}`}
  >
    <Select.Trigger aria-label={ariaLabel} className="type-control min-h-8 border-0 bg-transparent px-1.5 shadow-none">
      <Select.Value />
      <Select.Indicator><Icons.ChevronDown size={12} aria-hidden="true" /></Select.Indicator>
    </Select.Trigger>
    <Select.Popover>
      <ListBox items={options}>
        {(item) => <ListBox.Item id={item.id} textValue={item.label} className="type-control">
          <span>{item.label}</span>
          {item.description && <span className="type-meta block text-muted">{item.description}</span>}
        </ListBox.Item>}
      </ListBox>
    </Select.Popover>
  </Select>
}

export function EmptyState({ title, description, actions }: { title: string; description?: string; actions?: ReactNode }) {
  return <Card data-empty-state variant="transparent" className="p-6 text-center">
    <Card.Title>{title}</Card.Title>
    {description && <Card.Description className="mt-1">{description}</Card.Description>}
    {actions && <div className="mt-4 flex justify-center gap-2">{actions}</div>}
  </Card>
}

export function StatusNotice({ title, children, status = 'danger', role = 'alert' }: {
  title: string
  children?: ReactNode
  status?: 'default' | 'accent' | 'info' | 'success' | 'warning' | 'danger'
  role?: 'alert' | 'status'
}) {
  const alertStatus = status === 'info' ? 'accent' : status

  return <Alert data-status-notice status={alertStatus} role={role}>
    <Alert.Content>
      <Alert.Title>{title}</Alert.Title>
      {children && <Alert.Description>{children}</Alert.Description>}
    </Alert.Content>
  </Alert>
}

export function LoadingState({ label = '正在加载', rows = 3 }: { label?: string; rows?: number }) {
  return <div data-loading-state role="status" aria-label={label} className="grid gap-3">
    {Array.from({ length: rows }, (_, index) => <Skeleton key={index} className="h-32 rounded-[var(--inteliscope-radius-card)]" />)}
  </div>
}

export function CalmSkeleton({ className = '' }: { className?: string }) {
  return <Skeleton animationType="pulse" className={`inteliscope-skeleton-calm ${className}`} />
}

export function LoadingReveal({ loading, label, name, skeleton, children, className = '' }: LoadingRevealProps) {
  const [showSkeleton, setShowSkeleton] = useState(loading)
  const revealing = !loading && showSkeleton

  useEffect(() => {
    if (loading || !showSkeleton) return
    const reducedMotion = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const timeout = window.setTimeout(() => setShowSkeleton(false), reducedMotion ? 0 : 180)
    return () => window.clearTimeout(timeout)
  }, [loading, showSkeleton])

  function finishSkeletonExit(event: AnimationEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return
    setShowSkeleton(false)
  }

  return <div
    data-loading-reveal={name}
    data-loading-state={loading ? 'loading' : revealing ? 'revealing' : 'ready'}
    className={`relative grid min-h-0 ${className}`}
  >
    {showSkeleton && <div
      data-loading-layer
      role={loading ? 'status' : undefined}
      aria-label={loading ? label : undefined}
      aria-busy={loading ? 'true' : undefined}
      aria-hidden={loading ? undefined : 'true'}
      className={`min-h-0 [grid-area:1/1] ${revealing ? 'inteliscope-skeleton-exit' : ''}`}
      onAnimationEnd={finishSkeletonExit}
    >{skeleton}</div>}
    {!loading && <div
      data-content-layer
      className={`flex min-h-0 flex-col [grid-area:1/1] ${revealing ? 'inteliscope-content-reveal' : ''}`}
    >{children}</div>}
  </div>
}
