import { useCallback, useEffect, useRef, useState, type FormEvent, type Key, type RefObject } from 'react'

import { ApiError } from '../../api/client'
import type { CatalogField, CatalogSource, SecretRef, SourceTypeDefinition, Subscription, SubscriptionDisableDisposition, TaxonomyOptions } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  actionToast,
  Button,
  Checkbox,
  ComboBox,
  Description,
  FieldError,
  Fieldset,
  Icons,
  Input,
  Label,
  ListBox,
  Modal,
  RemovableTag,
  TextArea,
  TextField,
} from '../../design-system'
import { formValuesForSource, sourceMutationPayload, sourceScopeLabel } from '../subscriptions/subscriptionModel'
import { HeroNotice, HeroSelect } from './HeroAdminControls'
import { validateRegistryFields } from './sourceFormValidation'

function unique(values: string[]) {
  const seen = new Set<string>()
  return values.map((value) => value.trim()).filter((value) => {
    const key = value.toLocaleLowerCase()
    if (!value || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function sourceFormError(caught: unknown, sourceType: string): string {
  if (caught instanceof SyntaxError) return '高级配置不是有效 JSON。'
  if (!(caught instanceof ApiError)) return '来源保存失败。'
  if (sourceType !== 'youtube_channel') return caught.message
  if (caught.code === 'youtube_channel_not_found') {
    return '未找到这个 YouTube 频道，请检查链接或改用频道 ID。'
  }
  if (caught.code === 'youtube_channel_resolution_failed') {
    return '暂时无法解析 YouTube 频道，请稍后重试或改用频道 ID。'
  }
  if (caught.code === 'invalid_source_config') {
    return '请输入公开的 YouTube 频道链接、@handle、频道 ID 或规范 Feed 地址。'
  }
  return caught.message
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
    <div className="flex flex-wrap gap-2">{values.map((topic) => <RemovableTag
      key={topic}
      label={`${topic}${!active.has(topic.toLocaleLowerCase()) ? '（已停用）' : ''}`}
      onRemove={() => onChange(values.filter((value) => value !== topic))}
    />)}</div>
  </div>
}

function fieldValue(field: CatalogField, form: FormData, registryValues: Record<string, unknown>) {
  if (field.input_type === 'checkbox' || field.input_type === 'boolean') return form.has(field.name)
  if (field.options?.length) return String(registryValues[field.name] ?? '').trim()
  const raw = String(form.get(field.name) ?? '').trim()
  return field.input_type === 'number' ? raw === '' ? field.default : Number(raw) : raw
}

function RegistryFields({ definition, values, errors, onOptionChange, onFieldChange }: { definition: SourceTypeDefinition; values: Record<string, unknown>; errors: Record<string, string>; onOptionChange: (name: string, value: string) => void; onFieldChange: (name: string) => void }) {
  return <>{definition.fields.map((field) => field.options?.length
    ? <RegistryOptionField key={field.name} field={field} value={String(values[field.name] ?? '')} error={errors[field.name]} onChange={(value) => onOptionChange(field.name, value)} />
    : field.input_type === 'checkbox' || field.input_type === 'boolean'
      ? <div key={field.name} className="grid gap-1"><Checkbox name={field.name} defaultSelected={Boolean(values[field.name])} isInvalid={Boolean(errors[field.name])} onChange={() => onFieldChange(field.name)}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>{field.label}</Checkbox.Content></Checkbox>{field.help && <Description>{field.help}</Description>}{errors[field.name] && <FieldError>{errors[field.name]}</FieldError>}</div>
      : <TextField key={field.name} fullWidth name={field.name} defaultValue={String(values[field.name] ?? '')} isRequired={field.required} isInvalid={Boolean(errors[field.name])}><Label>{field.label}</Label><Input type={field.input_type === 'number' ? 'number' : field.input_type === 'url' ? 'url' : 'text'} min={field.min ?? undefined} max={field.max ?? undefined} step={field.input_type === 'number' ? 1 : undefined} onChange={() => onFieldChange(field.name)} />{field.help && <Description>{field.help}</Description>}{errors[field.name] && <FieldError>{errors[field.name]}</FieldError>}</TextField>)}</>
}

function RegistryOptionField({ field, value, error, onChange }: { field: CatalogField; value: string; error?: string; onChange: (value: string) => void }) {
  return <HeroSelect label={field.label} value={value} onChange={onChange} isRequired={field.required} description={field.help} errorMessage={error} options={(field.options ?? []).map((option) => typeof option === 'string' ? { id: option, label: option } : { id: option.value, label: option.label })} />
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
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [registryValues, setRegistryValues] = useState<Record<string, unknown>>(() => formValuesForSource(definition, source))

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const entity = source?.id ?? 'new'
    setError(''); setFieldErrors({})
    const form = new FormData(event.currentTarget)
    const nextFieldErrors = validateRegistryFields(definition, form, registryValues)
    if (!String(form.get('display_name') ?? '').trim()) nextFieldErrors.display_name = '来源名称不能为空。'
    if (Object.keys(nextFieldErrors).length) {
      setFieldErrors(nextFieldErrors)
      return
    }
    setPending(true); feedback.begin('source-save', entity)
    try {
      const config = advanced.trim() ? JSON.parse(advanced) as Record<string, unknown> : {}
      for (const field of definition.fields) config[field.name] = fieldValue(field, form, registryValues)
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
      const message = sourceFormError(caught, definition.type)
      setError(message); feedback.fail('source-save', entity, message)
    } finally { setPending(false) }
  }

  function captureInvalid(event: FormEvent<HTMLFormElement>) {
    const target = event.target as HTMLInputElement
    const field = definition.fields.find((candidate) => candidate.name === target.name)
    const label = field?.label ?? (target.name === 'display_name' ? '来源名称' : '')
    if (!label) return
    const message = target.validity.valueMissing
      ? `${label}不能为空。`
      : target.validity.typeMismatch
        ? `${label}必须是有效 URL。`
        : target.validity.rangeUnderflow
          ? `${label}不能小于 ${target.min}。`
          : target.validity.rangeOverflow
            ? `${label}不能大于 ${target.max}。`
            : target.validity.badInput
              ? `${label}必须是有效数字。`
              : target.validationMessage
    setFieldErrors((current) => ({ ...current, [target.name]: message }))
  }

  function clearFieldError(name: string) {
    setFieldErrors((current) => {
      if (!current[name]) return current
      const next = { ...current }
      delete next[name]
      return next
    })
  }

  return <form className="grid gap-4" noValidate onSubmit={submit} onInvalidCapture={captureInvalid}>
    <TextField fullWidth name="display_name" defaultValue={source?.display_name ?? ''} isRequired isInvalid={Boolean(fieldErrors.display_name)}><Label>来源名称</Label><Input onChange={() => clearFieldError('display_name')} />{fieldErrors.display_name && <FieldError>{fieldErrors.display_name}</FieldError>}</TextField>
    <TextField fullWidth name="description" defaultValue={source?.description ?? ''}><Label>来源说明</Label><Input /></TextField>
    {!source && <HeroSelect name="scope" label="可见范围" value={scope} onChange={(value) => setScope(value as CatalogSource['scope'])} options={scopes.map((value) => ({ id: value, label: sourceScopeLabel(value) }))} />}
    <RegistryFields definition={definition} values={registryValues} errors={fieldErrors} onOptionChange={(name, value) => {
      setRegistryValues((current) => ({ ...current, [name]: value }))
      clearFieldError(name)
    }} onFieldChange={clearFieldError} />
    <HeroSelect name="default_channel" label="默认频道" value={channel} onChange={setChannel} options={[{ id: '', label: '未设置' }, ...taxonomy.channels.map((value) => ({ id: value, label: value }))]} />
    <TopicCombo label="默认主题" options={taxonomy.topics} values={topics} onChange={setTopics} />
    {allowSecret && <HeroSelect name="secret_env" label="Apify Key" value={secretEnv} onChange={setSecretEnv} options={[{ id: '', label: '不使用 Key' }, ...secrets.filter((secret) => secret.kind === 'apify').map((secret) => ({ id: secret.env_name, label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}` }))]} />}
    {definition.credential_mode === 'workspace_apify_pool' && <HeroNotice title="由工作区 Apify Key 池自动管理" />}
    <Checkbox name="enabled" defaultSelected={source?.enabled ?? true}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用来源</Checkbox.Content></Checkbox>
    <Fieldset><Fieldset.Legend>高级配置</Fieldset.Legend><Fieldset.Group><TextArea fullWidth aria-label="高级配置 JSON" value={advanced} onChange={(event) => setAdvanced(event.target.value)} rows={5} /></Fieldset.Group></Fieldset>
    {error && <HeroNotice title={error} />}
    <Button type="submit" isDisabled={pending}>{pending ? '保存中…' : submitLabel}</Button>
  </form>
}

export function SubscriptionForm({ subscription, source, readonly, taxonomy, onDone, onJob, onPendingChange }: {
  subscription: Subscription
  source: CatalogSource
  readonly: boolean
  taxonomy: TaxonomyOptions
  onDone: () => void
  onJob: (kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) => Promise<void>
  onPendingChange?: (pending: boolean) => void
}) {
  const { api, beginAction, isActionCurrent } = useAppContext()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [channel, setChannel] = useState(subscription.override_channel ?? '')
  const [topics, setTopics] = useState(subscription.override_topics ?? [])
  const [analysisMode, setAnalysisMode] = useState(subscription.analysis_mode ?? 'full')
  const [interval, setInterval] = useState(String(subscription.schedule?.interval_minutes ?? 360))
  const [enabled, setEnabled] = useState(subscription.enabled)
  const [disableDisposition, setDisableDisposition] = useState<SubscriptionDisableDisposition>('dismiss')
  const [confirmUnsubscribe, setConfirmUnsubscribe] = useState(false)

  useEffect(() => {
    onPendingChange?.(pending)
    return () => onPendingChange?.(false)
  }, [onPendingChange, pending])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
    const intent = submitter?.value ?? 'save'
    const token = beginAction()
    setPending(true); setError('')
    try {
      if (intent === 'unsubscribe') {
        try {
          await api.unsubscribe(subscription.id)
          actionToast.success(`${source.display_name} 已取消订阅`)
          if (isActionCurrent(token)) onDone()
        } catch (caught) {
          actionToast.danger('取消订阅失败', {
            description: caught instanceof ApiError || caught instanceof Error ? caught.message : '请稍后重试。',
          })
        }
        return
      }
      await api.updateSubscription(subscription.id, {
        enabled,
        override_channel: channel || null,
        override_topics: topics,
        personal_tags: String(form.get('personal_tags') ?? '').split(',').map((value) => value.trim()).filter(Boolean),
        analysis_mode: analysisMode as Subscription['analysis_mode'],
        priority: Number(form.get('priority') ?? 0),
        ...(subscription.enabled && !enabled ? { on_disable: disableDisposition } : {}),
      })
      if (!isActionCurrent(token)) return
      await api.updateSourceSchedule(subscription.id, { enabled: enabled && form.has('source_schedule_enabled'), interval_minutes: Number(interval) })
      if (!isActionCurrent(token)) return
      if (intent === 'test' || intent === 'fetch') await onJob(intent, source.id, subscription.id)
      if (isActionCurrent(token)) {
        if (intent === 'save') actionToast.success('订阅设置已保存')
        onDone()
      }
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
      <Checkbox name="enabled" isSelected={enabled} onChange={setEnabled}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用订阅</Checkbox.Content></Checkbox>
      {subscription.enabled && !enabled && <div className="rounded-control border border-separator bg-surface-secondary p-3">
        <HeroSelect
          label="关闭后如何处理已有内容"
          value={disableDisposition}
          onChange={(value) => setDisableDisposition(value as SubscriptionDisableDisposition)}
          options={[
            { id: 'dismiss', label: '归入忽略集合，可在设置中恢复' },
            { id: 'save', label: '加入收藏后从信息流移除' },
          ]}
        />
      </div>}
      <HeroSelect name="source_schedule_interval" label="单源自动获取" value={interval} onChange={setInterval} options={(subscription.schedule?.allowed_intervals ?? [30, 60, 180, 360, 720, 1440]).map((value) => ({ id: String(value), label: value === 30 ? '每 30 分钟' : `每 ${value / 60} 小时` }))} />
      <Checkbox name="source_schedule_enabled" defaultSelected={subscription.schedule?.enabled ?? false}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用单源周期</Checkbox.Content></Checkbox>
    </Fieldset>
    {error && <HeroNotice title={error} />}
    {!readonly && <>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" name="intent" value="save" isDisabled={pending}>保存</Button>
        <Button type="submit" name="intent" value="fetch" variant="secondary" isDisabled={pending}>保存并获取</Button>
        <Button type="submit" name="intent" value="test" variant="ghost" size="sm" isDisabled={pending}>仅测试连接</Button>
      </div>
      <div className="border-t border-separator pt-3">
        {confirmUnsubscribe
          ? <HeroNotice title="确认取消这个订阅？" status="warning">
            <p className="mb-2">这只影响你的订阅，不会删除共享来源或其他成员的数据。</p>
            <span className="flex flex-wrap gap-2">
              <Button type="button" size="sm" variant="ghost" isDisabled={pending} onPress={() => setConfirmUnsubscribe(false)}>保留订阅</Button>
              <Button type="submit" size="sm" name="intent" value="unsubscribe" variant="danger" isDisabled={pending}>确认取消订阅</Button>
            </span>
          </HeroNotice>
          : <Button type="button" size="sm" variant="ghost" className="text-danger" isDisabled={pending} onPress={() => setConfirmUnsubscribe(true)}>取消订阅…</Button>}
      </div>
    </>}
  </form>
}

export function HeroDialog({ isOpen, onOpenChange, returnFocusRef, title, children, locked = false }: {
  isOpen: boolean
  onOpenChange: (open: boolean) => void
  returnFocusRef?: RefObject<HTMLElement | null>
  title: string
  children: React.ReactNode
  locked?: boolean
}) {
  const wasOpen = useRef(isOpen)
  const pendingReturnFocus = useRef<HTMLElement | null>(null)
  const fallbackTimer = useRef<number | null>(null)
  const finishReturnFocus = useCallback(() => {
    if (fallbackTimer.current !== null) {
      window.clearTimeout(fallbackTimer.current)
      fallbackTimer.current = null
    }
    const target = pendingReturnFocus.current
    pendingReturnFocus.current = null
    window.requestAnimationFrame(() => {
      if (target?.isConnected) target.focus()
    })
  }, [])

  useEffect(() => {
    if (wasOpen.current && !isOpen) {
      pendingReturnFocus.current = returnFocusRef?.current ?? null
      if (returnFocusRef) returnFocusRef.current = null
      fallbackTimer.current = window.setTimeout(finishReturnFocus, 300)
    } else if (isOpen) {
      pendingReturnFocus.current = null
    }
    wasOpen.current = isOpen
    return () => {
      if (fallbackTimer.current !== null) {
        window.clearTimeout(fallbackTimer.current)
        fallbackTimer.current = null
      }
    }
  }, [finishReturnFocus, isOpen, returnFocusRef])

  useEffect(() => {
    if (!isOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (locked) {
        event.preventDefault()
        event.stopImmediatePropagation()
        return
      }
      event.preventDefault()
      event.stopImmediatePropagation()
      onOpenChange(false)
    }
    window.addEventListener('keydown', closeOnEscape, true)
    return () => window.removeEventListener('keydown', closeOnEscape, true)
  }, [isOpen, locked, onOpenChange])

  return <Modal isOpen={isOpen} onOpenChange={(open) => {
    if (!open && locked) return
    onOpenChange(open)
  }}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开{title}</Modal.Trigger>
    <Modal.Backdrop isDismissable={!locked} onAnimationEnd={(event) => {
      if (event.target === event.currentTarget && event.currentTarget.dataset.exiting === 'true') finishReturnFocus()
    }}>
      <Modal.Container size="lg" scroll="inside"><Modal.Dialog><Modal.Header><Modal.Heading>{title}</Modal.Heading></Modal.Header><Modal.Body>{children}</Modal.Body><Modal.Footer><Button variant="ghost" isDisabled={locked} onPress={() => onOpenChange(false)}>{locked ? '正在保存…' : '关闭'}</Button></Modal.Footer></Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}
