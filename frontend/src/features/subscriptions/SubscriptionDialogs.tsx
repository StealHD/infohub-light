import { useState, type FormEvent } from 'react'

import { ApiError } from '../../api/client'
import type { CatalogField, CatalogSource, SecretRef, SourceTypeDefinition, Subscription, TaxonomyOptions } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '../../ui'
import { RefreshRounded } from '../../ui/icons'
import { formValuesForSource, sourceMutationPayload, sourceScopeLabel } from './subscriptionModel'

const splitList = (value: FormDataEntryValue | null) => String(value ?? '').split(',').map((part) => part.trim()).filter(Boolean)

function uniqueValues(values: string[]): string[] {
  const seen = new Set<string>()
  return values.map((value) => value.trim()).filter((value) => {
    const key = value.toLocaleLowerCase()
    if (!value || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function TopicPicker({ label, options, value, onChange }: {
  label: string
  options: string[]
  value: string[]
  onChange: (topics: string[]) => void
}) {
  const optionKeys = new Set(options.map((topic) => topic.toLocaleLowerCase()))
  return <Autocomplete
    multiple
    freeSolo
    filterSelectedOptions
    options={options}
    value={value}
    onChange={(_event, next) => onChange(uniqueValues(next.map(String)))}
    renderValue={(topics, getItemProps) => topics.map((topic, index) => {
      const { key, ...tagProps } = getItemProps({ index })
      const inactive = !optionKeys.has(topic.toLocaleLowerCase())
      return <Chip
        {...tagProps}
        key={key}
        label={inactive
          ? <Stack component="span" direction="row" spacing={0.75} sx={{ alignItems: 'center' }}><span>{topic}</span><Typography component="span" variant="caption">已停用</Typography></Stack>
          : topic}
      />
    })}
    renderInput={(params) => <TextField {...params} label={label} size="small" helperText="从主题库选择，或输入自定义主题后按回车" />}
  />
}

function fieldValue(field: CatalogField, form: FormData): unknown {
  if (field.input_type === 'checkbox' || field.input_type === 'boolean') return form.has(field.name)
  const raw = String(form.get(field.name) ?? '').trim()
  if (field.input_type === 'number') return raw === '' ? field.default : Number(raw)
  return raw
}

function RegistryFields({ definition, source }: { definition: SourceTypeDefinition; source?: CatalogSource }) {
  const values = formValuesForSource(definition, source)
  return <>{definition.fields.map((field) => {
    const value = values[field.name]
    const options = field.options ?? []
    if (options.length) return <TextField
      key={field.name}
      select
      fullWidth
      size="small"
      name={field.name}
      label={field.label}
      defaultValue={String(value ?? '')}
      required={field.required}
      helperText={field.help}
    >{options.map((option) => {
      const normalized = typeof option === 'string' ? { value: option, label: option } : option
      return <MenuItem key={normalized.value} value={normalized.value}>{normalized.label}</MenuItem>
    })}</TextField>
    if (field.input_type === 'checkbox' || field.input_type === 'boolean') return <FormControlLabel
      key={field.name}
      control={<Checkbox name={field.name} defaultChecked={Boolean(value)} />}
      label={<Box><Typography>{field.label}</Typography>{field.help && <Typography variant="caption" color="text.secondary">{field.help}</Typography>}</Box>}
    />
    return <TextField
      key={field.name}
      fullWidth
      size="small"
      name={field.name}
      label={field.label}
      type={field.input_type === 'number' ? 'number' : field.input_type === 'url' ? 'url' : 'text'}
      defaultValue={String(value ?? '')}
      required={field.required}
      helperText={field.help}
      slotProps={{ htmlInput: { min: field.min ?? undefined, max: field.max ?? undefined } }}
    />
  })}</>
}

export function SourceForm({ definition, source, secrets, allowSecret, scopes, onSubmit, submitLabel, taxonomy }: {
  definition: SourceTypeDefinition
  source?: CatalogSource
  secrets: SecretRef[]
  allowSecret: boolean
  scopes: CatalogSource['scope'][]
  onSubmit: (payload: Record<string, unknown>) => Promise<void>
  submitLabel: string
  taxonomy: TaxonomyOptions
}) {
  const feedback = useActionFeedback()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [defaultTopics, setDefaultTopics] = useState(source?.default_topics ?? [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const formElement = event.currentTarget
    setError('')
    setPending(true)
    const entity = source?.id ?? 'new'
    feedback.begin('source-save', entity)
    const form = new FormData(formElement)
    try {
      const advanced = String(form.get('advanced_config') ?? '').trim()
      const config = advanced ? JSON.parse(advanced) as Record<string, unknown> : {}
      for (const field of definition.fields) config[field.name] = fieldValue(field, form)
      await onSubmit(sourceMutationPayload({ source, allowSecret, config, metadata: {
        type: definition.type,
        display_name: String(form.get('display_name') ?? '').trim(),
        description: String(form.get('description') ?? '').trim(),
        scope: String(form.get('scope') ?? source?.scope ?? 'private'),
        default_channel: String(form.get('default_channel') ?? '').trim() || null,
        default_topics: defaultTopics,
        secret_env: String(form.get('secret_env') ?? '').trim() || null,
        enabled: form.has('enabled'),
      } }))
      feedback.succeed('source-save', entity)
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : caught instanceof SyntaxError ? '高级配置不是有效 JSON。' : '来源保存失败。'
      setError(message)
      feedback.fail('source-save', entity, message)
    } finally {
      setPending(false)
    }
  }

  return <Box component="form" onSubmit={submit} sx={{ py: 1 }}>
    <Stack spacing={2}>
      <TextField name="display_name" label="来源名称" required fullWidth size="small" defaultValue={source?.display_name ?? ''} />
      <TextField name="description" label="来源说明" fullWidth size="small" defaultValue={source?.description ?? ''} />
      {!source && <TextField select name="scope" label="可见范围" fullWidth size="small" defaultValue={scopes[0] ?? 'private'}>
        {scopes.map((scope) => <MenuItem key={scope} value={scope}>{sourceScopeLabel(scope)}</MenuItem>)}
      </TextField>}
      <RegistryFields definition={definition} source={source} />
      <TextField select name="default_channel" label="默认频道" fullWidth size="small" defaultValue={source?.default_channel ?? ''}>
        <MenuItem value="">未设置</MenuItem>
        {taxonomy.channels.map((channel) => <MenuItem key={channel} value={channel}>{channel}</MenuItem>)}
      </TextField>
      <TopicPicker label="默认主题" options={taxonomy.topics} value={defaultTopics} onChange={setDefaultTopics} />
      {allowSecret && <TextField select name="secret_env" label="Apify Key" fullWidth size="small" defaultValue={source?.secret_env ?? ''}>
        <MenuItem value="">不使用 Key</MenuItem>
        {secrets.filter((item) => item.kind === 'apify').map((item) => <MenuItem key={item.id} value={item.env_name}>{item.name} · {item.is_set ? '已设置' : '未设置'}</MenuItem>)}
      </TextField>}
      <FormControlLabel control={<Checkbox name="enabled" defaultChecked={source?.enabled ?? true} />} label="启用来源" />
      <Box component="details">
        <Typography component="summary" sx={{ cursor: 'pointer', fontWeight: 650 }}>高级配置</Typography>
        <TextField name="advanced_config" label="高级配置 JSON" multiline minRows={5} fullWidth sx={{ mt: 1.5 }} defaultValue={JSON.stringify(source?.config ?? {}, null, 2)} />
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      <Button type="submit" variant="contained" disabled={pending}>{pending ? '保存中…' : submitLabel}</Button>
    </Stack>
  </Box>
}

export function SubscriptionEditor({ subscription, source, readonly, onDone, onJob, taxonomy }: {
  subscription: Subscription
  source: CatalogSource
  readonly: boolean
  onDone: () => void
  onJob: (kind: 'test' | 'fetch', sourceId: string, subscriptionId: string) => Promise<void>
  taxonomy: TaxonomyOptions
}) {
  const { api, beginAction, isActionCurrent } = useAppContext()
  const feedback = useActionFeedback()
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const [overrideTopics, setOverrideTopics] = useState(subscription.override_topics ?? [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const submitter = (event.nativeEvent as SubmitEvent).submitter as HTMLButtonElement | null
    const intent = submitter?.value ?? 'save'
    const actionToken = beginAction()
    const feedbackAction = intent === 'unsubscribe' ? 'unsubscribe' : intent === 'test' ? 'source-test' : intent === 'fetch' ? 'source-fetch' : 'subscription-save'
    setPending(true)
    setError('')
    feedback.begin(feedbackAction, subscription.id)
    try {
      if (intent === 'unsubscribe') {
        await api.unsubscribe(subscription.id)
        feedback.succeed(feedbackAction, subscription.id)
        if (isActionCurrent(actionToken)) onDone()
        return
      }
      await api.updateSubscription(subscription.id, {
        enabled: form.has('enabled'),
        override_channel: String(form.get('override_channel') ?? '').trim() || null,
        override_topics: overrideTopics,
        personal_tags: splitList(form.get('personal_tags')),
        analysis_mode: String(form.get('analysis_mode')) as Subscription['analysis_mode'],
        priority: Number(form.get('priority') ?? 0),
      })
      if (!isActionCurrent(actionToken)) return
      await api.updateSourceSchedule(subscription.id, {
        enabled: form.has('enabled') && form.has('source_schedule_enabled'),
        interval_minutes: Number(form.get('source_schedule_interval') ?? subscription.schedule?.interval_minutes ?? 360),
      })
      if (!isActionCurrent(actionToken)) return
      if (intent === 'test' || intent === 'fetch') await onJob(intent, source.id, subscription.id)
      feedback.succeed(feedbackAction, subscription.id)
      if (isActionCurrent(actionToken)) onDone()
    } catch (caught) {
      const message = caught instanceof ApiError ? caught.message : '订阅保存失败。'
      setError(message)
      feedback.fail(feedbackAction, subscription.id, message)
    } finally {
      setPending(false)
    }
  }

  return <Box component="form" onSubmit={submit} sx={{ py: 1 }}>
    <Box component="fieldset" disabled={readonly || pending} sx={{ m: 0, p: 0, border: 0 }}>
      <Stack spacing={2}>
        <TextField select name="override_channel" label="个人频道" fullWidth size="small" defaultValue={subscription.override_channel ?? ''}>
          <MenuItem value="">继承来源默认频道</MenuItem>
          {taxonomy.channels.map((channel) => <MenuItem key={channel} value={channel}>{channel}</MenuItem>)}
        </TextField>
        <TopicPicker label="阅读主题" options={taxonomy.topics} value={overrideTopics} onChange={setOverrideTopics} />
        <TextField name="personal_tags" label="个人标签" helperText="多个标签使用逗号分隔" fullWidth size="small" defaultValue={(subscription.personal_tags ?? []).join(', ')} />
        <TextField select name="analysis_mode" label="分析模式" fullWidth size="small" defaultValue={subscription.analysis_mode ?? 'full'}>
          <MenuItem value="full">完整分析</MenuItem><MenuItem value="personal_only">仅收集</MenuItem>
        </TextField>
        <TextField name="priority" label="信源优先级" type="number" fullWidth size="small" defaultValue={subscription.priority ?? 0} slotProps={{ htmlInput: { min: 0, max: 100 } }} />
        <FormControlLabel control={<Checkbox name="enabled" defaultChecked={subscription.enabled} />} label="启用订阅" />
        <TextField select name="source_schedule_interval" label="单源自动获取" fullWidth size="small" defaultValue={subscription.schedule?.interval_minutes ?? 360}>
          {(subscription.schedule?.allowed_intervals ?? [30, 60, 180, 360, 720, 1440]).map((value) => <MenuItem key={value} value={value}>{value === 30 ? '每 30 分钟' : `每 ${value / 60} 小时`}</MenuItem>)}
        </TextField>
        <FormControlLabel control={<Checkbox name="source_schedule_enabled" defaultChecked={subscription.schedule?.enabled ?? false} />} label="启用单源周期" />
      </Stack>
    </Box>
    {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
    {!readonly && <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 3, flexWrap: 'wrap' }}>
      <Button type="submit" name="intent" value="save" variant="contained">保存订阅</Button>
      <Button type="submit" name="intent" value="test">测试连接</Button>
      <Button type="submit" name="intent" value="fetch" startIcon={<RefreshRounded />}>保存并立即抓取</Button>
      <Button type="submit" name="intent" value="unsubscribe" color="error">取消订阅</Button>
    </Stack>}
  </Box>
}
