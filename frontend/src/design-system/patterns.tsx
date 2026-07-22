import { useEffect, useState, type AnimationEvent, type Key, type ReactNode } from 'react'

import {
  Alert,
  Card,
  ListBox,
  Select,
  Skeleton,
} from '@heroui/react'

import * as Icons from './icons'

export type PageFrameWidth = 'reading' | 'admin' | 'auth'

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
  auth: 'max-w-[var(--inteliscope-width-auth)]',
}

export function PageFrame({ width, children, className = '' }: {
  width: PageFrameWidth
  children: ReactNode
  className?: string
}) {
  return <div data-page-frame={width} className={`mx-auto w-full ${pageWidths[width]} ${className}`}>{children}</div>
}

export function PageHeader({ title, actions, className = '' }: { title: string; actions?: ReactNode; className?: string }) {
  return <header data-page-header data-header-visual="quiet-studio" className={`flex h-[52px] shrink-0 items-center gap-2 border-b border-separator bg-surface/95 px-3 supports-[backdrop-filter:blur(1px)]:backdrop-blur-lg min-[768px]:px-4 ${className}`}>
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

export function PageSection({ title, description, children, className = '' }: {
  title: string
  description?: string
  children: ReactNode
  className?: string
}) {
  return <Card data-page-section variant="secondary" className={`gap-0 border border-separator bg-surface-secondary p-4 shadow-none min-[640px]:p-5 ${className}`}>
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
  status?: 'default' | 'accent' | 'success' | 'warning' | 'danger'
  role?: 'alert' | 'status'
}) {
  return <Alert data-status-notice status={status} role={role}>
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
