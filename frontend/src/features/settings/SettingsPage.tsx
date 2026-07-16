import { useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Save, ShieldCheck, Trash2, UserPlus } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { SecretRef } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import { Button, Chip, IconButton, Stack, TextField, Typography } from '../../ui'
import { DEFAULT_DEEPSEEK_MODEL, DEFAULT_GEMINI_MODEL, aiDefaultsForProvider, canAdministerWorkspace, secretPresentation, settingsDataReady } from './settingsModel'
import styles from './SettingsPage.module.css'

const recordOf = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}

function normalizeTopics(values: string[]): string[] {
  const seen = new Set<string>()
  const topics: string[] = []
  for (const value of values) {
    const topic = value.trim().replace(/^#+/, '').trim()
    const key = topic.toLocaleLowerCase()
    if (!topic || seen.has(key)) continue
    seen.add(key)
    topics.push(topic)
  }
  return topics
}

export function TopicLibraryEditor({ topics, pending = false, onSave }: {
  topics: string[]
  pending?: boolean
  onSave: (topics: string[]) => void
}) {
  const [draft, setDraft] = useState(() => normalizeTopics(topics))
  const [newTopic, setNewTopic] = useState('')
  const [search, setSearch] = useState('')
  const sourceKey = JSON.stringify(normalizeTopics(topics))
  const dirty = JSON.stringify(draft) !== sourceKey
  const visible = useMemo(() => {
    const query = search.trim().toLocaleLowerCase()
    return query ? draft.filter((topic) => topic.toLocaleLowerCase().includes(query)) : draft
  }, [draft, search])

  function addTopic() {
    const next = normalizeTopics([...draft, newTopic])
    if (next.length === draft.length) return
    setDraft(next)
    setNewTopic('')
  }

  return <Stack spacing={2}>
    <Typography color="text.secondary" variant="body2">新增或删除只影响未来候选和 AI 分类；已有订阅与历史内容不会被改写。</Typography>
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1}>
      <TextField
        size="small"
        label="新增主题"
        value={newTopic}
        onChange={(event) => setNewTopic(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== 'Enter') return
          event.preventDefault()
          addTopic()
        }}
        slotProps={{ htmlInput: { maxLength: 40 } }}
        sx={{ flex: 1 }}
      />
      <Button variant="contained" onClick={addTopic} disabled={!newTopic.trim() || pending}>添加主题</Button>
      <TextField size="small" label="搜索主题" value={search} onChange={(event) => setSearch(event.target.value)} sx={{ minWidth: 180 }} />
    </Stack>
    <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap', alignItems: 'center' }}>
      {visible.map((topic) => <Stack key={topic} direction="row" spacing={0.25} sx={{ alignItems: 'center' }}>
        <Chip label={topic} />
        <IconButton size="small" aria-label={`删除 ${topic}`} disabled={pending} onClick={() => setDraft((current) => current.filter((item) => item !== topic))}><Trash2 size={16} /></IconButton>
      </Stack>)}
      {!visible.length && <Typography color="text.secondary" variant="body2">没有匹配的主题。</Typography>}
    </Stack>
    <Stack direction="row" spacing={1}>
      <Button variant="contained" disabled={!dirty || pending} onClick={() => onSave(draft)}>{pending ? '保存中…' : '保存更改'}</Button>
      <Button disabled={!dirty || pending} onClick={() => setDraft(JSON.parse(sourceKey) as string[])}>撤销更改</Button>
    </Stack>
  </Stack>
}

function SecretCard({ secret, onChanged }: { secret: SecretRef; onChanged: () => void }) {
  const { api } = useAppContext()
  const feedback = useActionFeedback()
  const [error, setError] = useState('')
  const presentation = secretPresentation(secret)
  const rotating = feedback.isPending('secret-rotate', secret.id)
  const removing = feedback.isPending('secret-delete', secret.id)
  async function rotate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const value = String(new FormData(form).get('value') ?? '')
    form.reset()
    setError('')
    feedback.begin('secret-rotate', secret.id)
    try { await api.rotateSecret(secret.id, value); feedback.succeed('secret-rotate', secret.id, `${secret.name} 已轮换。`); onChanged() }
    catch (caught) { const message = caught instanceof ApiError ? caught.message : '轮换失败。'; setError(message); feedback.fail('secret-rotate', secret.id, message) }
  }
  async function remove() {
    setError('')
    feedback.begin('secret-delete', secret.id)
    try { await api.deleteSecret(secret.id); feedback.succeed('secret-delete', secret.id, `${secret.name} 已删除。`); onChanged() }
    catch (caught) { const message = caught instanceof ApiError ? caught.message : '删除失败。'; setError(message); feedback.fail('secret-delete', secret.id, message) }
  }
  return <article className={styles.secretCard}>
    <div><KeyRound size={20} /><strong>{presentation.name}</strong><span>{presentation.provider} · {presentation.status} · {presentation.usage}</span></div>
    <form onSubmit={rotate}><input name="value" type="password" autoComplete="new-password" required disabled={rotating} placeholder="粘贴新 Key（不会回显）" aria-label={`轮换 ${secret.name}`} /><button type="submit" disabled={rotating}>{rotating ? '轮换中…' : '轮换'}</button></form>
    <button type="button" className={styles.danger} disabled={secret.used_by.length > 0 || removing} onClick={remove}><Trash2 size={15} />{removing ? '删除中…' : '删除'}</button>
    {error && <small className={styles.error} role="alert">{error}</small>}
  </article>
}

