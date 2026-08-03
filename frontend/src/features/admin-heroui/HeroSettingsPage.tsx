import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  StorageOperation,
  StoragePlan,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  actionToast,
  Button,
  Card,
  Icons,
  Input,
  Label,
  LoadingState,
  PageFrame,
  TextField,
} from '../../design-system'
import { canAdministerWorkspace } from '../settings/settingsModel'
import { HeroApifyActorRouteSettings } from '../apify-actors/HeroApifyActorRouteSettings'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'
import { HeroTopicLibrary } from './HeroTopicLibrary'
import { legacySettingsSectionFromHash, legacySettingsSectionsForRole } from './settingsSections'

const recordOf = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}
const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
const errorMessage = (caught: unknown, fallback: string) => caught instanceof ApiError
  ? caught.message
  : caught instanceof Error && caught.message
    ? caught.message
    : fallback
type CoreSettingsSection = 'rsshub' | 'filtering' | 'topics'
type CoreSettingsBundle = Partial<Record<CoreSettingsSection, Record<string, unknown>>>
type CoreSettingsSave = {
  sections: CoreSettingsSection[]
  payload: CoreSettingsBundle
  revisions: Record<CoreSettingsSection, number>
}

const coreSettingsOrder: CoreSettingsSection[] = ['rsshub', 'filtering', 'topics']

function formatDateTime(value: string | null): string {
  if (!value) return '尚未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function FormField({ label, name, defaultValue = '', type = 'text', min, max, required = false }: {
  label: string; name: string; defaultValue?: string | number; type?: string; min?: number; max?: number; required?: boolean
}) {
  return <TextField fullWidth name={name} defaultValue={String(defaultValue)} isRequired={required}><Label>{label}</Label><Input type={type} min={min} max={max} /></TextField>
}

