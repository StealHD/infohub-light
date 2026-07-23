import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { SecretRef } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  Button,
  Card,
  Checkbox,
  FieldError,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  Table,
  TextField,
  toast,
} from '../../design-system'
import {
  aiDefaultsForProvider,
  canAdministerWorkspace,
  secretPresentation,
  settingsDataReady,
} from '../settings/settingsModel'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'
import { HeroTopicLibrary } from './HeroTopicLibrary'

const recordOf = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}
const inputValue = (data: FormData, key: string) => String(data.get(key) ?? '').trim()
const errorMessage = (caught: unknown, fallback: string) => caught instanceof ApiError
  ? caught.message
  : caught instanceof Error && caught.message
    ? caught.message
    : fallback
const secretEnvPattern = /^[A-Za-z_][A-Za-z0-9_]*$/
const secretProviders: Record<string, string[]> = {
  ai: ['gemini', 'openai', 'anthropic', 'deepseek'],
  apify: ['apify'],
}
const secretQuotaStaleTime = 5 * 60 * 1000

type SecretDraft = {
  name: string
  kind: string
  provider: string
  envName: string
  value: string
}

type SecretField = keyof SecretDraft
type SecretFieldErrors = Partial<Record<SecretField, string>>

function validateSecretDraft(draft: SecretDraft): SecretFieldErrors {
  const errors: SecretFieldErrors = {}
  const provider = draft.provider.trim().toLowerCase()
  if (!draft.name.trim()) errors.name = 'Key 名称不能为空。'
  if (!secretProviders[draft.kind]) errors.kind = '请选择有效的 Key 类型。'
  if (!provider) {
    errors.provider = 'Provider 不能为空。'
  } else if (!secretProviders[draft.kind]?.includes(provider)) {
    errors.provider = draft.kind === 'apify'
      ? 'Apify Key 的 Provider 必须是 apify。'
      : 'AI Key 的 Provider 仅支持 gemini、openai、anthropic 或 deepseek。'
  }
  if (!draft.envName.trim()) {
    errors.envName = '环境变量名不能为空。'
  } else if (!secretEnvPattern.test(draft.envName.trim())) {
    errors.envName = '环境变量名必须以字母或下划线开头，且只能包含字母、数字和下划线。'
  }
  if (!draft.value) {
    errors.value = 'Key 值不能为空。'
  } else if (draft.value.includes('\r') || draft.value.includes('\n') || draft.value.includes('\u0000')) {
    errors.value = 'Key 值必须为不含换行或空字符的单行文本。'
  } else if (draft.value.length > 4096) {
    errors.value = 'Key 值不能超过 4096 个字符。'
  }
  return errors
}

function secretCreateErrorMessage(caught: unknown): string {
  if (!(caught instanceof ApiError)) {
    return caught instanceof Error && caught.message
      ? `网络请求失败：${caught.message}。请检查连接后重试。`
      : '网络请求失败，请检查连接后重试。'
  }
  if (caught.code === 'secret_env_conflict') return '环境变量名已被其他 Key 使用，请更换后重试。'
  if (caught.code === 'invalid_secret') {
    if (/provider/i.test(caught.message)) return 'Provider 与 Key 类型不匹配，请检查后重试。'
    if (/env|environment/i.test(caught.message)) return '环境变量名格式无效，请使用字母或下划线开头。'
    if (/empty|required/i.test(caught.message)) return '必填内容不能为空，请补充后重试。'
    if (/single|line|null/i.test(caught.message)) return 'Key 值必须为不含换行或空字符的单行文本。'
    if (/4096|exceed/i.test(caught.message)) return 'Key 值不能超过 4096 个字符。'
    return 'Key 元数据或值格式无效，请检查后重试。'
  }
  return caught.action ? `${caught.message} ${caught.action}` : caught.message
}

const formatUsd = (value: number) => new Intl.NumberFormat('zh-CN', {
  style: 'currency',
  currency: 'USD',
  currencyDisplay: 'narrowSymbol',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
}).format(value)

function formatCycleEnd(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未知'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(date)
}

