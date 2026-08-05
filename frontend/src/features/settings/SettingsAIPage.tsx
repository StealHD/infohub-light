import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'

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
  StatusBadge,
} from '../../components/settings'
import {
  actionToast,
  Button,
  Card,
  Checkbox,
  Icons,
  Input,
  Label,
  LoadingState,
  PageFrame,
  StatusNotice,
  TextField,
} from '../../design-system'
import { HeroNotice, HeroSelect } from '../admin-heroui/HeroAdminControls'
import { aiDefaultsForProvider, canAdministerWorkspace } from './settingsModel'
import {
  aiSettingsOrder,
  buildAiPayload,
  buildFeedEndMessagesPayload,
  configuredAiPayload,
  configuredFeedEndMessagesPayload,
  recordOf,
  sameSettingsPayload,
  type AiDraft,
  type AiSettingsBundle,
  type AiSettingsSection,
} from './settingsAiModel'
import { preserveSettingsReturnState } from './settingsReturnState'

type AiSettingsSave = {
  sections: AiSettingsSection[]
  payload: AiSettingsBundle
  revisions: Record<AiSettingsSection, number>
}

const feedEndMessageStatusLabels: Record<string, string> = {
  disabled: '使用内置文案',
  pending: '等待 Worker 刷新',
  refreshing: '正在后台生成',
  ready: 'AI 文案可用',
  degraded: '生成失败，保留安全回退',
}

