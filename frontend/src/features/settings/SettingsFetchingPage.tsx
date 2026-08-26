import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  SettingsDisclosure,
  SettingsGroup,
  SettingsItem,
  SettingsSection,
} from '../../components/settings'
import { actionToast, Button, Icons, Input, Label, LoadingState, PageFrame, StatusNotice, TextField } from '../../design-system'
import { HeroSelect } from '../admin-heroui/HeroAdminControls'
import { canAdministerWorkspace } from './settingsModel'
import { SettingsTopicLibrary } from './SettingsTopicLibrary'
import { RsshubServiceSettings } from './RsshubServiceSettings'
import {
  buildFilteringPayload,
  buildRsshubPayload,
  configuredFilteringPayload,
  configuredRsshubPayload,
  configuredTopics,
  fetchingSettingsOrder,
  recordOf,
  sameFetchingPayload,
  type FetchingSettingsBundle,
  type FetchingSettingsSection,
} from './settingsFetchingModel'
import { preserveSettingsReturnState } from './settingsReturnState'

type FetchingSettingsSave = {
  sections: FetchingSettingsSection[]
  payload: FetchingSettingsBundle
  revisions: Record<FetchingSettingsSection, number>
}

const errorMessage = (caught: unknown, fallback: string) => caught instanceof ApiError
  ? caught.message
  : caught instanceof Error && caught.message
    ? caught.message
    : fallback

function FormField({ label, name, defaultValue = '', type = 'text', min, max, required = false }: {
  label: string
  name: string
  defaultValue?: string | number
  type?: string
  min?: number
  max?: number
  required?: boolean
}) {
  return <TextField fullWidth name={name} defaultValue={String(defaultValue)} isRequired={required}>
    <Label>{label}</Label>
    <Input type={type} min={min} max={max} />
  </TextField>
}