function FormField({ label, name, defaultValue = '', type = 'text', min, max, required = false }: {
  label: string; name: string; defaultValue?: string | number; type?: string; min?: number; max?: number; required?: boolean
}) {
  return <TextField fullWidth name={name} defaultValue={String(defaultValue)} isRequired={required}><Label>{label}</Label><Input type={type} min={min} max={max} /></TextField>
}

function SecretQuotaCell({ secret, userId }: { secret: SecretRef; userId: string }) {
  const { api } = useAppContext()
  const supported = secret.kind === 'apify' && secret.provider === 'apify'
  const quota = useQuery({
    queryKey: queryKeys.secretQuota(userId, secret.id),
    // Keep one shared in-flight lookup across React StrictMode's development remount.
    queryFn: () => api.secretQuota(secret.id),
    enabled: supported && secret.is_set,
    staleTime: secretQuotaStaleTime,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  if (!supported) return <span className="type-meta text-muted">暂不支持查询</span>
  if (!secret.is_set) return <span className="type-meta text-muted">Key 未配置，无法查询</span>
  if (quota.isPending) return <span className="type-meta text-muted" aria-live="polite">正在查询额度…</span>
  if (quota.isError) {
    return <div className="min-w-56" role="alert">
      <p className="type-meta text-danger">{errorMessage(quota.error, '额度查询失败，请稍后重试。')}</p>
      <Button
        className="mt-1"
        size="sm"
        variant="ghost"
        aria-label={`重试 ${secret.name} 额度`}
        isDisabled={quota.isFetching}
        onPress={() => void quota.refetch()}
      ><Icons.RefreshCw size={14} aria-hidden="true" />{quota.isFetching ? '重试中…' : '重试'}</Button>
    </div>
  }
  if (!quota.data) return <span className="type-meta text-muted">暂无额度数据</span>

  return <div className="min-w-64" aria-live="polite">
    <p className="type-control">套餐剩余 {formatUsd(quota.data.remaining_included_credits_usd)}</p>
    <p className="type-meta mt-1 text-muted">
      本月已用 {formatUsd(quota.data.monthly_usage_usd)} · 硬上限剩余 {formatUsd(quota.data.remaining_hard_limit_usd)}
    </p>
    <div className="mt-1 flex items-center gap-2">
      <span className="type-meta text-muted">周期至 {formatCycleEnd(quota.data.cycle_end_at)}</span>
      <Button
        size="sm"
        variant="ghost"
        isIconOnly
        aria-label={`刷新 ${secret.name} 额度`}
        isDisabled={quota.isFetching}
        onPress={() => void quota.refetch()}
      ><Icons.RefreshCw size={14} aria-hidden="true" /></Button>
    </div>
  </div>
}

function SecretRowActions({ secret, onChanged }: {
  secret: SecretRef
  onChanged: (secretId: string, action: 'rotate' | 'delete') => void
}) {
  const { api } = useAppContext()
  const feedback = useActionFeedback()
  const [value, setValue] = useState('')
  const [rotateOpen, setRotateOpen] = useState(false)
  const [rotateError, setRotateError] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const rotateTriggerRef = useRef<HTMLButtonElement>(null)
  const deleteTriggerRef = useRef<HTMLButtonElement>(null)
  const rotating = feedback.isPending('secret-rotate', secret.id)
  const removing = feedback.isPending('secret-delete', secret.id)

  function closeRotateDialog() {
    setRotateOpen(false)
    setRotateError('')
    setValue('')
    queueMicrotask(() => rotateTriggerRef.current?.focus())
  }

  function closeDeleteDialog() {
    setDeleteOpen(false)
    setDeleteError('')
    queueMicrotask(() => deleteTriggerRef.current?.focus())
  }

  async function rotate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitted = value
    setValue('')
    setRotateError('')
    if (!submitted) {
      setRotateError('新 Key 值不能为空。')
      return
    }
    feedback.begin('secret-rotate', secret.id)
    try {
      await api.rotateSecret(secret.id, submitted)
      feedback.succeed('secret-rotate', secret.id, `${secret.name} 已轮换。`)
      closeRotateDialog()
      toast.success('Key 已轮换', { description: secret.name, timeout: 4000 })
      onChanged(secret.id, 'rotate')
    } catch (caught) {
      const message = errorMessage(caught, '轮换失败，请稍后重试。')
      setRotateError(message)
      feedback.fail('secret-rotate', secret.id, message)
    }
  }

  async function remove() {
    setDeleteError('')
    feedback.begin('secret-delete', secret.id)
    try {
      await api.deleteSecret(secret.id)
      feedback.succeed('secret-delete', secret.id, `${secret.name} 已删除。`)
      closeDeleteDialog()
      toast.success('Key 已删除', { description: secret.name, timeout: 4000 })
      onChanged(secret.id, 'delete')
    } catch (caught) {
      const message = errorMessage(caught, '删除失败。')
      setDeleteError(message)
      feedback.fail('secret-delete', secret.id, message)
    }
  }

  return <div className="flex min-w-40 flex-wrap gap-2">
    <Modal isOpen={rotateOpen} onOpenChange={(open) => {
      if (rotating) return
      setRotateOpen(open)
      if (!open) {
        setRotateError('')
        setValue('')
        queueMicrotask(() => rotateTriggerRef.current?.focus())
      }
    }}>
      <Button ref={rotateTriggerRef} size="sm" type="button" variant="ghost" aria-label={`轮换 ${secret.name}`}>轮换</Button>
      <Modal.Backdrop isDismissable={!rotating} isKeyboardDismissDisabled={rotating}>
        <Modal.Container>
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>{`轮换 ${secret.name}`}</Modal.Heading></Modal.Header>
            <Modal.Body>
              <form id={`rotate-secret-${secret.id}`} className="grid gap-3" onSubmit={rotate}>
                <TextField fullWidth value={value} onChange={setValue} isRequired>
                  <Label>新 Key 值</Label>
                  <Input type="password" autoComplete="new-password" placeholder="粘贴新 Key（不会回显）" />
                </TextField>
                {rotateError && <HeroNotice title={rotateError} />}
              </form>
            </Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={rotating} onPress={closeRotateDialog}>取消轮换</Button>
              <Button type="submit" form={`rotate-secret-${secret.id}`} isDisabled={rotating}>
                {rotating ? '轮换中…' : '确认轮换'}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
    <Modal isOpen={deleteOpen} onOpenChange={(open) => {
        if (removing) return
        setDeleteOpen(open)
        if (!open) {
          setDeleteError('')
          queueMicrotask(() => deleteTriggerRef.current?.focus())
        }
      }}>
        <Button ref={deleteTriggerRef} size="sm" type="button" variant="danger" aria-label={`删除 ${secret.name}`} isDisabled={secret.used_by.length > 0 || removing}>删除</Button>
        <Modal.Backdrop isDismissable={!removing} isKeyboardDismissDisabled={removing}>
          <Modal.Container>
            <Modal.Dialog>
              <Modal.Header><Modal.Heading>{`删除 ${secret.name}？`}</Modal.Heading></Modal.Header>
              <Modal.Body>
                <p>删除后无法恢复；如需再次使用，必须重新添加 Key。</p>
                {deleteError && <div className="mt-3"><HeroNotice title={deleteError} /></div>}
              </Modal.Body>
              <Modal.Footer>
                <Button type="button" variant="ghost" isDisabled={removing} onPress={closeDeleteDialog}>取消删除</Button>
                <Button type="button" variant="danger" isDisabled={removing} onPress={() => void remove()}>{removing ? '删除中…' : '确认删除'}</Button>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
  </div>
}

export function HeroSettingsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const admin = canAdministerWorkspace(user)
  const config = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal) })
  const ignored = useQuery({ queryKey: queryKeys.ignored(user.id), queryFn: ({ signal }) => api.ignoredFeed(200, 0, signal) })
  const secrets = useQuery({ queryKey: queryKeys.secrets(user.id), queryFn: ({ signal }) => api.secrets(signal), enabled: admin })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [aiOverride, setAiOverride] = useState<{ provider: string; model: string; apiKeyEnv: string } | null>(null)
  const [secretDraft, setSecretDraft] = useState<SecretDraft>({ name: '', kind: 'ai', provider: '', envName: '', value: '' })
  const [secretFieldErrors, setSecretFieldErrors] = useState<SecretFieldErrors>({})
  const [secretFormError, setSecretFormError] = useState('')
  const ai = recordOf(config.data?.config.ai)
  const configuredAiProvider = String(ai.provider ?? 'gemini')
  const configuredAiDefaults = aiDefaultsForProvider(configuredAiProvider)
  const configuredAiDraft = {
    provider: configuredAiProvider,
    model: String(ai.model ?? configuredAiDefaults.model),
    apiKeyEnv: String(ai.api_key_env ?? ''),
  }
  const aiDraft = aiOverride ?? configuredAiDraft
  const filtering = recordOf(config.data?.config.filtering)

  function clearSecretFieldError(field: SecretField) {
    setSecretFieldErrors((current) => {
      if (!current[field]) return current
      const next = { ...current }
      delete next[field]
      return next
    })
    setSecretFormError('')
  }

  function secretChanged(secretId: string, action: 'rotate' | 'delete') {
    if (action === 'rotate') {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.secretQuota(user.id, secretId) }),
      ])
      return
    }
    queryClient.removeQueries({ queryKey: queryKeys.secretQuota(user.id, secretId) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) })
  }

  const configMutation = useMutation({
    mutationFn: ({ action, payload }: { action: string; payload: Record<string, unknown> }) => api.configAction(action, payload),
    onMutate: ({ action }) => feedback.begin('config-save', action),
    onSuccess: (_result, { action }) => { feedback.succeed('config-save', action); setMessage('设置已保存。'); setError(''); void queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }) },
    onError: (caught, { action }) => { const message = errorMessage(caught, '设置保存失败。'); setError(message); feedback.fail('config-save', action, message) },
  })
  const restoreMutation = useMutation({
    mutationFn: (articleId: string) => api.updateItemState(articleId, { dismissed: false }),
    onSuccess: async (_result, articleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.ignored(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }) }),
      ])
      const restored = ignored.data?.items.find((item) => item.id === articleId)
      toast.success('已恢复到信息流', { description: restored?.presentation?.content?.title || restored?.title, timeout: 4000 })
    },
    onError: (caught) => toast.danger('恢复失败', { description: errorMessage(caught, '请稍后重试。'), timeout: 8000 }),
  })

  async function createSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitted = { name: secretDraft.name.trim(), kind: secretDraft.kind, provider: secretDraft.provider.trim(), env_name: secretDraft.envName.trim(), value: secretDraft.value }
    setSecretDraft((current) => ({ ...current, value: '' }))
    setSecretFieldErrors({})
    setSecretFormError('')
    const fieldErrors = validateSecretDraft(secretDraft)
    if (Object.keys(fieldErrors).length) {
      const message = Object.values(fieldErrors)[0] ?? '请检查 Key 表单。'
      setSecretFieldErrors(fieldErrors)
      setSecretFormError('请修正标出的字段后重试。')
      feedback.fail('secret-create', 'new', message)
      toast.danger('新增 Key 失败', { description: message, timeout: 8000 })
      return
    }
    feedback.begin('secret-create', 'new')
    try {
      await api.createSecret(submitted)
      setSecretDraft({ name: '', kind: 'ai', provider: '', envName: '', value: '' })
      setSecretFieldErrors({})
      setSecretFormError('')
      feedback.succeed('secret-create', 'new', 'Key 已安全保存。')
      setMessage('Key 已保存，页面不会回显真实值。')
      toast.success('Key 已安全保存', { timeout: 4000 })
      void queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) })
    } catch (caught) {
      const message = secretCreateErrorMessage(caught)
      setSecretFormError(message)
      feedback.fail('secret-create', 'new', message)
      toast.danger('新增 Key 失败', { description: message, timeout: 8000 })
    }
  }


  function saveAi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    configMutation.mutate({ action: 'set_ai', payload: {
      enabled: data.has('enabled'), provider: aiDraft.provider, model: aiDraft.model, api_key_env: aiDraft.apiKeyEnv, base_url: inputValue(data, 'base_url'), languages: inputValue(data, 'languages') || 'zh',
      analysis_content_chars: Number(data.get('analysis_content_chars')), analysis_comments_chars: Number(data.get('analysis_comments_chars')), summary_max_chars: Number(data.get('summary_max_chars')), analysis_max_output_tokens: Number(data.get('analysis_max_output_tokens')), enrichment_content_chars: Number(ai.enrichment_content_chars ?? 4000),
    } })
  }

  function saveFiltering(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    configMutation.mutate({ action: 'set_filtering', payload: {
      ...filtering,
      time_window_hours: Number(data.get('time_window_hours')),
      recent_item_limit: Number(data.get('recent_item_limit')),
    } })
  }

  const ready = settingsDataReady({ admin, configLoaded: config.isSuccess, secretsLoaded: secrets.isSuccess })
  if (!ready) return <PageFrame width="admin" className="p-5">{config.isError || secrets.isError ? <HeroNotice title="设置读取失败" /> : <LoadingState label="正在读取设置" rows={1} />}</PageFrame>

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
    {message && <HeroNotice title={message} status="success" role="status" />}{error && <HeroNotice title={error} />}

    <AdminSection title="关于 Inteliscope" description="查看近期的重要功能、交互和可用性变化。">
      <Button size="sm" variant="secondary" onPress={() => navigate('/changelog')}><Icons.ScrollText size={16} aria-hidden="true" />查看更新日志</Button>
    </AdminSection>

    <AdminSection title="助手与 AI" description="本地助手通过只读 Remote MCP 使用当前账户的数据。">
      <Button size="sm" variant="secondary" onPress={() => navigate('/agents')}><Icons.Bot size={16} />管理助手连接</Button>
      {!admin && <Card variant="transparent" className="mt-4 p-4"><Card.Title>工作区设置只读</Card.Title><Card.Description className="mt-1">全局 AI、获取规则、主题、成员和 Key 仅 Owner/Admin 可管理；个人订阅参数仍可在订阅页维护。</Card.Description></Card>}
      {admin && <form className="mt-5 grid gap-4" onSubmit={saveAi}>
        <Checkbox name="enabled" defaultSelected={ai.enabled !== false}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用 AI 分析</Checkbox.Content></Checkbox>
        <div className="grid gap-4 min-[720px]:grid-cols-3">
          <HeroSelect label="Provider" value={aiDraft.provider} onChange={(nextProvider) => {
            const defaults = aiDefaultsForProvider(nextProvider)
            const available = (secrets.data?.secrets ?? []).some((secret) => secret.kind === 'ai' && secret.env_name === defaults.apiKeyEnv)
            setAiOverride({ provider: nextProvider, model: defaults.model, apiKeyEnv: available ? defaults.apiKeyEnv : aiDraft.apiKeyEnv })
          }} options={[{ id: 'gemini', label: 'Gemini' }, { id: 'openai', label: 'OpenAI' }, { id: 'anthropic', label: 'Anthropic' }, { id: 'deepseek', label: 'DeepSeek' }]} />
          <TextField fullWidth value={aiDraft.model} onChange={(model) => setAiOverride({ ...aiDraft, model })} isRequired><Label>模型</Label><Input /></TextField>
          <HeroSelect label="AI Key" value={aiDraft.apiKeyEnv} onChange={(apiKeyEnv) => setAiOverride({ ...aiDraft, apiKeyEnv })} options={[{ id: '', label: '请选择' }, ...(secrets.data?.secrets ?? []).filter((secret) => secret.kind === 'ai').map((secret) => ({ id: secret.env_name, label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}` }))]} />
          <FormField name="base_url" label="Base URL" type="url" defaultValue={String(ai.base_url ?? '')} />
          <FormField name="languages" label="输出语言" defaultValue={Array.isArray(ai.languages) ? ai.languages.join(',') : 'zh'} />
          <FormField name="analysis_content_chars" label="正文输入字符" type="number" min={100} max={10000} defaultValue={Number(ai.analysis_content_chars ?? 1000)} />
          <FormField name="analysis_comments_chars" label="评论输入字符" type="number" min={0} max={20000} defaultValue={Number(ai.analysis_comments_chars ?? 1500)} />
          <FormField name="summary_max_chars" label="概括最多字符" type="number" min={100} max={500} defaultValue={Number(ai.summary_max_chars ?? 200)} />
          <FormField name="analysis_max_output_tokens" label="最大输出 Token" type="number" min={256} max={2048} defaultValue={Number(ai.analysis_max_output_tokens ?? 800)} />
        </div>
        <Button className="w-fit" type="submit" isDisabled={feedback.isPending('config-save', 'set_ai')}><Icons.Save size={15} />{feedback.isPending('config-save', 'set_ai') ? '保存中…' : '保存 AI 设置'}</Button>
      </form>}
    </AdminSection>

    <AdminSection title="已忽略内容" description="忽略后的信息只在这里恢复，不会继续占用日常浏览空间。">
      {ignored.isLoading && <LoadingState label="正在读取已忽略内容" rows={2} />}
      {ignored.isError && <HeroNotice title="已忽略内容读取失败" />}
      {!ignored.isLoading && !ignored.data?.items.length && <Card variant="transparent" className="p-4"><Card.Title>暂无已忽略内容</Card.Title></Card>}
      <div className="grid gap-2">{(ignored.data?.items ?? []).map((item) => <Card key={item.id} variant="transparent" className="flex-row items-center gap-3 p-3">
        <div className="min-w-0 flex-1"><Card.Title className="truncate">{item.presentation?.content?.title || item.title || '无标题内容'}</Card.Title><Card.Description className="truncate">{item.presentation?.source?.name || item.source || '未知来源'}</Card.Description></div>
        <Button size="sm" variant="ghost" isDisabled={restoreMutation.isPending && restoreMutation.variables === item.id} onPress={() => restoreMutation.mutate(item.id)}>{restoreMutation.isPending && restoreMutation.variables === item.id ? '恢复中…' : '恢复'}</Button>
      </Card>)}</div>
    </AdminSection>

    {admin && <>
      <AdminSection title="获取与主题" description="控制抓取窗口和未来可选主题；兼容评分、精选与日报字段不在当前产品中显示。">
        <form className="grid gap-4" onSubmit={saveFiltering}><div className="grid gap-4 min-[720px]:grid-cols-2"><FormField name="time_window_hours" label="抓取窗口（小时）" type="number" min={1} max={720} defaultValue={Number(filtering.time_window_hours ?? 24)} /><FormField name="recent_item_limit" label="历史预览条数" type="number" min={1} max={200} defaultValue={Number(filtering.recent_item_limit ?? 20)} /></div><Button className="w-fit" type="submit" isDisabled={feedback.isPending('config-save', 'set_filtering')}>{feedback.isPending('config-save', 'set_filtering') ? '保存中…' : '保存获取设置'}</Button></form>
        <div className="mt-6 border-t border-separator pt-5"><h3 className="type-control mb-4">阅读主题库</h3><HeroTopicLibrary key={JSON.stringify(config.data?.taxonomy?.topics ?? config.data?.config.tags ?? [])} topics={(config.data?.taxonomy?.topics ?? (Array.isArray(config.data?.config.tags) ? config.data.config.tags : [])).filter((topic): topic is string => typeof topic === 'string')} pending={feedback.isPending('config-save', 'set_tags')} onSave={(topics) => configMutation.mutate({ action: 'set_tags', payload: { topics } })} /></div>
      </AdminSection>

      <AdminSection title="密钥" description="真实 Key 只写入 SecretStore，保存后永不回显。">
        <form className="grid gap-3 min-[760px]:grid-cols-5" noValidate onSubmit={createSecret}>
          <TextField fullWidth value={secretDraft.name} onChange={(name) => {
            setSecretDraft((current) => ({ ...current, name }))
            clearSecretFieldError('name')
          }} isRequired isInvalid={Boolean(secretFieldErrors.name)}>
            <Label>Key 名称</Label><Input />{secretFieldErrors.name && <FieldError>{secretFieldErrors.name}</FieldError>}
          </TextField>
          <div>
            <HeroSelect label="Key 类型" value={secretDraft.kind} onChange={(kind) => {
              setSecretDraft((current) => ({ ...current, kind }))
              clearSecretFieldError('kind')
              clearSecretFieldError('provider')
            }} options={[{ id: 'ai', label: 'AI' }, { id: 'apify', label: 'Apify' }]} />
            {secretFieldErrors.kind && <FieldError>{secretFieldErrors.kind}</FieldError>}
          </div>
          <TextField fullWidth value={secretDraft.provider} onChange={(provider) => {
            setSecretDraft((current) => ({ ...current, provider }))
            clearSecretFieldError('provider')
          }} isRequired isInvalid={Boolean(secretFieldErrors.provider)}>
            <Label>Key provider</Label><Input />{secretFieldErrors.provider && <FieldError>{secretFieldErrors.provider}</FieldError>}
          </TextField>
          <TextField fullWidth value={secretDraft.envName} onChange={(envName) => {
            setSecretDraft((current) => ({ ...current, envName }))
            clearSecretFieldError('envName')
          }} isRequired isInvalid={Boolean(secretFieldErrors.envName)}>
            <Label>环境变量名</Label><Input />{secretFieldErrors.envName && <FieldError>{secretFieldErrors.envName}</FieldError>}
          </TextField>
          <TextField fullWidth value={secretDraft.value} onChange={(value) => {
            setSecretDraft((current) => ({ ...current, value }))
            clearSecretFieldError('value')
          }} isRequired isInvalid={Boolean(secretFieldErrors.value)}>
            <Label>Key 值</Label><Input type="password" autoComplete="new-password" />{secretFieldErrors.value && <FieldError>{secretFieldErrors.value}</FieldError>}
          </TextField>
          {secretFormError && <div className="min-[760px]:col-span-5" data-testid="secret-form-feedback"><HeroNotice title={secretFormError} /></div>}
          <Button className="w-fit" type="submit" isDisabled={feedback.isPending('secret-create', 'new')}><Icons.KeyRound size={15} />{feedback.isPending('secret-create', 'new') ? '保存中…' : '新增 Key'}</Button>
        </form>
        <div className="mt-5 min-w-0 max-w-full">
          <Table variant="secondary" className="max-w-full">
            <Table.ScrollContainer className="max-w-full overflow-x-auto" data-testid="secret-table-scroll">
              <Table.Content aria-label="已配置 Key">
                <Table.Header>
                  <Table.Column isRowHeader>Key</Table.Column>
                  <Table.Column>类型</Table.Column>
                  <Table.Column>状态</Table.Column>
                  <Table.Column>额度</Table.Column>
                  <Table.Column>操作</Table.Column>
                </Table.Header>
                <Table.Body
                  items={secrets.data?.secrets ?? []}
                  renderEmptyState={() => <div className="p-6 text-center text-muted">暂未配置 Key</div>}
                >
                  {(secret) => {
                    const presentation = secretPresentation(secret)
                    return <Table.Row id={secret.id}>
                      <Table.Cell>
                        <div className="min-w-44">
                          <p className="type-control">{presentation.name}</p>
                          <code className="type-meta text-muted">{secret.env_name}</code>
                        </div>
                      </Table.Cell>
                      <Table.Cell><span className="type-meta">{secret.kind === 'apify' ? 'Apify' : 'AI'} · {presentation.provider}</span></Table.Cell>
                      <Table.Cell>
                        <div className="min-w-28">
                          <p className="type-control">{presentation.status}</p>
                          <p className="type-meta mt-1 text-muted">{presentation.usage}</p>
                        </div>
                      </Table.Cell>
                      <Table.Cell><SecretQuotaCell secret={secret} userId={user.id} /></Table.Cell>
                      <Table.Cell><SecretRowActions secret={secret} onChanged={secretChanged} /></Table.Cell>
                    </Table.Row>
                  }}
                </Table.Body>
              </Table.Content>
            </Table.ScrollContainer>
          </Table>
        </div>
      </AdminSection>

    </>}
  </PageFrame></div>
}