const feedEndMessageErrorLabels: Record<string, string> = {
  feed_end_messages_invalid_output: '模型输出未通过安全校验',
  feed_end_messages_timeout: '模型请求超过 60 秒',
  feed_end_messages_no_admin: '没有可归属生成用量的管理员',
  quota_exceeded: '工作区今日 AI 尝试额度已用尽',
  feed_end_messages_generation_failed: '模型请求失败',
  feed_end_messages_lease_lost: '生成租约已失效',
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

export function SettingsAIPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const admin = canAdministerWorkspace(user)
  const returnState = preserveSettingsReturnState(location.state)
  const config = useQuery({
    queryKey: queryKeys.config(user.id),
    queryFn: ({ signal }) => api.config(signal),
    enabled: admin,
    staleTime: queryStaleTime.settings,
  })
  const secrets = useQuery({
    queryKey: queryKeys.secrets(user.id),
    queryFn: ({ signal }) => api.secrets(signal),
    enabled: admin,
    staleTime: queryStaleTime.settings,
  })
  const feedEndMessagesStatus = useQuery({
    queryKey: queryKeys.feedEndMessages(user.id),
    queryFn: ({ signal }) => api.feedEndMessages(signal),
    enabled: admin,
    staleTime: queryStaleTime.settings,
    retry: false,
    refetchInterval: (query) => ['pending', 'refreshing'].includes(query.state.data?.status ?? '') ? 2_000 : false,
  })
  const [aiOverride, setAiOverride] = useState<AiDraft | null>(null)
  const [feedEndRefreshDaysOverride, setFeedEndRefreshDaysOverride] = useState<string | null>(null)
  const [feedEndStyleOverride, setFeedEndStyleOverride] = useState<string | null>(null)
  const [feedEndAiKeyEnvOverride, setFeedEndAiKeyEnvOverride] = useState<string | null>(null)
  const [expandedFeedEndScenes, setExpandedFeedEndScenes] = useState<Set<string>>(() => new Set())
  const [dirtySections, setDirtySections] = useState<Set<AiSettingsSection>>(() => new Set())
  const revisions = useRef<Record<AiSettingsSection, number>>({ ai: 0, feed_end_messages: 0 })
  const aiFormRef = useRef<HTMLFormElement>(null)
  const feedEndMessagesFormRef = useRef<HTMLFormElement>(null)

  const ai = recordOf(config.data?.config.ai)
  const configuredAiProvider = String(ai.provider ?? 'gemini')
  const configuredAiDefaults = aiDefaultsForProvider(configuredAiProvider)
  const configuredAiDraft: AiDraft = {
    provider: configuredAiProvider,
    model: String(ai.model ?? configuredAiDefaults.model),
    apiKeyEnv: String(ai.api_key_env ?? ''),
  }
  const aiDraft = aiOverride ?? configuredAiDraft
  const aiDraftRef = useRef(aiDraft)
  const feedEndMessages = recordOf(config.data?.config.feed_end_messages)
  const feedEndRefreshDays = feedEndRefreshDaysOverride ?? String(feedEndMessages.refresh_days ?? 7)
  const feedEndStyle = feedEndStyleOverride ?? String(feedEndMessages.style_preset ?? 'restrained')
  const feedEndAiKeyEnv = feedEndAiKeyEnvOverride ?? String(feedEndMessages.ai_key_env ?? '')
  const aiSecrets = (secrets.data?.secrets ?? []).filter((secret) => secret.kind === 'ai')
  const compatibleGlobalAiSecrets = aiSecrets.filter((secret) => secret.provider === aiDraft.provider)
  const compatibleFeedEndAiSecrets = aiSecrets.filter((secret) => secret.provider === aiDraft.provider)
  const selectedFeedEndAiSecret = aiSecrets.find((secret) => secret.env_name === feedEndAiKeyEnv)
  const feedEndKeyMismatch = Boolean(
    feedEndAiKeyEnv
    && (!selectedFeedEndAiSecret || selectedFeedEndAiSecret.provider !== aiDraft.provider),
  )
  const feedEndAiKeyOptions = [
    { id: '', label: '跟随全局 AI Key（默认）' },
    ...(feedEndKeyMismatch
      ? [{
          id: feedEndAiKeyEnv,
          label: selectedFeedEndAiSecret
            ? `${selectedFeedEndAiSecret.name} · 与当前 Provider 不兼容`
            : '当前绑定 Key 已不可用',
          description: '请改为跟随全局 Key，或选择同一 Provider 的已保存 Key。',
          isDisabled: true,
        }]
      : []),
    ...compatibleFeedEndAiSecrets.map((secret) => ({
      id: secret.env_name,
      label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}`,
      description: secret.base_url ? '使用 Key 的独立 Base URL' : '使用全局 Base URL',
    })),
  ]
  const savedFeedEndGenerationEnabled = ai.enabled !== false && feedEndMessages.ai_generation_enabled === true

  useLayoutEffect(() => {
    aiDraftRef.current = aiDraft
  }, [aiDraft])

  function updateDirty(section: AiSettingsSection, dirty: boolean) {
    setDirtySections((current) => {
      if (dirty === current.has(section)) return current
      const next = new Set(current)
      if (dirty) next.add(section)
      else next.delete(section)
      return next
    })
  }

  function payloadFor(section: AiSettingsSection): Record<string, unknown> {
    if (section === 'ai') {
      if (!aiFormRef.current) throw new Error('AI 设置表单尚未加载')
      return buildAiPayload({ form: aiFormRef.current, draft: aiDraftRef.current, configured: ai })
    }
    if (!feedEndMessagesFormRef.current) throw new Error('触底文案设置表单尚未加载')
    return buildFeedEndMessagesPayload(feedEndMessagesFormRef.current)
  }

  function configuredPayloadFor(section: AiSettingsSection): Record<string, unknown> {
    if (section === 'ai') return configuredAiPayload({ configured: ai, draft: configuredAiDraft })
    return configuredFeedEndMessagesPayload(feedEndMessages)
  }

  function refreshDirty(section: AiSettingsSection) {
    revisions.current[section] += 1
    window.requestAnimationFrame(() => {
      try {
        updateDirty(section, !sameSettingsPayload(payloadFor(section), configuredPayloadFor(section)))
      } catch {
        updateDirty(section, true)
      }
    })
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
    mutationFn: ({ payload }: AiSettingsSave) => api.configAction('set_settings_bundle', payload),
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
      if (savedWithoutNewerEdits.includes('ai')) setAiOverride(null)
      if (savedWithoutNewerEdits.includes('feed_end_messages')) {
        setFeedEndRefreshDaysOverride(null)
        setFeedEndStyleOverride(null)
        setFeedEndAiKeyEnvOverride(null)
      }
      if (result?.config) queryClient.setQueryData(queryKeys.config(user.id), result)
      actionToast.success(submitted.sections.length > 1 ? '全部配置已保存' : '设置已保存')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.feedEndMessages(user.id) }),
        ...(submitted.sections.includes('ai')
          ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorDiscoverySettings(user.id) })]
          : []),
      ])
    },
    onError: (caught) => {
      feedback.clear('config-save', 'set_settings_bundle')
      actionToast.danger('设置保存失败', { description: errorMessage(caught, '设置保存失败。') })
    },
  })
  const feedEndMessagesRefreshMutation = useMutation({
    mutationFn: () => api.refreshFeedEndMessages(),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.feedEndMessages(user.id), result)
      actionToast.success('已标记触底文案刷新', { description: 'Worker 会在普通任务队列空闲后处理。' })
    },
    onError: (caught) => actionToast.danger('触底文案刷新请求失败', {
      description: errorMessage(caught, '请稍后重试。'),
    }),
  })

  function reportValidity(section: AiSettingsSection): boolean {
    const form = section === 'ai' ? aiFormRef.current : feedEndMessagesFormRef.current
    if (form && !form.checkValidity()) {
      form.reportValidity()
      form.querySelector<HTMLElement>(':invalid')?.focus()
      return false
    }
    if (section === 'ai' && !aiDraft.apiKeyEnv.trim()) {
      document.getElementById('settings-ai')?.scrollIntoView({ block: 'start' })
      document.querySelector<HTMLElement>('[aria-label^="AI Key"]')?.focus()
      actionToast.warning('AI Key 不能为空', { description: '请选择已配置的 AI Key 后再保存。' })
      return false
    }
    return true
  }

  function saveSections(sections: AiSettingsSection[]) {
    if (configMutation.isPending) return
    const ordered = aiSettingsOrder.filter((section) => sections.includes(section))
    if (!ordered.length || ordered.some((section) => !reportValidity(section))) return
    const payload: AiSettingsBundle = {}
    ordered.forEach((section) => { payload[section] = payloadFor(section) })
    configMutation.mutate({ sections: [...ordered], payload, revisions: { ...revisions.current } })
  }

  function saveAi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveSections(['ai'])
  }

  function saveFeedEndMessages(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveSections(['feed_end_messages'])
  }

  return <div data-settings-page="ai" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      {dirtySections.size > 0 && <StatusNotice title="有尚未保存的更改" status="warning" role="status">
        <div className="flex flex-wrap items-center gap-3">
          <span className="min-w-0 flex-1">{dirtySections.size} 项设置待保存。</span>
          <Button size="sm" isDisabled={configMutation.isPending} onPress={() => saveSections([...dirtySections])}>
            <Icons.Save size={15} aria-hidden="true" />{configMutation.isPending ? '保存中…' : '保存全部配置'}
          </Button>
        </div>
      </StatusNotice>}

      <SettingsSection title="助手连接" description="本地助手通过只读 Remote MCP 使用当前账户的数据。">
        <SettingsGroup ariaLabel="助手连接">
          <SettingsItem
            label="Inteliscope 数据连接"
            description="管理本地助手的连接、授权范围与一次性令牌。"
            icon={<Icons.Bot size={17} aria-hidden="true" />}
            trailing={<Button size="sm" variant="ghost" onPress={() => navigate('/agents')}>管理连接</Button>}
          />
        </SettingsGroup>
      </SettingsSection>

      <SettingsSection id="settings-ai" title="工作区 AI" description="选择全局分析模型与 AI Key；Key 保存后永不回显。">
        {!admin && <SettingsGroup ariaLabel="工作区 AI 访问权限">
          <SettingsItem
            label="工作区设置只读"
            description="全局 AI、获取规则、主题、成员和 Key 仅 Owner/Admin 可管理；个人订阅参数仍可在订阅页维护。"
            icon={<Icons.LockKeyhole size={17} aria-hidden="true" />}
            trailing={<StatusBadge>只读</StatusBadge>}
          />
        </SettingsGroup>}
        {admin && (config.isPending || secrets.isPending
          ? <LoadingState label="正在读取 AI 设置" rows={2} />
          : config.isError || secrets.isError
            ? <StatusNotice title="AI 设置读取失败" status="warning">
              <Button size="sm" variant="ghost" onPress={() => { void config.refetch(); void secrets.refetch() }}>重试此区域</Button>
            </StatusNotice>
            : <SettingsGroup className="p-4 min-[640px]:p-5" ariaLabel="工作区 AI 配置">
              <form ref={aiFormRef} className="grid gap-4" onChange={() => refreshDirty('ai')} onSubmit={saveAi}>
                <Checkbox name="enabled" defaultSelected={ai.enabled !== false}>
                  <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用 AI 分析</Checkbox.Content>
                </Checkbox>
                <div className="grid gap-4 min-[720px]:grid-cols-3">
                  <HeroSelect label="Provider" value={aiDraft.provider} onChange={(nextProvider) => {
                    const defaults = aiDefaultsForProvider(nextProvider)
                    const compatibleSecrets = aiSecrets.filter((secret) => secret.provider === nextProvider)
                    const preferredSecret = compatibleSecrets.find((secret) => secret.env_name === defaults.apiKeyEnv) ?? compatibleSecrets[0]
                    setAiOverride({ provider: nextProvider, model: defaults.model, apiKeyEnv: preferredSecret?.env_name ?? '' })
                    refreshDirty('ai')
                  }} options={[{ id: 'gemini', label: 'Gemini' }, { id: 'openai', label: 'OpenAI' }, { id: 'anthropic', label: 'Anthropic' }, { id: 'deepseek', label: 'DeepSeek' }]} />
                  <TextField fullWidth value={aiDraft.model} onChange={(model) => {
                    setAiOverride({ ...aiDraft, model })
                    refreshDirty('ai')
                  }} isRequired><Label>模型</Label><Input /></TextField>
                  <HeroSelect label="AI Key" value={aiDraft.apiKeyEnv} onChange={(apiKeyEnv) => {
                    setAiOverride({ ...aiDraft, apiKeyEnv })
                    refreshDirty('ai')
                  }} options={[{ id: '', label: '请选择' }, ...compatibleGlobalAiSecrets.map((secret) => ({ id: secret.env_name, label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}`, description: secret.base_url ? '使用 Key 的独立 Base URL' : '使用全局 Base URL' }))]} />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" variant="ghost" onPress={() => navigate('/settings/secrets', { state: returnState })}>
                    <Icons.KeyRound size={15} aria-hidden="true" />管理密钥
                  </Button>
                  <span className="type-meta text-muted">仅显示 Key 元数据，不会显示真实值。</span>
                </div>
                <SettingsDisclosure title="高级配置" description="Base URL、输出语言与输入/输出长度限制。">
                  <div className="grid gap-4 min-[720px]:grid-cols-3">
                    <FormField name="base_url" label="Base URL" type="url" defaultValue={String(ai.base_url ?? '')} />
                    <FormField name="languages" label="输出语言" defaultValue={Array.isArray(ai.languages) ? ai.languages.join(',') : 'zh'} />
                    <FormField name="analysis_content_chars" label="正文输入字符" type="number" min={100} max={10000} defaultValue={Number(ai.analysis_content_chars ?? 1000)} />
                    <FormField name="analysis_comments_chars" label="评论输入字符" type="number" min={0} max={20000} defaultValue={Number(ai.analysis_comments_chars ?? 1500)} />
                    <FormField name="summary_max_chars" label="概括最多字符" type="number" min={100} max={500} defaultValue={Number(ai.summary_max_chars ?? 200)} />
                    <FormField name="analysis_max_output_tokens" label="最大输出 Token" type="number" min={256} max={2048} defaultValue={Number(ai.analysis_max_output_tokens ?? 800)} />
                  </div>
                </SettingsDisclosure>
                <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}>
                  <Icons.Save size={15} aria-hidden="true" />{configMutation.isPending && configMutation.variables?.sections.includes('ai') ? '保存中…' : '保存 AI 设置'}
                </Button>
              </form>
            </SettingsGroup>)}
      </SettingsSection>

      {admin && !config.isPending && !config.isError && <SettingsSection title="信息流触底文案" description="内置中文文案始终可用；启用后，Worker 会在普通任务队列空闲时生成三个共享场景。">
        <SettingsGroup className="p-4 min-[640px]:p-5" ariaLabel="触底文案设置">
          <form ref={feedEndMessagesFormRef} className="grid gap-4" onChange={() => refreshDirty('feed_end_messages')} onSubmit={saveFeedEndMessages}>
            <Checkbox name="ai_generation_enabled" defaultSelected={feedEndMessages.ai_generation_enabled === true}>
              <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用 AI 定期生成触底文案</Checkbox.Content>
            </Checkbox>
            <div className="grid gap-4 min-[720px]:grid-cols-3">
              <HeroSelect name="refresh_days" label="更新周期" value={feedEndRefreshDays} onChange={(value) => {
                setFeedEndRefreshDaysOverride(value)
                refreshDirty('feed_end_messages')
              }} options={[{ id: '1', label: '每天' }, { id: '7', label: '每 7 天（默认）' }, { id: '30', label: '每 30 天' }]} />
              <HeroSelect name="style_preset" label="文案风格" value={feedEndStyle} onChange={(value) => {
                setFeedEndStyleOverride(value)
                refreshDirty('feed_end_messages')
              }} options={[{ id: 'restrained', label: '克制（默认）' }, { id: 'warm', label: '温和' }, { id: 'light_humor', label: '轻幽默' }]} />
              <HeroSelect name="ai_key_env" label="生成用 AI Key" value={feedEndAiKeyEnv} onChange={(value) => {
                setFeedEndAiKeyEnvOverride(value)
                refreshDirty('feed_end_messages')
              }} options={feedEndAiKeyOptions} description={`仅显示与当前 ${aiDraft.provider} Provider 兼容的已保存 AI Key。`} errorMessage={feedEndKeyMismatch ? '当前绑定 Key 与全局 AI Provider 不匹配；请重新选择。' : undefined} />
              <FormField name="list_count" label="每场景条数" type="number" min={3} max={30} defaultValue={Number(feedEndMessages.list_count ?? 12)} required />
            </div>
            <TextField fullWidth name="style_prompt" defaultValue={String(feedEndMessages.style_prompt ?? '')}>
              <Label>自定义风格补充</Label>
              <Input maxLength={500} placeholder="可留空，最多 500 字；不能覆盖安全约束" />
            </TextField>
            <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}>
              <Icons.Save size={15} aria-hidden="true" />
              {configMutation.isPending && configMutation.variables?.sections.includes('feed_end_messages') ? '保存中…' : '保存触底文案设置'}
            </Button>
          </form>

          <Card variant="transparent" className="mt-5 border border-separator p-4">
            {feedEndMessagesStatus.isPending
              ? <LoadingState label="正在读取触底文案状态" rows={2} />
              : feedEndMessagesStatus.isError || !feedEndMessagesStatus.data
                ? <HeroNotice title="触底文案状态读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void feedEndMessagesStatus.refetch()}>重试状态读取</Button></HeroNotice>
                : <>
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <Card.Title>{feedEndMessageStatusLabels[feedEndMessagesStatus.data.status] ?? '状态未知'}</Card.Title>
                      <Card.Description className="mt-1">
                        来源：{feedEndMessagesStatus.data.source === 'ai' ? 'AI 文案池' : '内置文案'}
                        {' · '}generation {feedEndMessagesStatus.data.generation}
                        {' · '}最近生成 {formatDateTime(feedEndMessagesStatus.data.generated_at)}
                        {' · '}下次更新 {formatDateTime(feedEndMessagesStatus.data.next_refresh_at)}
                      </Card.Description>
                      {feedEndMessagesStatus.data.last_error_code && <p className="type-meta mt-2 text-warning">
                        {feedEndMessageErrorLabels[feedEndMessagesStatus.data.last_error_code] ?? '生成未成功，已保留安全文案。'}
                        {feedEndMessagesStatus.data.retry_at ? `；后台重试 ${formatDateTime(feedEndMessagesStatus.data.retry_at)}` : ''}
                      </p>}
                    </div>
                    <Button size="sm" variant="secondary" isDisabled={
                      !savedFeedEndGenerationEnabled
                      || feedEndMessagesRefreshMutation.isPending
                      || feedEndMessagesStatus.data.status === 'pending'
                      || feedEndMessagesStatus.data.status === 'refreshing'
                    } onPress={() => feedEndMessagesRefreshMutation.mutate()}>
                      <Icons.RefreshCw size={14} className={feedEndMessagesRefreshMutation.isPending ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />
                      {feedEndMessagesStatus.data.status === 'pending' ? '已等待刷新' : feedEndMessagesStatus.data.status === 'refreshing' ? '正在刷新' : '立即刷新'}
                    </Button>
                  </div>
                  {!savedFeedEndGenerationEnabled && <p className="type-meta mt-3 text-muted">保存并启用全局 AI 与触底文案生成后，才可请求立即刷新。</p>}
                  <div className="mt-4 grid gap-3 min-[720px]:grid-cols-3">
                    {([
                      ['empty', '空列表'],
                      ['first_end', '首次触底'],
                      ['repeat_end', '多次触底'],
                    ] as const).map(([scene, label]) => {
                      const messages = feedEndMessagesStatus.data.scenes[scene]
                      const expanded = expandedFeedEndScenes.has(scene)
                      const listId = `feed-end-messages-${scene}`
                      return <div key={scene} className="min-w-0 rounded-xl bg-surface-secondary p-3">
                        <div className="flex items-center justify-between gap-3">
                          <p className="type-control">{label}</p>
                          <div className="flex shrink-0 items-center gap-1">
                            <span className="type-meta text-muted">{messages.length} 条</span>
                            <Button size="sm" variant="ghost" aria-controls={listId} aria-expanded={expanded} aria-label={`${expanded ? '隐藏' : '展开'}${label}完整文案列表`} onPress={() => setExpandedFeedEndScenes((current) => {
                              const next = new Set(current)
                              if (next.has(scene)) next.delete(scene)
                              else next.add(scene)
                              return next
                            })}>{expanded ? '隐藏' : '展开'}</Button>
                          </div>
                        </div>
                        <ol id={listId} aria-label={`${label}完整文案列表`} className={`${expanded ? 'grid' : 'hidden'} mt-2 max-h-72 gap-1.5 overflow-y-auto rounded-lg pr-1 focus-visible:outline-2 focus-visible:outline-focus`} hidden={!expanded} tabIndex={0}>
                          {messages.map((message, index) => <li key={message} className="type-meta flex min-w-0 gap-2 text-muted">
                            <span className="w-5 shrink-0 text-right tabular-nums" aria-hidden="true">{index + 1}.</span>
                            <span className="min-w-0 break-words">{message}</span>
                          </li>)}
                        </ol>
                      </div>
                    })}
                  </div>
                </>}
          </Card>
        </SettingsGroup>
      </SettingsSection>}
    </PageFrame>
  </div>
}
