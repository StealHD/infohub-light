import { useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

import type { CatalogSource, FeedSchedule, SourceHealthItem, SourceTypeDefinition, Subscription } from '../../api/types'
import {
  anchoredTooltipProps,
  Button,
  Card,
  Icons,
  MetaTag,
  Modal,
  Popover,
  SearchField,
  StatusIndicator,
  Tooltip,
  TooltipTriggerButton,
  topAnchoredTooltipProps,
} from '../../design-system'
import {
  effectiveSourceType,
  presentSourceHealthIssue,
  presentSourceHealthStatus,
  sourceScopeLabel,
  sourceTypeLabel,
  type ChannelViewGroup,
  type HealthFilter,
} from '../subscriptions/subscriptionModel'
import { SourceAvatar } from '../source-avatar/SourceAvatar'
import { HeroSelect } from './HeroAdminControls'

export type FetchLabel = '提交中' | '已排队' | '获取中' | '立即获取'

export type SubscriptionViewEntry = {
  source: CatalogSource
  subscription: Subscription
  health?: SourceHealthItem
  fetchLabel: FetchLabel
  notificationPending: boolean
  canEdit: boolean
  canShare: boolean
}

export type LibraryViewEntry = {
  source: CatalogSource
  subscription?: Subscription
  channel: string
  subscribed: boolean
  subscribePending: boolean
  unsubscribePending: boolean
  canEdit: boolean
  canShare: boolean
}

export type SourceFilterProps = {
  definitions: SourceTypeDefinition[]
  typeFilter: string
  onTypeChange: (value: string) => void
  scopeFilter: string
  onScopeChange: (value: string) => void
  healthFilter: HealthFilter
  onHealthChange: (value: HealthFilter) => void
  includeHealth: boolean
}

type ChannelLayoutProps<T> = {
  groups: ChannelViewGroup<T>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  viewLabel: string
  selectorLabel: string
  channelDetail: (items: T[], group: ChannelViewGroup<T>) => string
  channelSummary: (items: T[], group: ChannelViewGroup<T>) => string
  beforeList?: ReactNode
  emptyTitle: string | ((group: ChannelViewGroup<T>) => string)
  emptyDescription?: string | ((group: ChannelViewGroup<T>) => string)
  renderList: (items: T[]) => ReactNode
}

const healthOptions = [
  { id: 'all', label: '全部健康状态' },
  { id: 'problem', label: '需处理' },
  { id: 'healthy', label: '正常' },
  { id: 'degraded', label: '需关注' },
  { id: 'failing', label: '连续失败' },
  { id: 'unknown', label: '尚未抓取' },
]

const scopeOptions = [
  { id: 'all', label: '全部范围' },
  { id: 'public', label: '公共订阅' },
  { id: 'private', label: '私人订阅' },
]

const formatCompactTime = (value?: string | null) => {
  if (!value) return '尚无记录'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? '时间未知'
    : parsed.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const intervalLabel = (minutes?: number) => {
  if (!minutes) return '周期未知'
  if (minutes < 60) return `每 ${minutes} 分钟`
  return `每 ${minutes / 60} 小时`
}

const formatClockTime = (value?: string | null) => {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime())
    ? null
    : parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

const formatUpdateTime = (value?: string | null) => {
  if (!value) return '尚未完成'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '时间未知'
  const now = new Date()
  const isToday = parsed.getFullYear() === now.getFullYear()
    && parsed.getMonth() === now.getMonth()
    && parsed.getDate() === now.getDate()
  return isToday
    ? `今天 ${parsed.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`
    : formatCompactTime(value)
}

function SourceIdentity({ source, detail }: { source: CatalogSource; detail: string }) {
  return <div className="flex min-w-0 items-center gap-3">
    <SourceAvatar
      name={source.display_name}
      avatarUrl={source.avatar_url}
      platform={source.setup_type || source.type}
      className="size-9 shrink-0 rounded-xl bg-accent/10 type-label text-accent"
    />
    <span className="min-w-0">
      <span className="type-control block truncate text-foreground">{source.display_name}</span>
      <span className="type-meta mt-0.5 block truncate text-muted">{detail}</span>
    </span>
  </div>
}

function SourceIssueDetails({ health, canRetry, canEdit }: { health: SourceHealthItem; canRetry: boolean; canEdit: boolean }) {
  const issue = health.last_issue
  if (!issue) return null
  const presentation = presentSourceHealthIssue(health, { canRetry, canEdit })
  return <div className="type-body grid gap-3">
    <div><span className="type-label text-muted">原因</span><p className="mt-1">{presentation.reason}</p></div>
    <div><span className="type-label text-muted">影响</span><p className="mt-1 text-muted">{presentation.impact}</p></div>
    <div><span className="type-label text-muted">建议操作</span><p className="mt-1 text-muted">{presentation.action}</p></div>
    {canEdit && <details>
      <summary className="type-meta cursor-pointer text-muted">技术详情</summary>
      <dl className="type-meta mt-2 grid gap-1 [overflow-wrap:anywhere]">
        <div><dt className="inline text-muted">阶段：</dt><dd className="inline">{issue.stage || '未知'}</dd></div>
        <div><dt className="inline text-muted">代码：</dt><dd className="inline">{issue.code || '未知'}</dd></div>
        <div><dt className="inline text-muted">可重试：</dt><dd className="inline">{issue.retryable ? '是' : '否'}</dd></div>
        <div><dt className="inline text-muted">原始信息：</dt><dd className="inline">{issue.message || '未提供'}</dd></div>
      </dl>
    </details>}
  </div>
}

function SourceHealthStatus({ health, canRetry, canEdit }: { health?: SourceHealthItem; canRetry: boolean; canEdit: boolean }) {
  const [detailsOpen, setDetailsOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const status = health?.status ?? 'unknown'
  const issue = health?.last_issue
  const presentation = health && issue ? presentSourceHealthIssue(health, { canRetry, canEdit }) : null
  const healthStatus = presentSourceHealthStatus(status)
  const icon = healthStatus.icon === 'check'
    ? <Icons.CircleCheck size={13} aria-hidden="true" />
    : healthStatus.icon === 'warning'
      ? <Icons.TriangleAlert size={13} aria-hidden="true" />
      : healthStatus.icon === 'error'
        ? <Icons.CircleX size={13} aria-hidden="true" />
        : <Icons.CircleDashed size={13} aria-hidden="true" />
  const indicator = <span data-source-health-chip aria-label={`健康状态：${healthStatus.label}`} className="inline-flex shrink-0 self-center">
    <StatusIndicator
      iconOnly
      withTooltip={!issue || !presentation}
      label={healthStatus.label}
      tone={healthStatus.tone}
      icon={icon}
    />
  </span>

  if (!health || !issue || !presentation) return indicator
  const failureCount = Math.max(health.consecutive_failures || 0, 1)
  return <>
    <Tooltip delay={250}>
      <TooltipTriggerButton
        ref={triggerRef}
        className="h-auto min-h-0 rounded-full p-0"
        aria-label={`查看 ${healthStatus.label} 详情`}
        onClick={() => setDetailsOpen(true)}
      >{indicator}</TooltipTriggerButton>
      <Tooltip.Content {...anchoredTooltipProps}>{`已连续 ${failureCount} 次失败：${presentation.reason}`}</Tooltip.Content>
    </Tooltip>
    <Modal isOpen={detailsOpen} onOpenChange={(open) => {
      setDetailsOpen(open)
      if (!open) window.requestAnimationFrame(() => triggerRef.current?.focus())
    }}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开来源失败详情</Modal.Trigger>
      <Modal.Backdrop>
        <Modal.Container size="md">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>来源获取失败</Modal.Heading></Modal.Header>
            <Modal.Body><SourceIssueDetails health={health} canRetry={canRetry} canEdit={canEdit} /></Modal.Body>
            <Modal.Footer><Button onPress={() => setDetailsOpen(false)}>关闭</Button></Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </>
}

function SourceEditAction({ source, onEditSource }: {
  source: CatalogSource
  onEditSource: (trigger: HTMLElement) => void
}) {
  return <Tooltip delay={250}>
    <TooltipTriggerButton
      aria-label={`编辑来源：${source.display_name}`}
      className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11"
      onClick={(event) => onEditSource(event.currentTarget)}
    ><Icons.Pencil size={15} aria-hidden="true" /></TooltipTriggerButton>
    <Tooltip.Content {...topAnchoredTooltipProps}>编辑来源</Tooltip.Content>
  </Tooltip>
}

function SourceShareAction({ source, onShare }: {
  source: CatalogSource
  onShare: (trigger: HTMLElement) => void
}) {
  return <Tooltip delay={250}>
    <TooltipTriggerButton
      aria-label={`分享来源：${source.display_name}`}
      className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11"
      onClick={(event) => onShare(event.currentTarget)}
    ><Icons.Share2 size={15} aria-hidden="true" /></TooltipTriggerButton>
    <Tooltip.Content {...topAnchoredTooltipProps}>分享来源</Tooltip.Content>
  </Tooltip>
}

function notificationDisabledReason({
  editable,
  source,
  subscription,
  pending,
}: {
  editable: boolean
  source: CatalogSource
  subscription: Subscription
  pending: boolean
}) {
  if (pending) return '正在保存新内容通知'
  if (!editable) return '当前账户无权修改新内容通知'
  if (!source.enabled) return '来源已停用，无法开启通知'
  if (!subscription.enabled) return '订阅已停用，无法开启通知'
  if (subscription.analysis_mode === 'personal_only') return '仅个人模式不发送新内容通知'
  return ''
}

export function SourceSearchField({ value, onChange, className = '' }: { value: string; onChange: (value: string) => void; className?: string }) {
  return <SearchField aria-label="搜索来源" value={value} onChange={onChange} className={`min-w-0 ${className}`} fullWidth variant="secondary">
    <SearchField.Group className="min-h-8 border-0 bg-transparent shadow-none">
      <SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon>
      <SearchField.Input placeholder="搜索来源" />
      <SearchField.ClearButton />
    </SearchField.Group>
  </SearchField>
}

export function SourceFilterMenu({ filters }: {
  filters: SourceFilterProps
}) {
  const [open, setOpen] = useState(false)
  const activeCount = Number(filters.typeFilter !== 'all') + Number(filters.scopeFilter !== 'all') + Number(filters.includeHealth && filters.healthFilter !== 'all')
  const typeOptions = [
    { id: 'all', label: '全部类型' },
    ...filters.definitions.map((definition) => ({ id: definition.type, label: definition.label || sourceTypeLabel(definition.type) })),
  ]
  const clear = () => {
    filters.onTypeChange('all')
    filters.onScopeChange('all')
    if (filters.includeHealth) filters.onHealthChange('all')
  }

  return <Popover isOpen={open} onOpenChange={setOpen}>
    <Popover.Trigger
      aria-label={`筛选来源，已启用 ${activeCount} 项`}
      title={activeCount > 0 ? `筛选来源 · 已启用 ${activeCount} 项` : '筛选来源'}
      className="relative inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
    >
      <Icons.SlidersHorizontal size={15} aria-hidden="true" />
      {activeCount > 0 && <span aria-label={`已启用 ${activeCount} 项筛选`} className="type-micro absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-accent px-1 text-center text-accent-foreground">{activeCount}</span>}
    </Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} className="z-40 w-[min(340px,calc(100vw-24px))] p-0">
      <Popover.Dialog aria-label="筛选来源" className="grid gap-3 p-4">
        <Popover.Heading className="type-page-title">筛选来源</Popover.Heading>
        <HeroSelect label="来源类型" value={filters.typeFilter} onChange={filters.onTypeChange} options={typeOptions} className="w-full" />
        {filters.includeHealth && <HeroSelect label="健康状态" value={filters.healthFilter} onChange={(value) => filters.onHealthChange(value as HealthFilter)} options={healthOptions} className="w-full" />}
        <HeroSelect label="可见范围" value={filters.scopeFilter} onChange={filters.onScopeChange} options={scopeOptions} className="w-full" />
        <div className="flex items-center justify-end gap-2">
          <Button type="button" size="sm" variant="ghost" isDisabled={activeCount === 0} onPress={clear}>清除筛选</Button>
          <Button type="button" size="sm" variant="secondary" onPress={() => setOpen(false)}>完成</Button>
        </div>
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}

function ChannelRail<T>({ groups, selectedChannel, onSelectChannel, detail, viewLabel }: {
  groups: ChannelViewGroup<T>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  detail: (items: T[], group: ChannelViewGroup<T>) => string
  viewLabel: string
}) {
  return <aside data-channel-rail className="sticky top-4 hidden self-start rounded-2xl border border-separator bg-surface-secondary p-3 min-[1200px]:block">
    <div className="type-label mb-1 px-2 text-muted">{viewLabel === '我的订阅' ? '视图' : '频道'}</div>
    <nav aria-label={`${viewLabel}频道`} className="grid gap-1">
      {groups.map((group) => {
        const selected = group.id === selectedChannel
        return <button
          key={group.id}
          type="button"
          aria-pressed={selected}
          aria-label={`${group.label}，${detail(group.items, group)}，${group.items.length} 个来源`}
          className={`grid min-h-14 w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-2 rounded-xl px-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-focus ${selected ? 'bg-accent/15 text-foreground ring-1 ring-inset ring-accent/25' : 'text-muted hover:bg-default hover:text-foreground'}`}
          onClick={() => onSelectChannel(group.id)}
        >
          <span aria-hidden="true" className={`grid size-8 place-items-center rounded-lg type-label ${selected ? 'bg-accent/15 text-foreground' : 'bg-default text-muted'}`}>
            {group.id === 'all' ? '全' : group.id === 'exceptions' ? '异' : group.id === 'scope:public' ? '公' : group.id === 'scope:private' ? '私' : group.label === 'AI' ? 'AI' : Array.from(group.label)[0]}
          </span>
          <span className="min-w-0">
            <span className="type-control block truncate">{group.label}</span>
            <span className="type-meta block truncate text-muted">{detail(group.items, group)}</span>
          </span>
          <span className="type-meta tabular-nums">{group.items.length}</span>
        </button>
      })}
    </nav>
  </aside>
}

function ChannelHeader({ group, summary }: {
  group: ChannelViewGroup<unknown>
  summary: string
}) {
  return <Card data-channel-header variant="secondary" className="min-w-0 max-w-full border border-separator bg-surface-secondary p-4 shadow-none">
    <div className="min-w-0">
      <div className="type-label text-accent">当前频道</div>
      <h2 className="type-section-title mt-1 truncate">{group.label}</h2>
      <p className="type-meta mt-1 text-muted">{summary}</p>
    </div>
  </Card>
}

function ChannelLayout<T>({
  groups,
  selectedChannel,
  onSelectChannel,
  viewLabel,
  selectorLabel,
  channelDetail,
  channelSummary,
  beforeList,
  emptyTitle,
  emptyDescription,
  renderList,
}: ChannelLayoutProps<T>) {
  const activeGroup = groups.find((group) => group.id === selectedChannel) ?? groups[0]
  const emptyTitleText = activeGroup && typeof emptyTitle === 'function'
    ? emptyTitle(activeGroup)
    : typeof emptyTitle === 'string' ? emptyTitle : '没有匹配的来源'
  const emptyDescriptionText = activeGroup && typeof emptyDescription === 'function'
    ? emptyDescription(activeGroup)
    : typeof emptyDescription === 'string' ? emptyDescription : undefined
  const controls = <div data-compact-channel-controls className="min-w-0 max-w-full min-[1200px]:hidden">
    {activeGroup && <HeroSelect
      label={selectorLabel}
      value={activeGroup.id}
      onChange={onSelectChannel}
      options={groups.map((group) => ({ id: group.id, label: `${group.label} · ${group.items.length}` }))}
    />}
  </div>

  return <>
    {controls}
    <div data-channel-workspace={viewLabel} className="grid min-w-0 max-w-full items-start gap-4 min-[1200px]:grid-cols-[236px_minmax(0,1fr)]">
      <ChannelRail
        groups={groups}
        selectedChannel={activeGroup?.id ?? ''}
        onSelectChannel={onSelectChannel}
        detail={channelDetail}
        viewLabel={viewLabel}
      />
      <section aria-label={`${activeGroup?.label ?? '无匹配频道'} ${viewLabel}`} className="grid min-w-0 max-w-full gap-3">
        {activeGroup && <ChannelHeader
          group={activeGroup}
          summary={channelSummary(activeGroup.items, activeGroup)}
        />}
        {beforeList}
        {activeGroup && activeGroup.items.length > 0 ? renderList(activeGroup.items) : <Card variant="transparent" className="p-6 text-center">
          <Card.Title>{emptyTitleText}</Card.Title>
          {emptyDescriptionText && <Card.Description className="mt-1">{emptyDescriptionText}</Card.Description>}
        </Card>}
      </section>
    </div>
  </>
}

export function SubscriptionRows({ items, editable, feedWindowDays = 7, globalSchedule, onFetch, onToggleNotification, onEditSubscription, onEditSource, onShare }: {
  items: SubscriptionViewEntry[]
  editable: boolean
  feedWindowDays?: number
  globalSchedule?: FeedSchedule
  onFetch: (entry: SubscriptionViewEntry) => void
  onToggleNotification: (entry: SubscriptionViewEntry, enabled: boolean) => void
  onEditSubscription: (entry: SubscriptionViewEntry) => void
  onEditSource: (source: CatalogSource, trigger: HTMLElement) => void
  onShare: (source: CatalogSource, trigger: HTMLElement) => void
}) {
  return <div role="list" aria-label="订阅来源" className="grid min-w-0 max-w-full gap-2">
    {items.map((entry) => {
      const { source, subscription, health } = entry
      const schedule = subscription.schedule
      const subscriptionActive = source.enabled && subscription.enabled
      const usesSourceSchedule = subscriptionActive && Boolean(schedule?.enabled)
      const effectiveNextRunAt = !subscriptionActive
        ? null
        : usesSourceSchedule
          ? schedule?.next_run_at
          : globalSchedule?.enabled
            ? globalSchedule.next_run_at
            : null
      const nextRunTime = formatClockTime(effectiveNextRunAt)
      const updateDetails = !subscriptionActive
        ? ['更新：订阅已停用']
        : usesSourceSchedule
          ? ['更新：单源', intervalLabel(schedule?.interval_minutes)]
          : globalSchedule?.enabled
            ? ['更新：全局', intervalLabel(globalSchedule.interval_minutes)]
            : globalSchedule
              ? ['更新：跟随全局', '全局已关闭']
              : ['更新：跟随全局']
      if (nextRunTime) updateDetails.push(`下次 ${nextRunTime}`)
      const latestAt = health?.last_attempt_at || health?.last_success_at
      const fetchBusy = entry.fetchLabel !== '立即获取'
      const notificationDisabled = !editable
        || !source.enabled
        || !subscription.enabled
        || subscription.analysis_mode === 'personal_only'
        || entry.notificationPending
      const notificationSelected = source.enabled
        && subscription.enabled
        && subscription.analysis_mode !== 'personal_only'
        && Boolean(subscription.notify_on_new_items)
      return <Card
        key={subscription.id}
        role="listitem"
        aria-label={`${source.display_name} 订阅来源`}
        data-compact-source-row="subscription"
        variant="secondary"
        className="min-w-0 max-w-full border border-separator bg-surface-secondary p-3 shadow-none"
      >
        <div data-source-card-header className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-2">
          <div className="min-w-0 flex-1">
            <SourceIdentity source={source} detail={`${sourceTypeLabel(effectiveSourceType(source))} · ${sourceScopeLabel(source.scope)}`} />
          </div>
          <div data-source-card-status className="grid shrink-0 justify-items-end gap-1">
            <SourceHealthStatus health={health} canRetry={editable} canEdit={entry.canEdit} />
            <dl data-source-counts className="flex min-w-0 items-center justify-end gap-2 text-muted">
              <div className="type-meta flex items-baseline gap-1 whitespace-nowrap">
                <dt>今日</dt><dd className="type-label text-foreground">{health?.today_item_count ?? 0}</dd>
              </div>
              <div className="type-meta flex items-baseline gap-1 whitespace-nowrap">
                <dt>近{feedWindowDays}天</dt><dd className="type-label text-foreground">{health?.feed_item_count ?? health?.current_item_count ?? 0}</dd>
              </div>
              <div className="type-meta flex items-baseline gap-1 whitespace-nowrap">
                <dt>历史</dt>
                <dd>{(health?.history_item_count ?? 0) > 0
                  ? <Link
                    to={`/history?source_id=${encodeURIComponent(source.id)}`}
                    aria-label={`查看 ${source.display_name} 的 ${health?.history_item_count ?? 0} 条历史内容`}
                    className="type-label rounded text-accent underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-focus"
                  >{health?.history_item_count ?? 0}</Link>
                  : <span className="type-label text-foreground">0</span>}</dd>
              </div>
            </dl>
          </div>
        </div>
        <div className="mt-2 grid min-w-0 gap-2 border-t border-separator pt-2 min-[560px]:grid-cols-[minmax(0,1fr)_auto] min-[560px]:items-center">
          <div data-source-update-metadata className="type-meta flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-muted min-[680px]:flex-nowrap">
            {updateDetails.map((detail, index) => <span key={detail} className="whitespace-nowrap">
              {index > 0 && <span className="mr-2" aria-hidden="true">·</span>}
              {detail}
            </span>)}
            <span aria-hidden="true">·</span>
            <time
              dateTime={latestAt || undefined}
              aria-label={`最近更新 ${formatUpdateTime(latestAt)}，上次抓取 ${health?.last_fetched_count ?? 0} 条`}
              title={`上次抓取 ${health?.last_fetched_count ?? 0} 条`}
              className="whitespace-nowrap"
            >{formatUpdateTime(latestAt)}</time>
          </div>
          <div data-source-card-controls className="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
            <Tooltip delay={250}>
              <TooltipTriggerButton
                role="switch"
                aria-label={`新内容通知：${source.display_name}`}
                aria-checked={notificationSelected}
                aria-busy={entry.notificationPending}
                aria-disabled={notificationDisabled}
                className={`size-8 shrink-0 rounded-lg pointer-coarse:size-11 ${notificationSelected ? 'bg-accent/15 text-accent hover:bg-accent/20' : 'text-muted hover:bg-default hover:text-foreground'} ${notificationDisabled ? 'cursor-not-allowed opacity-45' : ''}`}
                onClick={() => {
                  if (!notificationDisabled) onToggleNotification(entry, !notificationSelected)
                }}
              >
                {entry.notificationPending
                  ? <Icons.LoaderCircle size={15} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  : notificationSelected
                    ? <Icons.BellRing size={15} aria-hidden="true" />
                    : <Icons.Bell size={15} aria-hidden="true" />}
              </TooltipTriggerButton>
              <Tooltip.Content {...topAnchoredTooltipProps}>
                {notificationDisabled
                  ? notificationDisabledReason({ editable, source, subscription, pending: entry.notificationPending })
                  : notificationSelected
                    ? '新内容通知已开启，点击关闭'
                    : '新内容通知已关闭，点击开启'}
              </Tooltip.Content>
            </Tooltip>
            {entry.canEdit && <SourceEditAction
              source={source}
              onEditSource={(trigger) => onEditSource(source, trigger)}
            />}
            {entry.canShare && <SourceShareAction
              source={source}
              onShare={(trigger) => onShare(source, trigger)}
            />}
            <Tooltip delay={250}>
              <TooltipTriggerButton
                aria-label={`${editable ? '配置' : '查看'} ${source.display_name} 订阅`}
                className="size-8 shrink-0 rounded-lg text-muted hover:bg-default hover:text-foreground pointer-coarse:size-11"
                onClick={() => onEditSubscription(entry)}
              ><Icons.Settings2 size={15} aria-hidden="true" /></TooltipTriggerButton>
              <Tooltip.Content {...topAnchoredTooltipProps}>{editable ? '订阅设置' : '查看订阅'}</Tooltip.Content>
            </Tooltip>
            {editable && <Tooltip delay={250}>
              <span className="inline-flex" aria-busy={fetchBusy || undefined}>
                <TooltipTriggerButton
                  className="type-control min-h-8 min-w-[104px] gap-1.5 rounded-xl bg-accent px-3 text-accent-foreground hover:bg-accent/90 pointer-coarse:min-h-11"
                  aria-label={`${entry.fetchLabel} ${source.display_name}；上次抓取 ${health?.last_fetched_count ?? 0} 条；最近更新 ${formatUpdateTime(latestAt)}`}
                  disabled={fetchBusy}
                  onClick={() => onFetch(entry)}
                >
                  <Icons.RefreshCw className={fetchBusy ? 'animate-spin motion-reduce:animate-none' : ''} size={14} aria-hidden="true" />
                  <span>立即获取</span>
                </TooltipTriggerButton>
              </span>
              <Tooltip.Content {...topAnchoredTooltipProps}>上次抓取 {health?.last_fetched_count ?? 0} 条 · 最近更新 {formatUpdateTime(latestAt)}</Tooltip.Content>
            </Tooltip>}
            {entry.notificationPending && <span className="sr-only" role="status">正在保存 {source.display_name} 的新内容通知设置</span>}
            {fetchBusy && <span className="sr-only" role="status">{entry.fetchLabel} {source.display_name}</span>}
          </div>
        </div>
      </Card>
    })}
  </div>
}

function LibraryRows({ items, editable, onSubscribe, onUnsubscribe, onEditSource, onShare }: {
  items: LibraryViewEntry[]
  editable: boolean
  onSubscribe: (source: CatalogSource) => void
  onUnsubscribe: (entry: LibraryViewEntry) => void
  onEditSource: (source: CatalogSource, trigger: HTMLElement) => void
  onShare: (source: CatalogSource, trigger: HTMLElement) => void
}) {
  return <div role="list" aria-label="当前频道来源库" className="grid min-w-0 max-w-full gap-2">
    {items.map((entry) => {
      const { source } = entry
      return <Card
        key={source.id}
        role="listitem"
        aria-label={`${source.display_name} 来源`}
        data-compact-source-row="library"
        variant="secondary"
        className="min-w-0 max-w-full border border-separator bg-surface-secondary p-3 shadow-none"
      >
        <div data-source-card-header className="flex min-w-0 items-center gap-2">
          <div className="min-w-0 flex-1">
            <SourceIdentity source={source} detail={`${sourceTypeLabel(effectiveSourceType(source))} · ${source.description || '暂无说明'}`} />
          </div>
          <MetaTag icon={source.scope === 'private' ? <Icons.Lock size={12} aria-hidden="true" /> : <Icons.Globe2 size={12} aria-hidden="true" />}>
            {sourceScopeLabel(source.scope)}
          </MetaTag>
        </div>
        <div data-source-card-controls className="mt-2 flex min-w-0 flex-wrap items-center justify-end gap-2 border-t border-separator pt-2">
          {entry.canEdit && <SourceEditAction
            source={source}
            onEditSource={(trigger) => onEditSource(source, trigger)}
          />}
          {entry.canShare && <SourceShareAction
            source={source}
            onShare={(trigger) => onShare(source, trigger)}
          />}
          {entry.subscribed ? <Button
            size="sm"
            variant="ghost"
            aria-label={`${entry.unsubscribePending ? '取消中' : '取消订阅'} ${source.display_name}`}
            isDisabled={!editable || !entry.subscription || entry.unsubscribePending}
            onPress={() => onUnsubscribe(entry)}
          >{entry.unsubscribePending ? '取消中' : '取消订阅'}</Button> : <Button
            size="sm"
            aria-label={`${entry.subscribePending ? '订阅中' : '订阅'} ${source.display_name}`}
            isDisabled={!editable || entry.subscribePending}
            onPress={() => onSubscribe(source)}
          >{entry.subscribePending ? '订阅中' : '订阅'}</Button>}
        </div>
      </Card>
    })}
  </div>
}

export function SubscriptionListView({ items, editable, feedWindowDays = 7, globalSchedule, schedule, onFetch, onToggleNotification, onEditSubscription, onEditSource, onShare }: {
  items: SubscriptionViewEntry[]
  editable: boolean
  feedWindowDays?: number
  globalSchedule?: FeedSchedule
  schedule: ReactNode
  onFetch: (entry: SubscriptionViewEntry) => void
  onToggleNotification: (entry: SubscriptionViewEntry, enabled: boolean) => void
  onEditSubscription: (entry: SubscriptionViewEntry) => void
  onEditSource: (source: CatalogSource, trigger: HTMLElement) => void
  onShare: (source: CatalogSource, trigger: HTMLElement) => void
}) {
  return <section data-subscription-list-workspace aria-label="我的订阅列表" className="grid min-w-0 max-w-full gap-3">
    {schedule}
    {items.length > 0 ? <SubscriptionRows
      items={items}
      editable={editable}
      feedWindowDays={feedWindowDays}
      globalSchedule={globalSchedule}
      onFetch={onFetch}
      onToggleNotification={onToggleNotification}
      onEditSubscription={onEditSubscription}
      onEditSource={onEditSource}
      onShare={onShare}
    /> : <Card variant="transparent" className="p-6 text-center">
      <Card.Title>没有匹配的订阅</Card.Title>
      <Card.Description className="mt-1">调整搜索或筛选，或前往来源库选择要关注的来源。</Card.Description>
    </Card>}
  </section>
}

export function SourceLibraryChannelView({ groups, selectedChannel, onSelectChannel, editable, hasSources, onSubscribe, onUnsubscribe, onEditSource, onShare }: {
  groups: ChannelViewGroup<LibraryViewEntry>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  editable: boolean
  hasSources: boolean
  onSubscribe: (source: CatalogSource) => void
  onUnsubscribe: (entry: LibraryViewEntry) => void
  onEditSource: (source: CatalogSource, trigger: HTMLElement) => void
  onShare: (source: CatalogSource, trigger: HTMLElement) => void
}) {
  return <ChannelLayout
    groups={groups}
    selectedChannel={selectedChannel}
    onSelectChannel={onSelectChannel}
    viewLabel="来源库"
    selectorLabel="频道"
    channelDetail={(items) => `${items.filter((item) => item.subscribed).length}/${items.length} 已订阅`}
    channelSummary={(items) => `${items.length} 个来源 · ${items.filter((item) => item.subscribed).length} 个已订阅`}
    emptyTitle={hasSources ? '没有匹配的来源' : '来源库还是空的'}
    emptyDescription={hasSources ? '调整搜索或筛选后重试。' : '创建来源后，它会按默认频道出现在这里。'}
    renderList={(items) => <LibraryRows
      items={items}
      editable={editable}
      onSubscribe={onSubscribe}
      onUnsubscribe={onUnsubscribe}
      onEditSource={onEditSource}
      onShare={onShare}
    />}
  />
}
