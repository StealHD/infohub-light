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
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
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
const errorMessage = (caught: unknown, fallback: string) => caught instanceof ApiError ? caught.message : fallback

function FormField({ label, name, defaultValue = '', type = 'text', min, max, required = false }: {
  label: string; name: string; defaultValue?: string | number; type?: string; min?: number; max?: number; required?: boolean
}) {
  return <TextField fullWidth name={name} defaultValue={String(defaultValue)} isRequired={required}><Label>{label}</Label><Input type={type} min={min} max={max} /></TextField>
}

function HeroSecretCard({ secret, onChanged }: { secret: SecretRef; onChanged: () => void }) {
  const { api } = useAppContext()
  const feedback = useActionFeedback()
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteError, setDeleteError] = useState('')
  const deleteTriggerRef = useRef<HTMLButtonElement>(null)
  const presentation = secretPresentation(secret)
  const rotating = feedback.isPending('secret-rotate', secret.id)
  const removing = feedback.isPending('secret-delete', secret.id)

  function closeDeleteDialog() {
    setDeleteOpen(false)
    setDeleteError('')
    queueMicrotask(() => deleteTriggerRef.current?.focus())
  }

  async function rotate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitted = value
    setValue('')
    setError('')
    feedback.begin('secret-rotate', secret.id)
    try { await api.rotateSecret(secret.id, submitted); feedback.succeed('secret-rotate', secret.id, `${secret.name} 已轮换。`); onChanged() }
    catch (caught) { const message = errorMessage(caught, '轮换失败。'); setError(message); feedback.fail('secret-rotate', secret.id, message) }
  }

  async function remove() {
    setDeleteError('')
    feedback.begin('secret-delete', secret.id)
    try {
      await api.deleteSecret(secret.id)
      feedback.succeed('secret-delete', secret.id, `${secret.name} 已删除。`)
      closeDeleteDialog()
      onChanged()
    } catch (caught) {
      const message = errorMessage(caught, '删除失败。')
      setDeleteError(message)
      feedback.fail('secret-delete', secret.id, message)
    }
  }

  return <Card variant="transparent" className="p-4">
    <div className="flex flex-wrap items-center gap-2"><Icons.KeyRound size={17} /><Card.Title>{presentation.name}</Card.Title><span className="type-meta text-muted">{presentation.provider} · {presentation.status} · {presentation.usage}</span></div>
    <form className="mt-3 flex flex-col gap-2 min-[640px]:flex-row" onSubmit={rotate}>
      <TextField fullWidth value={value} onChange={setValue} isRequired><Label>{`轮换 ${secret.name}`}</Label><Input type="password" autoComplete="new-password" placeholder="粘贴新 Key（不会回显）" /></TextField>
      <Button className="self-end" type="submit" isDisabled={rotating}>{rotating ? '轮换中…' : '轮换'}</Button>
      <Modal isOpen={deleteOpen} onOpenChange={(open) => {
        if (removing) return
        setDeleteOpen(open)
        if (!open) {
          setDeleteError('')
          queueMicrotask(() => deleteTriggerRef.current?.focus())
        }
      }}>
        <Button ref={deleteTriggerRef} className="self-end" type="button" variant="danger" isDisabled={secret.used_by.length > 0 || removing}>删除</Button>
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
    </form>
    {error && <div className="mt-3"><HeroNotice title={error} /></div>}
  </Card>
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
  const [secretDraft, setSecretDraft] = useState({ name: '', kind: 'ai', provider: '', envName: '', value: '' })
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
  const refreshSecrets = () => void queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) })

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
    setError('')
    feedback.begin('secret-create', 'new')
    try {
      await api.createSecret(submitted)
      setSecretDraft({ name: '', kind: 'ai', provider: '', envName: '', value: '' })
      feedback.succeed('secret-create', 'new', 'Key 已安全保存。')
      setMessage('Key 已保存，页面不会回显真实值。')
      refreshSecrets()
    } catch (caught) {
      const message = errorMessage(caught, 'Key 保存失败。')
      setError(message)
      feedback.fail('secret-create', 'new', message)
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
      ai_score_threshold: Number(data.get('ai_score_threshold')),
      homepage_min_score: Number(data.get('homepage_min_score')),
      time_window_hours: Number(data.get('time_window_hours')),
      recent_item_limit: Number(data.get('recent_item_limit')),
    } })
  }

  const ready = settingsDataReady({ admin, configLoaded: config.isSuccess, secretsLoaded: secrets.isSuccess })
  if (!ready) return <PageFrame width="admin" className="p-5">{config.isError || secrets.isError ? <HeroNotice title="设置读取失败" /> : <LoadingState label="正在读取设置" rows={1} />}</PageFrame>

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
    {message && <HeroNotice title={message} status="success" role="status" />}{error && <HeroNotice title={error} />}

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
      <AdminSection title="获取与主题" description="控制兼容评分、抓取窗口和未来可选主题；精选与日报字段不在当前产品中显示。">
        <form className="grid gap-4" onSubmit={saveFiltering}><div className="grid gap-4 min-[720px]:grid-cols-4"><FormField name="ai_score_threshold" label="兼容阈值" type="number" min={0} max={10} defaultValue={Number(filtering.ai_score_threshold ?? 7.5)} /><FormField name="homepage_min_score" label="首页最低分" type="number" min={0} max={10} defaultValue={Number(filtering.homepage_min_score ?? 6)} /><FormField name="time_window_hours" label="抓取窗口（小时）" type="number" min={1} max={720} defaultValue={Number(filtering.time_window_hours ?? 24)} /><FormField name="recent_item_limit" label="历史预览条数" type="number" min={1} max={200} defaultValue={Number(filtering.recent_item_limit ?? 20)} /></div><Button className="w-fit" type="submit" isDisabled={feedback.isPending('config-save', 'set_filtering')}>{feedback.isPending('config-save', 'set_filtering') ? '保存中…' : '保存获取设置'}</Button></form>
        <div className="mt-6 border-t border-separator pt-5"><h3 className="type-control mb-4">阅读主题库</h3><HeroTopicLibrary key={JSON.stringify(config.data?.taxonomy?.topics ?? config.data?.config.tags ?? [])} topics={(config.data?.taxonomy?.topics ?? (Array.isArray(config.data?.config.tags) ? config.data.config.tags : [])).filter((topic): topic is string => typeof topic === 'string')} pending={feedback.isPending('config-save', 'set_tags')} onSave={(topics) => configMutation.mutate({ action: 'set_tags', payload: { topics } })} /></div>
      </AdminSection>

      <AdminSection title="密钥" description="真实 Key 只写入 SecretStore，保存后永不回显。">
        <form className="grid gap-3 min-[760px]:grid-cols-5" onSubmit={createSecret}>
          <TextField fullWidth value={secretDraft.name} onChange={(name) => setSecretDraft((current) => ({ ...current, name }))} isRequired><Label>Key 名称</Label><Input /></TextField>
          <HeroSelect label="Key 类型" value={secretDraft.kind} onChange={(kind) => setSecretDraft((current) => ({ ...current, kind }))} options={[{ id: 'ai', label: 'AI' }, { id: 'apify', label: 'Apify' }]} />
          <TextField fullWidth value={secretDraft.provider} onChange={(provider) => setSecretDraft((current) => ({ ...current, provider }))} isRequired><Label>Key provider</Label><Input /></TextField>
          <TextField fullWidth value={secretDraft.envName} onChange={(envName) => setSecretDraft((current) => ({ ...current, envName }))} isRequired><Label>环境变量名</Label><Input pattern="[A-Z][A-Z0-9_]*" /></TextField>
          <TextField fullWidth value={secretDraft.value} onChange={(value) => setSecretDraft((current) => ({ ...current, value }))} isRequired><Label>Key 值</Label><Input type="password" autoComplete="new-password" /></TextField>
          <Button className="w-fit" type="submit" isDisabled={feedback.isPending('secret-create', 'new')}><Icons.KeyRound size={15} />{feedback.isPending('secret-create', 'new') ? '保存中…' : '新增 Key'}</Button>
        </form>
        <div className="mt-5 grid gap-3">{(secrets.data?.secrets ?? []).map((secret) => <HeroSecretCard key={secret.id} secret={secret} onChanged={refreshSecrets} />)}</div>
      </AdminSection>

    </>}
  </PageFrame></div>
}
