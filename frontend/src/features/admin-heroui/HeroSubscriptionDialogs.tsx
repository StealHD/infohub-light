import { useState, type FormEvent, type Key } from 'react'

import { ApiError } from '../../api/client'
import type { CatalogField, CatalogSource, SecretRef, SourceTypeDefinition, Subscription, TaxonomyOptions } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  Button,
  Checkbox,
  Chip,
  ComboBox,
  Fieldset,
  Icons,
  Input,
  Label,
  ListBox,
  Modal,
  TextArea,
  TextField,
} from '../../design-system'
import { formValuesForSource, sourceMutationPayload, sourceScopeLabel } from '../subscriptions/subscriptionModel'
import { HeroNotice, HeroSelect } from './HeroAdminControls'

function unique(values: string[]) {
  const seen = new Set<string>()
  return values.map((value) => value.trim()).filter((value) => {
    const key = value.toLocaleLowerCase()
    if (!value || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function TopicCombo({ label, options, values, onChange }: { label: string; options: string[]; values: string[]; onChange: (values: string[]) => void }) {
  const [input, setInput] = useState('')
  const active = new Set(options.map((topic) => topic.toLocaleLowerCase()))
  function add(value: string) {
    const next = unique([...values, value])
    onChange(next)
    setInput('')
  }
  return <div className="grid gap-2">
    <ComboBox allowsCustomValue inputValue={input} onInputChange={setInput} onSelectionChange={(key: Key | null) => key !== null && add(String(key))}>
      <Label>{label}</Label>
      <ComboBox.InputGroup><Input aria-label={label} onKeyDown={(event) => { if (event.key === 'Enter' && input.trim()) { event.preventDefault(); add(input) } }} /><ComboBox.Trigger aria-label={`打开${label}候选`}><Icons.ChevronDown size={15} /></ComboBox.Trigger></ComboBox.InputGroup>
      <ComboBox.Popover><ListBox>{options.filter((option) => !values.includes(option)).map((option) => <ListBox.Item id={option} key={option}>{option}</ListBox.Item>)}</ListBox></ComboBox.Popover>
    </ComboBox>
    <div className="flex flex-wrap gap-2">{values.map((topic) => <Chip key={topic} variant="soft"><Chip.Label>{topic}{!active.has(topic.toLocaleLowerCase()) && <span className="ml-1 text-[10px] text-muted">已停用</span>}</Chip.Label><button type="button" aria-label={`移除 ${topic}`} onClick={() => onChange(values.filter((value) => value !== topic))}><Icons.X size={12} /></button></Chip>)}</div>
  </div>
}

function fieldValue(field: CatalogField, form: FormData) {
  if (field.input_type === 'checkbox' || field.input_type === 'boolean') return form.has(field.name)
  const raw = String(form.get(field.name) ?? '').trim()
  return field.input_type === 'number' ? raw === '' ? field.default : Number(raw) : raw
}

function RegistryFields({ definition, source }: { definition: SourceTypeDefinition; source?: CatalogSource }) {
  const values = formValuesForSource(definition, source)
  return <>{definition.fields.map((field) => field.options?.length
    ? <RegistryOptionField key={field.name} field={field} value={String(values[field.name] ?? '')} />
    : field.input_type === 'checkbox' || field.input_type === 'boolean'
      ? <Checkbox key={field.name} name={field.name} defaultSelected={Boolean(values[field.name])}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{field.label}</Checkbox.Content></Checkbox>
      : <TextField key={field.name} fullWidth name={field.name} defaultValue={String(values[field.name] ?? '')} isRequired={field.required}><Label>{field.label}</Label><Input type={field.input_type === 'number' ? 'number' : field.input_type === 'url' ? 'url' : 'text'} min={field.min ?? undefined} max={field.max ?? undefined} /></TextField>)}</>
}

function RegistryOptionField({ field, value }: { field: CatalogField; value: string }) {
  const [selected, setSelected] = useState(value)
  return <HeroSelect label={field.label} name={field.name} value={selected} onChange={setSelected} options={(field.options ?? []).map((option) => typeof option === 'string' ? { id: option, label: option } : { id: option.value, label: option.label })} />
}

export function SourceForm({ definition, source, secrets, allowSecret, scopes, taxonomy, submitLabel, onSubmit }: {
  definition: SourceTypeDefinition
  source?: CatalogSource
  secrets: SecretRef[]
  allowSecret: boolean
  scopes: CatalogSource['scope'][]
  taxonomy: TaxonomyOptions
  submitLabel: string
  onSubmit: (payload: Record<string, unknown>) => Promise<void>
}) {
  const feedback = useActionFeedback()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [scope, setScope] = useState(source?.scope ?? scopes[0] ?? 'private')
  const [channel, setChannel] = useState(source?.default_channel ?? '')
  const [topics, setTopics] = useState(source?.default_topics ?? [])
  const [secretEnv, setSecretEnv] = useState(source?.secret_env ?? '')
  const [advanced, setAdvanced] = useState(JSON.stringify(source?.config ?? {}, null, 2))

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const entity = source?.id ?? 'new'
    setError(''); setPending(true); feedback.begin('source-save', entity)
    const form = new FormData(event.currentTarget)
    try {
      const config = advanced.trim() ? JSON.parse(advanced) as Record<string, unknown> : {}
      for (const field of definition.fields) config[field.name] = fieldValue(field, form)
      await onSubmit(sourceMutationPayload({ source, allowSecret, config, metadata: {
        type: definition.type,
        display_name: String(form.get('display_name') ?? '').trim(),
        description: String(form.get('description') ?? '').trim(),
        scope,
        default_channel: channel || null,
        default_topics: topics,
        secret_env: secretEnv || null,
        enabled: form.has('enabled'),
      } }))
      feedback.succeed('source-save', entity)
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : caught instanceof SyntaxError ? '高级配置不是有效 JSON。' : '来源保存失败。'
      setError(message); feedback.fail('source-save', entity, message)
    } finally { setPending(false) }
  }

  return <form className="grid gap-4" onSubmit={submit}>
    <TextField fullWidth name="display_name" defaultValue={source?.display_name ?? ''} isRequired><Label>来源名称</Label><Input /></TextField>
    <TextField fullWidth name="description" defaultValue={source?.description ?? ''}><Label>来源说明</Label><Input /></TextField>
    {!source && <HeroSelect name="scope" label="可见范围" value={scope} onChange={(value) => setScope(value as CatalogSource['scope'])} options={scopes.map((value) => ({ id: value, label: sourceScopeLabel(value) }))} />}
    <RegistryFields definition={definition} source={source} />
    <HeroSelect name="default_channel" label="默认频道" value={channel} onChange={setChannel} options={[{ id: '', label: '未设置' }, ...taxonomy.channels.map((value) => ({ id: value, label: value }))]} />
    <TopicCombo label="默认主题" options={taxonomy.topics} values={topics} onChange={setTopics} />
    {allowSecret && <HeroSelect name="secret_env" label="Apify Key" value={secretEnv} onChange={setSecretEnv} options={[{ id: '', label: '不使用 Key' }, ...secrets.filter((secret) => secret.kind === 'apify').map((secret) => ({ id: secret.env_name, label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}` }))]} />}
    <Checkbox name="enabled" defaultSelected={source?.enabled ?? true}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用来源</Checkbox.Content></Checkbox>
    <Fieldset><Fieldset.Legend>高级配置</Fieldset.Legend><Fieldset.Group><TextArea fullWidth aria-label="高级配置 JSON" value={advanced} onChange={(event) => setAdvanced(event.target.value)} rows={5} /></Fieldset.Group></Fieldset>
    {error && <HeroNotice title={error} />}
    <Button type="submit" isDisabled={pending}>{pending ? '保存中…' : submitLabel}</Button>
  </form>
}

export function SubscriptionForm({ subscription, source, readonly, taxonomy, onDone, onJob }: {
  subscription: Subscription
  source: CatalogSource
  readonly: boolean
  taxonomy: TaxonomyOptions
  onDone: () => void
  onJob: (kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) => Promise<void>
}) {
  const { api, beginAction, isActionCurrent } = useAppContext()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [channel, setChannel] = useState(subscription.override_channel ?? '')
  const [topics, setTopics] = useState(subscription.override_topics ?? [])
  const [analysisMode, setAnalysisMode] = useState(subscription.analysis_mode ?? 'full')
  const [interval, setInterval] = useState(String(subscription.schedule?.interval_minutes ?? 360))

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
    const intent = submitter?.value ?? 'save'
    const token = beginAction()
    setPending(true); setError('')
    try {
      if (intent === 'unsubscribe') { await api.unsubscribe(subscription.id); if (isActionCurrent(token)) onDone(); return }
      await api.updateSubscription(subscription.id, { enabled: form.has('enabled'), override_channel: channel || null, override_topics: topics, personal_tags: String(form.get('personal_tags') ?? '').split(',').map((value) => value.trim()).filter(Boolean), analysis_mode: analysisMode as Subscription['analysis_mode'], priority: Number(form.get('priority') ?? 0) })
      if (!isActionCurrent(token)) return
      await api.updateSourceSchedule(subscription.id, { enabled: form.has('enabled') && form.has('source_schedule_enabled'), interval_minutes: Number(interval) })
      if (!isActionCurrent(token)) return
      if (intent === 'test' || intent === 'fetch') await onJob(intent, source.id, subscription.id)
      if (isActionCurrent(token)) onDone()
    } catch (caught) { setError(caught instanceof ApiError ? caught.message : '订阅保存失败。') }
    finally { setPending(false) }
  }

  return <form className="grid gap-4" onSubmit={submit}>
    <Fieldset disabled={readonly || pending} className="grid gap-4">
      <Fieldset.Legend>订阅配置</Fieldset.Legend>
      <HeroSelect name="override_channel" label="个人频道" value={channel} onChange={setChannel} options={[{ id: '', label: '继承来源默认频道' }, ...taxonomy.channels.map((value) => ({ id: value, label: value }))]} />
      <TopicCombo label="阅读主题" options={taxonomy.topics} values={topics} onChange={setTopics} />
      <TextField fullWidth name="personal_tags" defaultValue={(subscription.personal_tags ?? []).join(', ')}><Label>个人标签</Label><Input /></TextField>
      <HeroSelect name="analysis_mode" label="分析模式" value={analysisMode} onChange={(value) => setAnalysisMode(value as NonNullable<Subscription['analysis_mode']>)} options={[{ id: 'full', label: '完整分析' }, { id: 'personal_only', label: '仅收集' }]} />
      <TextField fullWidth name="priority" defaultValue={String(subscription.priority ?? 0)}><Label>信源优先级</Label><Input type="number" min={0} max={100} /></TextField>
      <Checkbox name="enabled" defaultSelected={subscription.enabled}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用订阅</Checkbox.Content></Checkbox>
      <HeroSelect name="source_schedule_interval" label="单源自动获取" value={interval} onChange={setInterval} options={(subscription.schedule?.allowed_intervals ?? [30, 60, 180, 360, 720, 1440]).map((value) => ({ id: String(value), label: value === 30 ? '每 30 分钟' : `每 ${value / 60} 小时` }))} />
      <Checkbox name="source_schedule_enabled" defaultSelected={subscription.schedule?.enabled ?? false}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用单源周期</Checkbox.Content></Checkbox>
    </Fieldset>
    {error && <HeroNotice title={error} />}
    {!readonly && <div className="flex flex-wrap gap-2"><Button type="submit" name="intent" value="save">保存订阅</Button><Button type="submit" name="intent" value="test" variant="secondary">测试连接</Button><Button type="submit" name="intent" value="fetch" variant="secondary">保存并立即抓取</Button><Button type="submit" name="intent" value="unsubscribe" variant="danger">取消订阅</Button></div>}
  </form>
}

export function HeroDialog({ isOpen, onOpenChange, title, children }: { isOpen: boolean; onOpenChange: (open: boolean) => void; title: string; children: React.ReactNode }) {
  return <Modal isOpen={isOpen} onOpenChange={onOpenChange}><Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开{title}</Modal.Trigger><Modal.Backdrop><Modal.Container size="lg" scroll="inside"><Modal.Dialog><Modal.Header><Modal.Heading>{title}</Modal.Heading></Modal.Header><Modal.Body>{children}</Modal.Body><Modal.Footer><Button variant="ghost" onPress={() => onOpenChange(false)}>关闭</Button></Modal.Footer></Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
}