export function SettingsFetchingPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const location = useLocation()
  const admin = canAdministerWorkspace(user)
  const returnState = preserveSettingsReturnState(location.state)
  const config = useQuery({
    queryKey: queryKeys.config(user.id),
    queryFn: ({ signal }) => api.config(signal),
    enabled: admin,
    staleTime: queryStaleTime.settings,
  })
  const [rssInitialFetchWindowOverride, setRssInitialFetchWindowOverride] = useState<string | null>(null)
  const [feedWindowDaysOverride, setFeedWindowDaysOverride] = useState<string | null>(null)
  const [topicsOverride, setTopicsOverride] = useState<string[] | null>(null)
  const [dirtySections, setDirtySections] = useState<Set<FetchingSettingsSection>>(() => new Set())
  const revisions = useRef<Record<FetchingSettingsSection, number>>({ rsshub: 0, filtering: 0, topics: 0 })
  const rsshubFormRef = useRef<HTMLFormElement>(null)
  const filteringFormRef = useRef<HTMLFormElement>(null)

  const workspaceConfig = useMemo(() => config.data?.config ?? {}, [config.data?.config])
  const filtering = recordOf(workspaceConfig.filtering)
  const rsshub = recordOf(workspaceConfig.rsshub)
  const savedTopics = useMemo(
    () => configuredTopics(workspaceConfig, config.data?.taxonomy?.topics),
    [config.data?.taxonomy?.topics, workspaceConfig],
  )
  const topicsDraft = topicsOverride ?? savedTopics
  const topicsDraftRef = useRef(topicsDraft)
  const rssInitialFetchWindow = rssInitialFetchWindowOverride ?? String(filtering.rss_initial_fetch_window_hours ?? 168)
  const feedWindowDays = feedWindowDaysOverride ?? String(filtering.feed_window_days ?? 7)

  useLayoutEffect(() => {
    topicsDraftRef.current = topicsDraft
  }, [topicsDraft])

  function updateDirty(section: FetchingSettingsSection, dirty: boolean) {
    setDirtySections((current) => {
      if (dirty === current.has(section)) return current
      const next = new Set(current)
      if (dirty) next.add(section)
      else next.delete(section)
      return next
    })
  }

  function payloadFor(section: FetchingSettingsSection): Record<string, unknown> {
    if (section === 'rsshub') {
      if (!rsshubFormRef.current) throw new Error('RSSHub 设置表单尚未加载')
      return buildRsshubPayload(rsshubFormRef.current)
    }
    if (section === 'filtering') {
      if (!filteringFormRef.current) throw new Error('获取设置表单尚未加载')
      return buildFilteringPayload({ form: filteringFormRef.current, configured: filtering })
    }
    return { topics: topicsDraftRef.current }
  }

  function configuredPayloadFor(section: FetchingSettingsSection): Record<string, unknown> {
    if (section === 'rsshub') return configuredRsshubPayload(rsshub)
    if (section === 'filtering') return configuredFilteringPayload(filtering)
    return { topics: savedTopics }
  }

  function refreshDirty(section: FetchingSettingsSection) {
    revisions.current[section] += 1
    updateDirty(section, true)
    window.requestAnimationFrame(() => {
      try {
        updateDirty(section, !sameFetchingPayload(payloadFor(section), configuredPayloadFor(section)))
      } catch {
        updateDirty(section, true)
      }
    })
  }

  function setTopicsDirty(topics: string[]) {
    revisions.current.topics += 1
    setTopicsOverride(topics)
    updateDirty('topics', !sameFetchingPayload({ topics }, { topics: savedTopics }))
  }

  useEffect(() => {
    if (!dirtySections.size) return
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [dirtySections.size])

  const configMutation = useMutation({
    mutationFn: ({ payload }: FetchingSettingsSave) => api.configAction('set_settings_bundle', payload),
    onMutate: () => feedback.begin('config-save', 'set_settings_bundle'),
    onSuccess: (result, submitted) => {
      feedback.clear('config-save', 'set_settings_bundle')
      const savedWithoutNewerEdits = submitted.sections.filter(
        (section) => revisions.current[section] === submitted.revisions[section],
      )
      setDirtySections((current) => {
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
      feedback.clear('config-save', 'set_settings_bundle')
      actionToast.danger('设置保存失败', { description: errorMessage(caught, '设置保存失败。') })
    },
  })

  function reportValidity(section: FetchingSettingsSection): boolean {
    const form = section === 'rsshub' ? rsshubFormRef.current : section === 'filtering' ? filteringFormRef.current : null
    if (form && !form.checkValidity()) {
      form.reportValidity()
      form.querySelector<HTMLElement>(':invalid')?.focus()
      return false
    }
    return true
  }

  function saveSections(sections: FetchingSettingsSection[]) {
    if (configMutation.isPending) return
    const ordered = fetchingSettingsOrder.filter((section) => sections.includes(section))
    if (!ordered.length || ordered.some((section) => !reportValidity(section))) return
    const payload: FetchingSettingsBundle = {}
    ordered.forEach((section) => { payload[section] = payloadFor(section) })
    configMutation.mutate({ sections: [...ordered], payload, revisions: { ...revisions.current } })
  }

  function saveRsshub(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveSections(['rsshub'])
  }

  function saveFiltering(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveSections(['filtering'])
  }

  if (!admin) return <Navigate to="/settings" state={returnState} replace />

  return <div data-settings-page="fetching" data-page-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      {dirtySections.size > 0 && <div className="sticky top-3 z-10"><StatusNotice title="有尚未保存的更改" status="warning" role="status">
        <div className="flex flex-wrap items-center gap-3">
          <span className="min-w-0 flex-1">{dirtySections.size} 项设置待保存。</span>
          <Button size="sm" isDisabled={configMutation.isPending} onPress={() => saveSections([...dirtySections])}>
            <Icons.Save size={15} aria-hidden="true" />{configMutation.isPending ? '保存中…' : '保存全部配置'}
          </Button>
        </div>
      </StatusNotice></div>}

      {config.isPending
        ? <LoadingState label="正在读取 RSSHub 设置" rows={2} />
        : config.isError
          ? <StatusNotice title="RSSHub 设置读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void config.refetch()}>重试此区域</Button></StatusNotice>
          : <RsshubServiceSettings
              baseUrl={String(rsshub.base_url ?? 'http://rsshub:1200')}
              formRef={rsshubFormRef}
              isSaving={configMutation.isPending && Boolean(configMutation.variables?.sections.includes('rsshub'))}
              onFormChange={() => refreshDirty('rsshub')}
              onSave={saveRsshub}
            />}

      <SettingsSection title="获取窗口" description="调整工作区抓取和 Feed 展示的时间范围；不会删除既有内容。">
        {config.isPending
          ? <LoadingState label="正在读取获取窗口" rows={2} />
          : config.isError
            ? <StatusNotice title="获取窗口读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void config.refetch()}>重试此区域</Button></StatusNotice>
            : <SettingsGroup ariaLabel="获取窗口">
              <SettingsItem label="抓取与展示范围" description="按上海自然日划分 Feed 与历史。" icon={<Icons.Clock3 size={17} aria-hidden="true" />}>
                <form ref={filteringFormRef} className="grid gap-4" onChange={() => refreshDirty('filtering')} onSubmit={saveFiltering}>
                  <div className="grid gap-4 min-[640px]:grid-cols-2 min-[960px]:grid-cols-4">
                    <FormField name="time_window_hours" label="日常抓取窗口（小时）" type="number" min={1} max={720} defaultValue={Number(filtering.time_window_hours ?? 24)} required />
                    <HeroSelect name="feed_window_days" label="信息流活跃窗口" value={feedWindowDays} onChange={(value) => { setFeedWindowDaysOverride(value); refreshDirty('filtering') }} options={[{ id: '7', label: '近 7 天（默认）' }, { id: '14', label: '近 14 天' }, { id: '30', label: '近 30 天' }]} />
                    <HeroSelect name="rss_initial_fetch_window_hours" label="RSS 首次抓取窗口" value={rssInitialFetchWindow} onChange={(value) => { setRssInitialFetchWindowOverride(value); refreshDirty('filtering') }} options={[{ id: '168', label: '7 天' }, { id: '720', label: '30 天' }]} />
                    <FormField name="recent_item_limit" label="历史预览条数" type="number" min={1} max={200} defaultValue={Number(filtering.recent_item_limit ?? 20)} required />
                  </div>
                  <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}>{configMutation.isPending && configMutation.variables?.sections.includes('filtering') ? '保存中…' : '保存获取设置'}</Button>
                </form>
                <SettingsDisclosure title="窗口说明" description="首次抓取和日常抓取采用不同范围。" className="mt-4">
                  <p className="type-body text-muted">RSS 或 RSSHub 订阅在首次成功前使用首次抓取窗口；成功后恢复日常窗口。信息流活跃窗口只影响 Feed 与历史展示，不改变抓取窗口。</p>
                </SettingsDisclosure>
              </SettingsItem>
            </SettingsGroup>}
      </SettingsSection>

      <SettingsSection title="阅读主题库" description="主题只影响未来候选和 AI 分类，不会改写已有订阅或历史内容。">
        {config.isPending
          ? <LoadingState label="正在读取主题库" rows={2} />
          : config.isError
            ? <StatusNotice title="主题库读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void config.refetch()}>重试此区域</Button></StatusNotice>
            : <SettingsGroup ariaLabel="阅读主题库">
              <SettingsItem label="工作区主题" description="新增或删除后单独保存。" icon={<Icons.Tags size={17} aria-hidden="true" />}>
                <SettingsTopicLibrary topics={savedTopics} draft={topicsDraft} pending={configMutation.isPending} onDraftChange={setTopicsDirty} onSave={() => saveSections(['topics'])} />
              </SettingsItem>
            </SettingsGroup>}
      </SettingsSection>
    </PageFrame>
  </div>
}