const storageOperationLabels: Record<StorageOperation, string> = {
  cleanup: '标准清理',
  archive: '转入冷归档',
  restore: '恢复归档',
  delete_archive: '永久删除归档',
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: index ? 1 : 0 }).format(value / (1024 ** index))} ${units[index]}`
}

function StorageArchiveSettings({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [activePlan, setActivePlan] = useState<StoragePlan | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const summary = useQuery({
    queryKey: queryKeys.storageSummary(user.id),
    queryFn: ({ signal }) => api.storageSummary(signal),
    enabled: queryEnabled,
  })
  const archives = useQuery({
    queryKey: queryKeys.storageArchives(user.id),
    queryFn: ({ signal }) => api.storageArchives(signal),
    enabled: queryEnabled,
  })
  const preview = useMutation({
    mutationFn: ({ operation, payload = {} }: {
      operation: StorageOperation
      payload?: Record<string, unknown>
    }) => api.createStoragePlan(operation, payload),
    onSuccess: (plan) => {
      setConfirmation('')
      setActivePlan(plan)
    },
  })
  const apply = useMutation({
    mutationFn: ({ plan, confirmationText }: {
      plan: StoragePlan
      confirmationText: string
    }) => api.applyStoragePlan(plan.id, confirmationText),
    onSuccess: (plan) => {
      setActivePlan(plan)
      setConfirmation('')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.storageSummary(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.storageArchives(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.feedRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.historyRoot(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.searchRoot(user.id) }),
      ])
      actionToast.success(`${storageOperationLabels[plan.operation]}已完成`)
    },
  })
  const previewData = recordOf(activePlan?.payload.preview)
  const previewCounts = recordOf(previewData.counts)
  const requiredConfirmation = String(previewData.required_confirmation ?? '')
  const cleanupCandidateCount = Object.values(previewCounts).reduce<number>(
    (sum, value) => sum + Number(value || 0),
    0,
  )
  const activePlanHasWork = activePlan?.operation === 'cleanup'
    ? cleanupCandidateCount > 0
    : activePlan?.operation === 'archive'
      ? Number(previewData.item_count ?? 0) > 0
      : true
  const planPending = preview.isPending || apply.isPending
  const planError = preview.isError
    ? errorMessage(preview.error, '生成预演失败，请稍后重试。')
    : apply.isError
      ? errorMessage(apply.error, '执行计划失败，所有候选项均保持不变。')
      : ''

  function previewPlan(operation: StorageOperation, batchId?: string) {
    preview.reset()
    apply.reset()
    setActivePlan(null)
    setConfirmation('')
    preview.mutate({
      operation,
      payload: batchId ? { batch_id: batchId } : {},
    })
  }

  return <div className="grid gap-4">
    {summary.isPending
      ? <LoadingState label="正在读取存储状态" rows={2} />
      : summary.isError
        ? <HeroNotice title="存储状态读取失败" status="warning">
          <Button size="sm" variant="ghost" onPress={() => void summary.refetch()}>重试此区域</Button>
        </HeroNotice>
        : summary.data && <>
          {!summary.data.readiness.ready && <HeroNotice title="迁移尚未完成" status="warning">
            必须先完成 Feed Storage v3 与时间索引 v11 的带备份迁移，之后才能生成清理或归档计划。
          </HeroNotice>}
          <div className="grid gap-3 min-[560px]:grid-cols-2 min-[920px]:grid-cols-4">
            <Card variant="secondary" className="p-4">
              <Card.Description>稳定内容</Card.Description>
              <Card.Title className="mt-1">{summary.data.counts.content_total} 条</Card.Title>
              <p className="type-meta mt-1 text-muted">在线 {summary.data.counts.content_online} · 冷归档 {summary.data.counts.content_archived}</p>
            </Card>
            <Card variant="secondary" className="p-4">
              <Card.Description>数据库</Card.Description>
              <Card.Title className="mt-1">{formatBytes(summary.data.bytes.database)}</Card.Title>
              <p className="type-meta mt-1 text-muted">Feed 快照 {summary.data.counts.feed_snapshots}</p>
            </Card>
            <Card variant="secondary" className="p-4">
              <Card.Description>在线媒体</Card.Description>
              <Card.Title className="mt-1">{formatBytes(summary.data.bytes.media)}</Card.Title>
              <p className="type-meta mt-1 text-muted">{summary.data.counts.media_assets} 个资源</p>
            </Card>
            <Card variant="secondary" className="p-4">
              <Card.Description>归档文件</Card.Description>
              <Card.Title className="mt-1">{formatBytes(summary.data.bytes.archives)}</Card.Title>
              <p className="type-meta mt-1 text-muted">{summary.data.counts.archive_batches} 个批次</p>
            </Card>
          </div>
          <Card variant="transparent" className="p-4">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <Card.Title>安全治理</Card.Title>
                <Card.Description className="mt-1">
                  清理只处理紧凑快照、完成任务、缓存、使用记录和孤立媒体；正文与媒体满 {summary.data.policy.archive_after_days} 天后可转冷归档，永不自动永久删除。
                </Card.Description>
                <p className="type-meta mt-2 text-muted">最近清理：{formatDateTime(summary.data.last_cleanup_at)}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  isDisabled={!summary.data.readiness.ready || planPending}
                  onPress={() => previewPlan('cleanup')}
                ><Icons.BrushCleaning size={15} aria-hidden="true" />预演标准清理</Button>
                <Button
                  size="sm"
                  variant="secondary"
                  isDisabled={!summary.data.readiness.ready || planPending}
                  onPress={() => previewPlan('archive')}
                ><Icons.Archive size={15} aria-hidden="true" />预演 90 日归档</Button>
              </div>
            </div>
          </Card>
        </>}

    {preview.isPending && <LoadingState label="正在计算候选项，不会修改数据" rows={1} />}
    {activePlan && activePlan.status === 'previewed' && <HeroNotice
      title={`${storageOperationLabels[activePlan.operation]}预演`}
      status={activePlan.operation === 'delete_archive' ? 'warning' : 'default'}
      role="status"
    >
      <div className="grid gap-3">
        {activePlan.operation === 'cleanup' && <p>
          预计清理 {cleanupCandidateCount} 条轻量运行记录；稳定内容永久删除数为 0。
        </p>}
        {activePlan.operation === 'archive' && <p>
          预计归档 {Number(previewData.item_count ?? 0)} 条内容、{Number(previewData.media_count ?? 0)} 个媒体文件。收藏、稍后读和待通知内容已排除。
        </p>}
        {activePlan.operation === 'restore' && <p>
          将校验并恢复 {Number(previewData.item_count ?? 0)} 条内容、{Number(previewData.media_count ?? 0)} 个媒体文件。
        </p>}
        {activePlan.operation === 'delete_archive' && <>
          <p>这是不可恢复的所有者操作。归档已先恢复到在线存储，预计释放 {formatBytes(Number(previewData.byte_size ?? 0))}。</p>
          <TextField fullWidth value={confirmation} onChange={setConfirmation}>
            <Label>输入确认文本</Label>
            <Input placeholder={requiredConfirmation} />
          </TextField>
        </>}
        <p className="type-meta text-muted">预演有效至 {formatDateTime(activePlan.expires_at)}；执行前会再次核对候选指纹。</p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={activePlan.operation === 'delete_archive' ? 'danger' : 'primary'}
            isDisabled={!activePlanHasWork || planPending || (activePlan.operation === 'delete_archive' && confirmation !== requiredConfirmation)}
            onPress={() => apply.mutate({ plan: activePlan, confirmationText: confirmation })}
          >{!activePlanHasWork ? '无需执行' : apply.isPending ? '执行中…' : `执行${storageOperationLabels[activePlan.operation]}`}</Button>
          <Button size="sm" variant="ghost" isDisabled={planPending} onPress={() => {
            setActivePlan(null)
            setConfirmation('')
          }}>取消</Button>
        </div>
      </div>
    </HeroNotice>}
    {activePlan?.status === 'applied' && <HeroNotice title={`${storageOperationLabels[activePlan.operation]}已完成`} status="success">
      数据状态已刷新；完整结果已记录到审计计划。
    </HeroNotice>}
    {planError && <HeroNotice title="存储操作未完成" status="warning" role="alert">{planError}</HeroNotice>}

    <Card variant="transparent" className="p-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <Card.Title>冷归档批次</Card.Title>
          <Card.Description className="mt-1">管理员可预演恢复；只有所有者可在恢复完成后预演永久删除。</Card.Description>
        </div>
        <Button size="sm" variant="ghost" isDisabled={archives.isFetching} onPress={() => void archives.refetch()}>
          <Icons.RefreshCw size={14} className={archives.isFetching ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />
          刷新
        </Button>
      </div>
      {archives.isPending && <div className="mt-4"><LoadingState label="正在读取归档批次" rows={2} /></div>}
      {archives.isError && <div className="mt-4"><HeroNotice title="归档批次读取失败" status="warning" /></div>}
      {!archives.isPending && !archives.isError && !(archives.data?.archives.length) && <p className="type-meta mt-4 text-muted">尚无归档批次。</p>}
      <div className="mt-4 grid gap-2">
        {(archives.data?.archives ?? []).map((archive) => <div
          key={archive.id}
          className="flex flex-wrap items-center gap-3 rounded-xl border border-separator bg-surface-secondary p-3"
        >
          <div className="min-w-0 flex-1">
            <p className="type-control break-all">{archive.id}</p>
            <p className="type-meta mt-1 text-muted">
              {archive.item_count} 条 · {archive.media_count} 个媒体 · {formatBytes(archive.byte_size)} · {
                archive.status === 'committed' ? '已归档' : archive.status === 'restored' ? '已恢复' : archive.status === 'deleted' ? '已永久删除' : '失败'
              }
            </p>
          </div>
          {archive.status === 'committed' && <Button
            size="sm"
            variant="secondary"
            isDisabled={planPending}
            onPress={() => previewPlan('restore', archive.id)}
          ><Icons.RotateCcw size={14} aria-hidden="true" />预演恢复</Button>}
          {archive.status === 'restored' && user.role === 'owner' && <Button
            size="sm"
            variant="danger"
            isDisabled={planPending}
            onPress={() => previewPlan('delete_archive', archive.id)}
          ><Icons.Trash2 size={14} aria-hidden="true" />预演永久删除</Button>}
        </div>)}
      </div>
    </Card>
  </div>
}

export function HeroSettingsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const admin = canAdministerWorkspace(user)
  const [activeSection, setActiveSection] = useState<string>(
    () => legacySettingsSectionFromHash(location.hash, user.role)?.id ?? 'settings-fetching',
  )
  const [activatedSections, setActivatedSections] = useState<Set<string>>(
    () => new Set([legacySettingsSectionFromHash(location.hash, user.role)?.id ?? 'settings-fetching']),
  )
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const activeSectionRef = useRef(activeSection)
  const scrollActivationFrameRef = useRef<number | undefined>(undefined)
  const scrollUnlockFrameRef = useRef<number | undefined>(undefined)
  const scrollActivationPendingRef = useRef(false)
  const lastScrollTopRef = useRef(0)
  const lastTouchYRef = useRef<number | null>(null)
  const explicitSectionNavigationRef = useRef(Boolean(legacySettingsSectionFromHash(location.hash, user.role)))
  const configQueryEnabled = admin && activeSection === 'settings-fetching'
  const config = useQuery({
    queryKey: queryKeys.config(user.id),
    queryFn: ({ signal }) => api.config(signal),
    enabled: configQueryEnabled,
    staleTime: queryStaleTime.settings,
  })
  const [rssInitialFetchWindowOverride, setRssInitialFetchWindowOverride] = useState<string | null>(null)
  const [feedWindowDaysOverride, setFeedWindowDaysOverride] = useState<string | null>(null)
  const [topicsOverride, setTopicsOverride] = useState<string[] | null>(null)
  const [dirtyCoreSections, setDirtyCoreSections] = useState<Set<CoreSettingsSection>>(() => new Set())
  const coreRevisions = useRef<Record<CoreSettingsSection, number>>({
    rsshub: 0,
    filtering: 0,
    topics: 0,
  })
  const rsshubFormRef = useRef<HTMLFormElement>(null)
  const filteringFormRef = useRef<HTMLFormElement>(null)
  const filtering = recordOf(config.data?.config.filtering)
  const rssInitialFetchWindow = rssInitialFetchWindowOverride
    ?? String(filtering.rss_initial_fetch_window_hours ?? 168)
  const feedWindowDays = feedWindowDaysOverride
    ?? String(filtering.feed_window_days ?? 7)
  const rsshub = recordOf(config.data?.config.rsshub)
  const configuredTopics = useMemo(() => {
    const topics = config.data?.taxonomy?.topics ?? config.data?.config.tags ?? []
    return Array.isArray(topics) ? topics.filter((topic): topic is string => typeof topic === 'string') : []
  }, [config.data])
  const topicsDraft = topicsOverride ?? configuredTopics
  const topicsDraftRef = useRef(topicsDraft)
  useEffect(() => {
    topicsDraftRef.current = topicsDraft
  }, [topicsDraft])
  const rsshubAccessKeySet = (config.data?.env_status ?? []).some(
    (item) => item.name === 'RSSHUB_ACCESS_KEY' && item.set === true,
  )
  const sectionOptions = useMemo(() => legacySettingsSectionsForRole(user.role), [user.role])
  const settingsDirty = dirtyCoreSections.size > 0

  const activateSection = useCallback((id: string) => {
    activeSectionRef.current = id
    setActiveSection(id)
    setActivatedSections((current) => {
      if (current.has(id)) return current
      const next = new Set(current)
      next.add(id)
      return next
    })
  }, [])

  const scheduleAdjacentSectionActivation = useCallback((direction: -1 | 1) => {
    const root = scrollContainerRef.current
    if (!root || scrollActivationPendingRef.current) return
    const activeIndex = sectionOptions.findIndex((section) => section.id === activeSectionRef.current)
    const candidate = sectionOptions[activeIndex + direction]
    if (!candidate) return
    const candidateElement = document.getElementById(candidate.id)
    if (!candidateElement) return
    const rootRect = root.getBoundingClientRect()
    const candidateRect = candidateElement.getBoundingClientRect()
    const revealInset = Math.min(64, Math.max(24, rootRect.height / 8))
    const visibleEnough = (
      candidateRect.bottom >= rootRect.top + revealInset
      && candidateRect.top <= rootRect.bottom - revealInset
    )
    if (!visibleEnough) return

    scrollActivationPendingRef.current = true
    window.cancelAnimationFrame(scrollActivationFrameRef.current ?? 0)
    scrollActivationFrameRef.current = window.requestAnimationFrame(() => {
      activateSection(candidate.id)
      const nextUrl = `${window.location.pathname}${window.location.search}#${candidate.id}`
      window.history.replaceState(window.history.state, '', nextUrl)
      window.cancelAnimationFrame(scrollUnlockFrameRef.current ?? 0)
      scrollUnlockFrameRef.current = window.requestAnimationFrame(() => {
        lastScrollTopRef.current = root.scrollTop
        scrollActivationPendingRef.current = false
      })
    })
  }, [activateSection, sectionOptions])

  function updateCoreSectionDirty(section: CoreSettingsSection, dirty: boolean) {
    setDirtyCoreSections((current) => {
      if (dirty === current.has(section)) return current
      const next = new Set(current)
      if (dirty) next.add(section)
      else next.delete(section)
      return next
    })
  }

  function setCoreSectionDirty(section: CoreSettingsSection, dirty: boolean) {
    coreRevisions.current[section] += 1
    updateCoreSectionDirty(section, dirty)
  }

  function refreshCoreDirty(section: CoreSettingsSection) {
    coreRevisions.current[section] += 1
    window.requestAnimationFrame(() => {
      try {
        updateCoreSectionDirty(
          section,
          JSON.stringify(payloadFor(section)) !== JSON.stringify(configuredPayloadFor(section)),
        )
      } catch {
        updateCoreSectionDirty(section, true)
      }
    })
  }

  useEffect(() => {
    if (!settingsDirty) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [settingsDirty])

  useEffect(() => {
    const section = legacySettingsSectionFromHash(location.hash, user.role)
    if (!section) return
    explicitSectionNavigationRef.current = true
    const frame = window.requestAnimationFrame(() => {
      activateSection(section.id)
      const target = document.getElementById(section.id)
      target?.scrollIntoView?.({
        block: 'start',
        behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      })
      target?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [activateSection, location.hash, user.role])

  useEffect(() => {
    const root = scrollContainerRef.current
    if (!root) return
    lastScrollTopRef.current = root.scrollTop

    const nestedScrollConsumes = (target: EventTarget | null, direction: -1 | 1) => {
      let element = target instanceof HTMLElement ? target : null
      while (element && element !== root) {
        const overflowY = window.getComputedStyle(element).overflowY
        if (
          ['auto', 'scroll'].includes(overflowY)
          && element.scrollHeight > element.clientHeight
          && (
            (direction > 0 && element.scrollTop + element.clientHeight < element.scrollHeight - 1)
            || (direction < 0 && element.scrollTop > 1)
          )
        ) {
          return true
        }
        element = element.parentElement
      }
      return false
    }
    const keyboardTargetOwnsNavigation = (target: EventTarget | null) => (
      target instanceof HTMLElement
      && Boolean(target.closest('button, a, input, textarea, select, [contenteditable="true"], [role="combobox"], [role="listbox"], [role="menu"], [role="slider"], [role="spinbutton"]'))
    )
    const activateFromScroll = () => {
      const nextScrollTop = root.scrollTop
      const delta = nextScrollTop - lastScrollTopRef.current
      lastScrollTopRef.current = nextScrollTop
      if (explicitSectionNavigationRef.current) return
      if (Math.abs(delta) < 1) return
      scheduleAdjacentSectionActivation(delta > 0 ? 1 : -1)
    }
    const activateFromWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) < 1) return
      const direction = event.deltaY > 0 ? 1 : -1
      if (nestedScrollConsumes(event.target, direction)) return
      explicitSectionNavigationRef.current = false
      scheduleAdjacentSectionActivation(direction)
    }
    const rememberTouch = (event: TouchEvent) => {
      lastTouchYRef.current = event.touches[0]?.clientY ?? null
      explicitSectionNavigationRef.current = false
    }
    const activateFromTouch = (event: TouchEvent) => {
      const currentY = event.touches[0]?.clientY
      const previousY = lastTouchYRef.current
      if (currentY === undefined || previousY === null) return
      lastTouchYRef.current = currentY
      const delta = previousY - currentY
      if (Math.abs(delta) < 4) return
      const direction = delta > 0 ? 1 : -1
      if (nestedScrollConsumes(event.target, direction)) return
      scheduleAdjacentSectionActivation(direction)
    }
    const enableForKeyboardScroll = (event: KeyboardEvent) => {
      if (keyboardTargetOwnsNavigation(event.target)) return
      if (['ArrowDown', 'PageDown', 'End'].includes(event.key) || (event.key === ' ' && !event.shiftKey)) {
        explicitSectionNavigationRef.current = false
        scheduleAdjacentSectionActivation(1)
      } else if (['ArrowUp', 'PageUp', 'Home'].includes(event.key) || (event.key === ' ' && event.shiftKey)) {
        explicitSectionNavigationRef.current = false
        scheduleAdjacentSectionActivation(-1)
      }
    }
    const enableForScrollbarDrag = (event: PointerEvent) => {
      const rootRect = root.getBoundingClientRect()
      if (event.clientX >= rootRect.right - 20) {
        explicitSectionNavigationRef.current = false
      }
    }
    root.addEventListener('scroll', activateFromScroll, { passive: true })
    root.addEventListener('wheel', activateFromWheel, { passive: true })
    root.addEventListener('touchstart', rememberTouch, { passive: true })
    root.addEventListener('touchmove', activateFromTouch, { passive: true })
    root.addEventListener('keydown', enableForKeyboardScroll)
    root.addEventListener('pointerdown', enableForScrollbarDrag, { passive: true })
    return () => {
      root.removeEventListener('scroll', activateFromScroll)
      root.removeEventListener('wheel', activateFromWheel)
      root.removeEventListener('touchstart', rememberTouch)
      root.removeEventListener('touchmove', activateFromTouch)
      root.removeEventListener('keydown', enableForKeyboardScroll)
      root.removeEventListener('pointerdown', enableForScrollbarDrag)
    }
  }, [scheduleAdjacentSectionActivation])

  useEffect(() => () => {
    window.cancelAnimationFrame(scrollActivationFrameRef.current ?? 0)
    window.cancelAnimationFrame(scrollUnlockFrameRef.current ?? 0)
    scrollActivationPendingRef.current = false
  }, [])

  function jumpToSection(id: string) {
    if (!sectionOptions.some((section) => section.id === id)) return
    activateSection(id)
    if (location.hash === `#${id}`) {
      window.requestAnimationFrame(() => {
        const target = document.getElementById(id)
        target?.scrollIntoView?.({ block: 'start', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
        target?.focus({ preventScroll: true })
      })
      return
    }
    navigate({ pathname: location.pathname, search: location.search, hash: `#${id}` })
  }

  const configMutation = useMutation({
    mutationFn: ({ payload }: CoreSettingsSave) => api.configAction('set_settings_bundle', payload),
    onMutate: () => feedback.begin('config-save', 'set_settings_bundle'),
    onSuccess: (result, submitted) => {
      feedback.clear('config-save', 'set_settings_bundle')
      const savedWithoutNewerEdits = submitted.sections.filter(
        (section) => coreRevisions.current[section] === submitted.revisions[section],
      )
      setDirtyCoreSections((current) => {
        const next = new Set(current)
        savedWithoutNewerEdits.forEach((section) => next.delete(section))
        return next
      })
      if (savedWithoutNewerEdits.includes('filtering')) {
        setRssInitialFetchWindowOverride(null)
        setFeedWindowDaysOverride(null)
      }
      if (savedWithoutNewerEdits.includes('topics')) setTopicsOverride(null)
      if (result?.config) queryClient.setQueryData(queryKeys.config(user.id), result)
      actionToast.success(submitted.sections.length > 1 ? '全部配置已保存' : '设置已保存')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }),
        ...(submitted.sections.includes('filtering')
          ? [
              queryClient.invalidateQueries({ queryKey: queryKeys.feedRoot(user.id) }),
              queryClient.invalidateQueries({ queryKey: queryKeys.historyRoot(user.id) }),
              queryClient.invalidateQueries({ queryKey: queryKeys.searchRoot(user.id) }),
              queryClient.invalidateQueries({ queryKey: queryKeys.sourceHealth(user.id) }),
            ]
          : []),
      ])
    },
    onError: (caught) => {
      const message = errorMessage(caught, '设置保存失败。')
      feedback.clear('config-save', 'set_settings_bundle')
      actionToast.danger('设置保存失败', { description: message })
    },
  })

  function filteringPayload(): Record<string, unknown> {
    if (!filteringFormRef.current) throw new Error('获取设置表单尚未加载')
    const data = new FormData(filteringFormRef.current)
    return {
      ...filtering,
      time_window_hours: Number(data.get('time_window_hours')),
      feed_window_days: Number(data.get('feed_window_days')),
      rss_initial_fetch_window_hours: Number(data.get('rss_initial_fetch_window_hours')),
      recent_item_limit: Number(data.get('recent_item_limit')),
    }
  }

  function rsshubPayload(): Record<string, unknown> {
    if (!rsshubFormRef.current) throw new Error('RSSHub 设置表单尚未加载')
    return { base_url: inputValue(new FormData(rsshubFormRef.current), 'base_url') }
  }

  function reportSectionValidity(section: CoreSettingsSection): boolean {
    const form = section === 'rsshub'
      ? rsshubFormRef.current
      : section === 'filtering'
        ? filteringFormRef.current
        : null
    if (form && !form.checkValidity()) {
      form.reportValidity()
      form.querySelector<HTMLElement>(':invalid')?.focus()
      return false
    }
    return true
  }

  function payloadFor(section: CoreSettingsSection): Record<string, unknown> {
    if (section === 'rsshub') return rsshubPayload()
    if (section === 'filtering') return filteringPayload()
    return { topics: topicsDraftRef.current }
  }

  function configuredPayloadFor(section: CoreSettingsSection): Record<string, unknown> {
    if (section === 'rsshub') {
      return { base_url: String(rsshub.base_url ?? 'http://rsshub:1200').trim() }
    }
    if (section === 'filtering') {
      return {
        ...filtering,
        time_window_hours: Number(filtering.time_window_hours ?? 24),
        feed_window_days: Number(filtering.feed_window_days ?? 7),
        rss_initial_fetch_window_hours: Number(filtering.rss_initial_fetch_window_hours ?? 168),
        recent_item_limit: Number(filtering.recent_item_limit ?? 20),
      }
    }
    return { topics: configuredTopics }
  }

  function saveCoreSections(sections: CoreSettingsSection[]) {
    if (configMutation.isPending) return
    const orderedSections = coreSettingsOrder.filter((section) => sections.includes(section))
    if (!orderedSections.length) return
    for (const section of orderedSections) {
      if (!reportSectionValidity(section)) return
    }
    const payload: CoreSettingsBundle = {}
    for (const section of orderedSections) payload[section] = payloadFor(section)
    configMutation.mutate({
      sections: orderedSections,
      payload,
      revisions: { ...coreRevisions.current },
    })
  }

  function saveFiltering(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveCoreSections(['filtering'])
  }

  function saveRsshub(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveCoreSections(['rsshub'])
  }

  return <div ref={scrollContainerRef} data-settings-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="settings" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
    {settingsDirty && <div
      data-settings-dirty-notice
      className="fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-40 ml-auto max-w-md min-[768px]:bottom-4 min-[768px]:left-auto min-[768px]:right-4"
    >
      <HeroNotice title="有尚未保存的更改" status="warning" role="status">
        <div className="flex flex-wrap items-center gap-3">
          <span className="min-w-0 flex-1">
            {dirtyCoreSections.size} 项核心配置待保存。
          </span>
          {dirtyCoreSections.size > 0 && <Button
            size="sm"
            isDisabled={configMutation.isPending}
            onPress={() => saveCoreSections(coreSettingsOrder.filter((section) => dirtyCoreSections.has(section)))}
          ><Icons.Save size={15} aria-hidden="true" />{configMutation.isPending ? '保存中…' : '保存全部配置'}</Button>}
        </div>
      </HeroNotice>
    </div>}
    <div data-mobile-settings-selector className="min-[768px]:pointer-fine:hidden">
      <HeroSelect label="设置区域" value={activeSection} onChange={jumpToSection} options={[...sectionOptions]} className="w-full" />
    </div>
    <div className="grid min-w-0 gap-5">

    {admin && <>
      <AdminSection id="settings-fetching" title="获取与主题" description="控制抓取窗口和未来可选主题；兼容评分、精选与日报字段不在当前产品中显示。">
        {activatedSections.has('settings-fetching') && <>
        <HeroApifyActorRouteSettings queryEnabled={activeSection === 'settings-fetching'} />
        <div className="mt-6 border-t border-separator pt-5">
        {config.isPending
          ? <LoadingState label="正在读取获取与主题设置" rows={2} />
          : config.isError
            ? <HeroNotice title="获取与主题设置读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void config.refetch()}>重试此区域</Button></HeroNotice>
            : <>
        <div className="grid gap-3 border-b border-separator pb-5">
          <div>
            <h3 className="type-control">RSSHub 服务</h3>
            <p className="type-meta mt-1 text-muted">Bilibili 等受控路由统一使用此 Base URL，可填写自建、反向代理前缀或第三方 RSSHub。自建公网实例可通过 SecretStore 的 RSSHUB_ACCESS_KEY 启用访问控制；Worker 只发送路由级 code，OpenClaw 不接收地址或密钥。</p>
            <p className="type-meta mt-2 text-muted">RSSHub 访问密钥：{rsshubAccessKeySet ? '已配置' : '未配置（无鉴权第三方实例可留空）'}</p>
          </div>
          <form ref={rsshubFormRef} className="grid gap-4 min-[720px]:grid-cols-[minmax(0,1fr)_auto] min-[720px]:items-end" onChange={() => refreshCoreDirty('rsshub')} onSubmit={saveRsshub}>
            <FormField name="base_url" label="RSSHub Base URL" type="url" defaultValue={String(rsshub.base_url ?? 'http://rsshub:1200')} required />
            <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}>{configMutation.isPending && configMutation.variables?.sections.includes('rsshub') ? '保存中…' : '保存 RSSHub 地址'}</Button>
          </form>
        </div>
        <form ref={filteringFormRef} className="grid gap-4" onChange={() => refreshCoreDirty('filtering')} onSubmit={saveFiltering}>
          <div className="grid gap-4 min-[720px]:grid-cols-2 min-[1080px]:grid-cols-4">
            <FormField name="time_window_hours" label="日常抓取窗口（小时）" type="number" min={1} max={720} defaultValue={Number(filtering.time_window_hours ?? 24)} required />
            <HeroSelect
              name="feed_window_days"
              label="信息流活跃窗口"
              value={feedWindowDays}
              onChange={(value) => {
                setFeedWindowDaysOverride(value)
                refreshCoreDirty('filtering')
              }}
              description="按上海自然日划分 Feed 与历史；不改变抓取窗口，也不会删除内容。"
              options={[
                { id: '7', label: '近 7 天（默认）' },
                { id: '14', label: '近 14 天' },
                { id: '30', label: '近 30 天' },
              ]}
            />
            <HeroSelect
              name="rss_initial_fetch_window_hours"
              label="RSS 首次抓取窗口"
              value={rssInitialFetchWindow}
              onChange={(value) => {
                setRssInitialFetchWindowOverride(value)
                refreshCoreDirty('filtering')
              }}
              description="RSS 或 RSSHub 订阅在首次成功前使用该窗口；成功后恢复日常窗口。"
              options={[
                { id: '168', label: '7 天' },
                { id: '720', label: '30 天' },
              ]}
            />
            <FormField name="recent_item_limit" label="历史预览条数" type="number" min={1} max={200} defaultValue={Number(filtering.recent_item_limit ?? 20)} required />
          </div>
          <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}>{configMutation.isPending && configMutation.variables?.sections.includes('filtering') ? '保存中…' : '保存获取设置'}</Button>
        </form>
        <div className="mt-6 border-t border-separator pt-5"><h3 className="type-control mb-4">阅读主题库</h3><HeroTopicLibrary
          topics={configuredTopics}
          draft={topicsDraft}
          pending={configMutation.isPending}
          onDraftChange={(topics) => {
            setTopicsOverride(topics)
            setCoreSectionDirty('topics', JSON.stringify(topics) !== JSON.stringify(configuredTopics))
          }}
          onSave={() => saveCoreSections(['topics'])}
        /></div>
        </>}
        </div>
        </>}
      </AdminSection>

      <AdminSection id="settings-storage" title="存储与归档" description="预演工作区清理、90 日冷归档与恢复；所有操作均先核对候选指纹并记录审计。">
        {activatedSections.has('settings-storage') && <StorageArchiveSettings queryEnabled={activeSection === 'settings-storage'} />}
      </AdminSection>

    </>}
    </div>
  </PageFrame></div>
}