export function SettingsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const admin = canAdministerWorkspace(user)
  const config = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal) })
  const users = useQuery({ queryKey: queryKeys.users(user.id), queryFn: ({ signal }) => api.users(signal), enabled: admin })
  const secrets = useQuery({ queryKey: queryKeys.secrets(user.id), queryFn: ({ signal }) => api.secrets(signal), enabled: admin })
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const ai = recordOf(config.data?.config.ai)
  const configuredProvider = String(ai.provider ?? 'gemini')
  const filtering = recordOf(config.data?.config.filtering)
  const refreshSecrets = () => { void queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }) }
  const configMutation = useMutation({
    mutationFn: ({ action, payload }: { action: string; payload: Record<string, unknown> }) => api.configAction(action, payload),
    onMutate: ({ action }) => feedback.begin('config-save', action),
    onSuccess: (_result, { action }) => { feedback.succeed('config-save', action); setMessage('设置已保存。'); setError(''); void queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }) },
    onError: (caught, { action }) => { const message = caught instanceof ApiError ? caught.message : '设置保存失败。'; setError(message); feedback.fail('config-save', action, message) },
  })
  const memberMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: Record<string, unknown> }) => api.updateUser(id, patch),
    onMutate: ({ id }) => feedback.begin('member-update', id),
    onSuccess: (_result, { id }) => { feedback.succeed('member-update', id); void queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) }) },
    onError: (caught, { id }) => { const message = caught instanceof ApiError ? caught.message : '成员更新失败。'; setError(message); feedback.fail('member-update', id, message) },
  })

  async function createSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const payload = {
      name: String(data.get('name') ?? '').trim(), kind: String(data.get('kind') ?? ''), provider: String(data.get('provider') ?? '').trim(),
      env_name: String(data.get('env_name') ?? '').trim(), value: String(data.get('value') ?? ''),
    }
    setError('')
    feedback.begin('secret-create', 'new')
    try { await api.createSecret(payload); form.reset(); feedback.succeed('secret-create', 'new', 'Key 已安全保存。'); setMessage('Key 已保存，页面不会回显真实值。'); refreshSecrets() }
    catch (caught) { form.reset(); const message = caught instanceof ApiError ? caught.message : 'Key 保存失败。'; setError(message); feedback.fail('secret-create', 'new', message) }
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const payload = { username: String(data.get('username') ?? ''), password: String(data.get('password') ?? ''), display_name: String(data.get('display_name') ?? '') || null, role: String(data.get('role') ?? 'member'), enabled: true }
    feedback.begin('member-create', 'new')
    try { await api.createUser(payload); form.reset(); feedback.succeed('member-create', 'new', '成员已创建。'); setMessage('成员已创建。'); void queryClient.invalidateQueries({ queryKey: queryKeys.users(user.id) }) }
    catch (caught) { const message = caught instanceof ApiError ? caught.message : '成员创建失败。'; setError(message); feedback.fail('member-create', 'new', message) }
  }

  function saveAi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    configMutation.mutate({ action: 'set_ai', payload: {
      enabled: data.has('enabled'), provider: String(data.get('provider')), model: String(data.get('model')),
      api_key_env: String(data.get('api_key_env')), base_url: String(data.get('base_url') ?? ''), languages: String(data.get('languages') ?? 'zh'),
      analysis_content_chars: Number(data.get('analysis_content_chars')), analysis_comments_chars: Number(data.get('analysis_comments_chars')),
      summary_max_chars: Number(data.get('summary_max_chars')), analysis_max_output_tokens: Number(data.get('analysis_max_output_tokens')),
      enrichment_content_chars: Number(data.get('enrichment_content_chars')),
    } })
  }

  function saveFiltering(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    configMutation.mutate({ action: 'set_filtering', payload: Object.fromEntries(Array.from(data.entries()).map(([key, value]) => [key, Number(value)])) })
  }

  const ready = settingsDataReady({
    admin,
    configLoaded: config.isSuccess,
    secretsLoaded: secrets.isSuccess,
  })
  if (!ready) return <div className={styles.page}>
    <header><div><h1>设置</h1><p>当前账户：{user.display_name || user.username} · {user.role}</p></div><ShieldCheck size={30} /></header>
    <section className={styles.card} role={config.isError || secrets.isError ? 'alert' : 'status'}>
      <h2>{config.isError || secrets.isError ? '设置读取失败' : '正在读取设置…'}</h2>
      <p>{config.isError || secrets.isError ? '请检查服务连接后重试，当前不会显示或提交默认配置。' : '正在加载配置和安全的 Key 元数据。'}</p>
      {(config.isError || secrets.isError) && <button type="button" onClick={() => { void config.refetch(); if (admin) void secrets.refetch() }}>重试</button>}
    </section>
  </div>

  return <div className={styles.page}>
    <header><div><h1>设置</h1><p>当前账户：{user.display_name || user.username} · {user.role}</p></div><ShieldCheck size={30} /></header>
    {message && <div className={styles.success} role="status">{message}</div>}{error && <div className={styles.error} role="alert">{error}</div>}
    <section className={styles.card}><h2>助手连接</h2><p>在自己的电脑运行 OpenClaw，通过只读 Remote MCP 使用当前账户的数据。</p><Button component={NavLink} to="/agents" variant="outlined">管理助手连接</Button></section>
    {!admin && <section className={styles.card}><h2>工作区设置只读</h2><p>全局 AI、成员和 Key 仅 owner/admin 可管理。你的个人订阅参数仍可在订阅页维护。</p></section>}
    {admin && <>
      <section className={styles.card}><h2>AI 概括</h2><form className={styles.formGrid} onSubmit={saveAi}>
        <label className={styles.checkbox}><input name="enabled" type="checkbox" defaultChecked={ai.enabled !== false} />启用 AI 分析</label>
        <label>Provider<select name="provider" defaultValue={configuredProvider} onChange={(event) => {
          const form = event.currentTarget.form
          const defaults = aiDefaultsForProvider(event.currentTarget.value)
          const model = form?.elements.namedItem('model') as HTMLInputElement | null
          const apiKeyEnv = form?.elements.namedItem('api_key_env') as HTMLSelectElement | null
          if (model) model.value = defaults.model
          if (apiKeyEnv && Array.from(apiKeyEnv.options).some((option) => option.value === defaults.apiKeyEnv)) apiKeyEnv.value = defaults.apiKeyEnv
        }}><option value="gemini">Gemini</option><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="deepseek">DeepSeek</option></select></label>
        <label>模型<input name="model" defaultValue={String(ai.model ?? (configuredProvider === 'deepseek' ? DEFAULT_DEEPSEEK_MODEL : DEFAULT_GEMINI_MODEL))} required /></label>
        <label>AI Key<select name="api_key_env" defaultValue={String(ai.api_key_env ?? '')} required><option value="">请选择</option>{(secrets.data?.secrets ?? []).filter((secret) => secret.kind === 'ai').map((secret) => <option key={secret.id} value={secret.env_name}>{secret.name} · {secret.is_set ? '已设置' : '未设置'}</option>)}</select></label>
        <label>Base URL<input name="base_url" type="url" defaultValue={String(ai.base_url ?? '')} /></label>
        <label>输出语言<input name="languages" defaultValue={Array.isArray(ai.languages) ? ai.languages.join(',') : 'zh'} /></label>
        <label>正文输入字符<input name="analysis_content_chars" type="number" min="100" max="10000" defaultValue={Number(ai.analysis_content_chars ?? 1000)} /></label>
        <label>评论输入字符<input name="analysis_comments_chars" type="number" min="0" max="20000" defaultValue={Number(ai.analysis_comments_chars ?? 1500)} /></label>
        <label>概括最多字符<input name="summary_max_chars" type="number" min="100" max="500" defaultValue={Number(ai.summary_max_chars ?? 200)} /></label>
        <label>最大输出 Token<input name="analysis_max_output_tokens" type="number" min="256" max="2048" defaultValue={Number(ai.analysis_max_output_tokens ?? 800)} /></label>
        <input name="enrichment_content_chars" type="hidden" defaultValue={Number(ai.enrichment_content_chars ?? 4000)} />
        <button className={styles.primary} type="submit" disabled={feedback.isPending('config-save', 'set_ai')}><Save size={16} />{feedback.isPending('config-save', 'set_ai') ? '保存中…' : '保存 AI 设置'}</button>
      </form></section>
      <section className={styles.card}><h2>获取与展示窗口</h2><form className={styles.formGrid} onSubmit={saveFiltering}>
        {[
          ['ai_score_threshold','兼容阈值',7.5,0,10], ['featured_score_threshold','精选阈值',7.5,0,10], ['daily_push_score_threshold','日报阈值',8.5,0,10],
          ['daily_push_limit','日报条数',10,1,50], ['homepage_min_score','首页最低分',6,0,10], ['time_window_hours','抓取窗口（小时）',24,1,720], ['recent_item_limit','历史预览条数',20,1,200],
        ].map(([name,label,fallback,min,max]) => <label key={String(name)}>{label}<input name={String(name)} type="number" min={Number(min)} max={Number(max)} step="0.5" defaultValue={Number(filtering[String(name)] ?? fallback)} /></label>)}
        <button className={styles.primary} type="submit" disabled={feedback.isPending('config-save', 'set_filtering')}><Save size={16} />{feedback.isPending('config-save', 'set_filtering') ? '保存中…' : '保存阈值'}</button>
      </form></section>
      <section className={styles.card}><h2>阅读主题库</h2><TopicLibraryEditor
        key={JSON.stringify(config.data?.taxonomy?.topics ?? config.data?.config.tags ?? [])}
        topics={(config.data?.taxonomy?.topics ?? (Array.isArray(config.data?.config.tags) ? config.data.config.tags : [])).filter((topic): topic is string => typeof topic === 'string')}
        pending={feedback.isPending('config-save', 'set_tags')}
        onSave={(topics) => configMutation.mutate({ action: 'set_tags', payload: { topics } })}
      /></section>
      <section className={styles.card}><h2>密钥管理</h2><p>真实 Key 只写入 secrets.env，保存后永不回显。</p><form className={styles.inlineForm} onSubmit={createSecret}>
        <input name="name" required placeholder="名称" aria-label="Key 名称" /><select name="kind" defaultValue="ai" aria-label="Key 类型"><option value="ai">AI</option><option value="apify">Apify</option></select><input name="provider" list="secret-provider-options" required placeholder="provider" aria-label="Key provider" /><datalist id="secret-provider-options"><option value="deepseek" /><option value="gemini" /><option value="openai" /><option value="anthropic" /><option value="apify" /></datalist><input name="env_name" required pattern="[A-Z][A-Z0-9_]*" placeholder="ENV_NAME" aria-label="环境变量名" /><input name="value" type="password" autoComplete="new-password" required placeholder="粘贴 Key" aria-label="Key 值" /><button className={styles.primary} type="submit" disabled={feedback.isPending('secret-create', 'new')}><KeyRound size={16} />{feedback.isPending('secret-create', 'new') ? '保存中…' : '新增 Key'}</button>
      </form><div className={styles.secretGrid}>{(secrets.data?.secrets ?? []).map((secret) => <SecretCard key={secret.id} secret={secret} onChanged={refreshSecrets} />)}</div></section>
      <section className={styles.card}><h2>成员管理</h2><form className={styles.inlineForm} onSubmit={createUser}><input name="username" required placeholder="用户名" /><input name="display_name" placeholder="显示名" /><input name="password" type="password" autoComplete="new-password" required placeholder="初始密码" /><select name="role" defaultValue="member"><option value="admin">admin</option><option value="member">member</option><option value="viewer">viewer</option></select><button className={styles.primary} type="submit" disabled={feedback.isPending('member-create', 'new')}><UserPlus size={16} />{feedback.isPending('member-create', 'new') ? '创建中…' : '新增成员'}</button></form>
        <div className={styles.userList}>{(users.data?.users ?? []).map((member) => <article key={member.id}><div><strong>{member.display_name || member.username}</strong><span>{member.username}</span></div><select value={member.role} disabled={member.role === 'owner' || feedback.isPending('member-update', member.id)} onChange={(event) => memberMutation.mutate({ id: member.id, patch: { role: event.target.value } })}><option value="owner">owner</option><option value="admin">admin</option><option value="member">member</option><option value="viewer">viewer</option></select><button type="button" disabled={member.role === 'owner' || feedback.isPending('member-update', member.id)} onClick={() => memberMutation.mutate({ id: member.id, patch: { enabled: !member.enabled } })}>{feedback.isPending('member-update', member.id) ? '保存中…' : member.enabled ? '停用' : '启用'}</button></article>)}</div>
      </section>
    </>}
  </div>
}
