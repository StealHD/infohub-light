import { useRef, useState, type ReactNode } from 'react'

import type { CatalogSource, SourceHealthItem, SourceTypeDefinition, Subscription } from '../../api/types'
import {
  anchoredTooltipProps,
  Button,
  Card,
  Chip,
  Icons,
  Modal,
  Popover,
  SearchField,
  Tooltip,
  TooltipTriggerButton,
} from '../../design-system'
import {
  presentSourceHealthIssue,
  sourceScopeLabel,
  sourceTypeLabel,
  type HealthFilter,
} from '../subscriptions/subscriptionModel'
import { HeroSelect } from './HeroAdminControls'

export type FetchLabel = '提交中' | '已排队' | '获取中' | '立即获取'

export type SubscriptionViewEntry = {
  source: CatalogSource
  subscription: Subscription
  health?: SourceHealthItem
  channel: string
  fetchLabel: FetchLabel
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

type ChannelGroup<T> = {
  channel: string
  items: T[]
}

type FilterProps = {
  search: string
  onSearchChange: (value: string) => void
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
  groups: ChannelGroup<T>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  filters: FilterProps
  viewLabel: string
  channelDetail: (items: T[]) => string
  channelSummary: (items: T[]) => string
  beforeList?: ReactNode
  emptyTitle: string
  emptyDescription?: string
  renderList: (items: T[]) => ReactNode
}

type MoreActionsProps = {
  source: CatalogSource
  canEdit: boolean
  canShare: boolean
  onEditSource: () => void
  onShare: () => void
}

const healthLabel: Record<string, string> = {
  healthy: '正常',
  degraded: '需关注',
  failing: '连续失败',
  unknown: '尚未抓取',
}

const healthOptions = [
  { id: 'all', label: '全部健康状态' },
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

const sourceMark = (name: string) => {
  const normalized = name.trim().replace(/^[@#]/, '')
  return Array.from(normalized || '?').slice(0, 2).join('').toLocaleUpperCase()
}

function SourceIdentity({ source, detail }: { source: CatalogSource; detail: string }) {
  return <div className="flex min-w-0 items-center gap-3">
    <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent/10 type-label text-accent">
      {sourceMark(source.display_name)}
    </span>
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
  const chip = <Chip
    data-source-health-chip
    aria-label={`健康状态：${healthLabel[status]}`}
    size="sm"
    color={status === 'healthy' ? 'success' : status === 'failing' ? 'danger' : 'default'}
    variant="soft"
    className="shrink-0"
  ><Chip.Label>{healthLabel[status]}</Chip.Label></Chip>

  if (!health || !issue || !presentation) return chip
  const failureCount = Math.max(health.consecutive_failures || 0, 1)
  return <>
    <Tooltip delay={250}>
      <TooltipTriggerButton
        ref={triggerRef}
        className="h-auto min-h-0 rounded-full p-0"
        aria-label={`查看 ${healthLabel[status]} 详情`}
        onClick={() => setDetailsOpen(true)}
      >{chip}</TooltipTriggerButton>
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

function MoreActions({ source, canEdit, canShare, onEditSource, onShare }: MoreActionsProps) {
  const [open, setOpen] = useState(false)
  const closeThen = (action: () => void) => {
    setOpen(false)
    action()
  }

  if (!canEdit && !canShare) return null

  return <Popover isOpen={open} onOpenChange={setOpen}>
    <Popover.Trigger
      aria-label={`更多操作：${source.display_name}`}
      className="type-control inline-flex min-h-8 shrink-0 items-center gap-1 rounded-lg px-2 text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
    >
      更多<Icons.ChevronDown size={13} aria-hidden="true" />
    </Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} className="z-40 w-40 p-0">
      <Popover.Dialog aria-label={`${source.display_name} 更多操作`} className="grid gap-1 p-2">
        {canShare && <Button size="sm" variant="ghost" className="w-full justify-start" aria-label={`分享 ${source.display_name}`} onPress={() => closeThen(onShare)}>
          <Icons.Share2 size={14} aria-hidden="true" />分享来源
        </Button>}
        {canEdit && <Button size="sm" variant="ghost" className="w-full justify-start" aria-label={`编辑 ${source.display_name} 来源`} onPress={() => closeThen(onEditSource)}>
          <Icons.Pencil size={14} aria-hidden="true" />编辑来源
        </Button>}
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}

function ChannelSearch({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <SearchField aria-label="搜索来源" value={value} onChange={onChange} fullWidth>
    <SearchField.Group>
      <SearchField.SearchIcon><Icons.Search size={15} /></SearchField.SearchIcon>
      <SearchField.Input placeholder="搜索来源" />
      <SearchField.ClearButton />
    </SearchField.Group>
  </SearchField>
}

function ChannelFilterMenu({ filters, activeCount }: {
  filters: FilterProps
  activeCount: number
}) {
  const [open, setOpen] = useState(false)
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
      className="type-control inline-flex min-h-9 items-center gap-1.5 rounded-xl bg-default px-3 text-muted hover:bg-default/80 hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus"
    >
      <Icons.SlidersHorizontal size={15} aria-hidden="true" />
      筛选
      {activeCount > 0 && <span aria-label={`已启用 ${activeCount} 项筛选`} className="type-micro rounded-md bg-accent/15 px-1.5 text-accent">{activeCount}</span>}
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

function ChannelRail<T>({ groups, selectedChannel, onSelectChannel, detail, search, onSearchChange, viewLabel }: {
  groups: ChannelGroup<T>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  detail: (items: T[]) => string
  search: string
  onSearchChange: (value: string) => void
  viewLabel: string
}) {
  return <aside data-channel-rail className="sticky top-4 hidden self-start rounded-2xl border border-separator bg-surface-secondary p-3 min-[1200px]:block">
    <ChannelSearch value={search} onChange={onSearchChange} />
    <div className="type-label mb-1 mt-4 px-2 text-muted">频道</div>
    <nav aria-label={`${viewLabel}频道`} className="grid gap-1">
      {groups.map((group) => {
        const selected = group.channel === selectedChannel
        return <button
          key={group.channel}
          type="button"
          aria-pressed={selected}
          aria-label={`${group.channel}，${detail(group.items)}，${group.items.length} 个来源`}
          className={`grid min-h-14 w-full grid-cols-[36px_minmax(0,1fr)_auto] items-center gap-2 rounded-xl px-2 text-left transition-colors focus-visible:outline-2 focus-visible:outline-focus ${selected ? 'bg-accent/15 text-foreground ring-1 ring-inset ring-accent/25' : 'text-muted hover:bg-default hover:text-foreground'}`}
          onClick={() => onSelectChannel(group.channel)}
        >
          <span aria-hidden="true" className={`grid size-8 place-items-center rounded-lg type-label ${selected ? 'bg-accent/15 text-foreground' : 'bg-default text-muted'}`}>
            {group.channel === 'AI' ? 'AI' : Array.from(group.channel)[0]}
          </span>
          <span className="min-w-0">
            <span className="type-control block truncate">{group.channel}</span>
            <span className="type-meta block truncate text-muted">{detail(group.items)}</span>
          </span>
          <span className="type-meta tabular-nums">{group.items.length}</span>
        </button>
      })}
    </nav>
  </aside>
}

function ChannelHeader({ channel, summary, filterControl }: {
  channel: string
  summary: string
  filterControl: ReactNode
}) {
  return <Card data-channel-header variant="secondary" className="min-w-0 max-w-full border border-separator bg-surface-secondary p-4 shadow-none">
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <div className="type-label text-accent">当前频道</div>
        <h2 className="type-section-title mt-1 truncate">{channel}</h2>
        <p className="type-meta mt-1 text-muted">{summary}</p>
      </div>
      <div className="hidden shrink-0 min-[1200px]:block">{filterControl}</div>
    </div>
  </Card>
}

function ChannelLayout<T>({
  groups,
  selectedChannel,
  onSelectChannel,
  filters,
  viewLabel,
  channelDetail,
  channelSummary,
  beforeList,
  emptyTitle,
  emptyDescription,
  renderList,
}: ChannelLayoutProps<T>) {
  const activeCount = Number(filters.typeFilter !== 'all') + Number(filters.scopeFilter !== 'all') + Number(filters.includeHealth && filters.healthFilter !== 'all')
  const activeGroup = groups.find((group) => group.channel === selectedChannel) ?? groups[0]
  const controls = <div data-compact-channel-controls className="grid min-w-0 max-w-full gap-2 min-[1200px]:hidden">
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-2">
      <ChannelSearch value={filters.search} onChange={filters.onSearchChange} />
      <ChannelFilterMenu filters={filters} activeCount={activeCount} />
    </div>
    {activeGroup && <HeroSelect
      label="频道"
      value={activeGroup.channel}
      onChange={onSelectChannel}
      options={groups.map((group) => ({ id: group.channel, label: `${group.channel} · ${group.items.length}` }))}
    />}
  </div>

  return <>
    {controls}
    <div data-channel-workspace={viewLabel} className="grid min-w-0 max-w-full items-start gap-4 min-[1200px]:grid-cols-[236px_minmax(0,1fr)]">
      <ChannelRail
        groups={groups}
        selectedChannel={activeGroup?.channel ?? ''}
        onSelectChannel={onSelectChannel}
        detail={channelDetail}
        search={filters.search}
        onSearchChange={filters.onSearchChange}
        viewLabel={viewLabel}
      />
      <section aria-label={`${activeGroup?.channel ?? '无匹配频道'} ${viewLabel}`} className="grid min-w-0 max-w-full gap-3">
        <ChannelHeader
          channel={activeGroup?.channel ?? '无匹配频道'}
          summary={activeGroup ? channelSummary(activeGroup.items) : '调整搜索或筛选后重试'}
          filterControl={<ChannelFilterMenu filters={filters} activeCount={activeCount} />}
        />
        {beforeList}
        {activeGroup ? renderList(activeGroup.items) : <Card variant="transparent" className="p-6 text-center">
          <Card.Title>{emptyTitle}</Card.Title>
          {emptyDescription && <Card.Description className="mt-1">{emptyDescription}</Card.Description>}
        </Card>}
      </section>
    </div>
  </>
}

export function SubscriptionRows({ items, editable, onFetch, onEditSubscription, onEditSource, onShare }: {
  items: SubscriptionViewEntry[]
  editable: boolean
  onFetch: (entry: SubscriptionViewEntry) => void
  onEditSubscription: (entry: SubscriptionViewEntry) => void
  onEditSource: (source: CatalogSource) => void
  onShare: (source: CatalogSource) => void
}) {
  return <div role="list" aria-label="当前频道订阅" className="grid min-w-0 max-w-full gap-2">
    {items.map((entry) => {
      const { source, subscription, health } = entry
      const schedule = subscription.schedule
      const latestAt = health?.last_attempt_at || health?.last_success_at
      return <Card
        key={subscription.id}
        role="listitem"
        aria-label={`${source.display_name} 订阅来源`}
        data-compact-source-row="subscription"
        variant="secondary"
        className="min-w-0 max-w-full border border-separator bg-surface-secondary p-3 shadow-none"
      >
        <div className="flex min-w-0 items-start gap-2">
          <div className="min-w-0 flex-1">
            <SourceIdentity source={source} detail={`${sourceTypeLabel(source.type)} · ${sourceScopeLabel(source.scope)}`} />
          </div>
          {subscription.enabled && subscription.notify_on_new_items && subscription.analysis_mode !== 'personal_only' && <Chip size="sm" variant="soft"><Chip.Label>新内容通知</Chip.Label></Chip>}
          <SourceHealthStatus health={health} canRetry={editable} canEdit={entry.canEdit} />
          <MoreActions
            source={source}
            canEdit={entry.canEdit}
            canShare={entry.canShare}
            onEditSource={() => onEditSource(source)}
            onShare={() => onShare(source)}
          />
        </div>
        <div className="mt-2 grid gap-2 border-t border-separator pt-2 min-[680px]:grid-cols-[minmax(0,1fr)_auto] min-[680px]:items-center">
          <div className="type-meta flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-muted">
            <span>{schedule?.enabled ? intervalLabel(schedule.interval_minutes) : '手动更新'}</span>
            <span>{health?.last_fetched_count ?? 0} 条 · {formatCompactTime(latestAt)}</span>
            {schedule?.enabled && <span>{schedule.next_run_at ? `下次 ${formatCompactTime(schedule.next_run_at)}` : '等待下次更新'}</span>}
          </div>
          <div className="flex min-w-0 items-center justify-end gap-1.5">
            <Button size="sm" variant="ghost" aria-label={`${editable ? '配置' : '查看'} ${source.display_name} 订阅`} onPress={() => onEditSubscription(entry)}>
              {editable ? '订阅设置' : '查看订阅'}
            </Button>
            {editable && <Button size="sm" aria-label={`${entry.fetchLabel} ${source.display_name}`} isDisabled={entry.fetchLabel !== '立即获取'} onPress={() => onFetch(entry)}>
              <Icons.RefreshCw size={14} aria-hidden="true" />{entry.fetchLabel}
            </Button>}
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
  onEditSource: (source: CatalogSource) => void
  onShare: (source: CatalogSource) => void
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
        <div className="flex min-w-0 items-start gap-2">
          <div className="min-w-0 flex-1">
            <SourceIdentity source={source} detail={`${sourceTypeLabel(source.type)} · ${source.description || '暂无说明'}`} />
          </div>
          <Chip size="sm" variant="soft"><Chip.Label>{sourceScopeLabel(source.scope)}</Chip.Label></Chip>
          <MoreActions
            source={source}
            canEdit={entry.canEdit}
            canShare={entry.canShare}
            onEditSource={() => onEditSource(source)}
            onShare={() => onShare(source)}
          />
        </div>
        <div className="mt-2 flex min-w-0 flex-wrap items-center justify-between gap-2 border-t border-separator pt-2">
          <Chip size="sm" color={entry.subscribed ? 'success' : 'default'} variant="soft"><Chip.Label>{entry.subscribed ? '已订阅' : '未订阅'}</Chip.Label></Chip>
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

export function SubscriptionChannelView({ groups, selectedChannel, onSelectChannel, filters, editable, schedule, onFetch, onEditSubscription, onEditSource, onShare }: {
  groups: ChannelGroup<SubscriptionViewEntry>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  filters: FilterProps
  editable: boolean
  schedule: ReactNode
  onFetch: (entry: SubscriptionViewEntry) => void
  onEditSubscription: (entry: SubscriptionViewEntry) => void
  onEditSource: (source: CatalogSource) => void
  onShare: (source: CatalogSource) => void
}) {
  return <ChannelLayout
    groups={groups}
    selectedChannel={selectedChannel}
    onSelectChannel={onSelectChannel}
    filters={filters}
    viewLabel="我的订阅"
    channelDetail={(items) => {
      const problemCount = items.filter((item) => item.health?.status === 'degraded' || item.health?.status === 'failing').length
      const unknownCount = items.filter((item) => !item.health || item.health.status === 'unknown').length
      if (problemCount > 0) return `${problemCount} 个需处理`
      if (unknownCount > 0) return `${unknownCount} 个待检查`
      return '全部正常'
    }}
    channelSummary={(items) => {
      const healthyCount = items.filter((item) => item.health?.status === 'healthy').length
      const problemCount = items.filter((item) => item.health?.status === 'degraded' || item.health?.status === 'failing').length
      const unknownCount = items.filter((item) => !item.health || item.health.status === 'unknown').length
      return `${items.length} 个来源 · ${healthyCount} 个正常 · ${problemCount} 个需处理${unknownCount > 0 ? ` · ${unknownCount} 个待检查` : ''}`
    }}
    beforeList={schedule}
    emptyTitle="没有匹配的订阅"
    emptyDescription="调整搜索或筛选，或前往来源库选择要关注的来源。"
    renderList={(items) => <SubscriptionRows
      items={items}
      editable={editable}
      onFetch={onFetch}
      onEditSubscription={onEditSubscription}
      onEditSource={onEditSource}
      onShare={onShare}
    />}
  />
}

export function SourceLibraryChannelView({ groups, selectedChannel, onSelectChannel, filters, editable, hasSources, onSubscribe, onUnsubscribe, onEditSource, onShare }: {
  groups: ChannelGroup<LibraryViewEntry>[]
  selectedChannel: string
  onSelectChannel: (channel: string) => void
  filters: FilterProps
  editable: boolean
  hasSources: boolean
  onSubscribe: (source: CatalogSource) => void
  onUnsubscribe: (entry: LibraryViewEntry) => void
  onEditSource: (source: CatalogSource) => void
  onShare: (source: CatalogSource) => void
}) {
  return <ChannelLayout
    groups={groups}
    selectedChannel={selectedChannel}
    onSelectChannel={onSelectChannel}
    filters={filters}
    viewLabel="来源库"
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
