import { useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { queryStaleTime } from '../../api/queryPolicy'
import type {
  ApifyKeyPoolMember,
  SecretRef,
  StorageOperation,
  StoragePlan,
} from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { useActionFeedback } from '../../app/ActionFeedback'
import {
  actionToast,
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
  StatusIndicator,
  Table,
  TextField,
} from '../../design-system'
import {
  aiDefaultsForProvider,
  canAdministerWorkspace,
  secretPresentation,
} from '../settings/settingsModel'
import { PRODUCT_RELEASES_URL } from '../documentation/documentationLinks'
import { HeroEmailTransportSettings } from '../notifications/HeroEmailTransportSettings'
import { HeroNotificationSettings } from '../notifications/HeroNotificationSettings'
import { AdminPageHeader, AdminSection, HeroNotice, HeroSelect } from './HeroAdminControls'
import { HeroTopicLibrary } from './HeroTopicLibrary'
import { settingsSectionFromHash, settingsSectionsForRole } from './settingsSections'

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
const isApifySecret = (secret: SecretRef) => secret.kind === 'apify' || secret.provider === 'apify'
const secretQuotaStaleTime = 5 * 60 * 1000

type SecretDraft = {
  name: string
  kind: string
  provider: string
  envName: string
  value: string
}

type CoreSettingsSection = 'ai' | 'feed_end_messages' | 'rsshub' | 'filtering' | 'topics'
type FeedEndMessageScene = 'empty' | 'first_end' | 'repeat_end'
type CoreSettingsBundle = Partial<Record<CoreSettingsSection, Record<string, unknown>>>
type CoreSettingsSave = {
  sections: CoreSettingsSection[]
  payload: CoreSettingsBundle
  revisions: Record<CoreSettingsSection, number>
}

const coreSettingsOrder: CoreSettingsSection[] = ['ai', 'feed_end_messages', 'rsshub', 'filtering', 'topics']
const emptySecretDraft: SecretDraft = { name: '', kind: 'ai', provider: '', envName: '', value: '' }
const sameSettingsPayload = (left: Record<string, unknown>, right: Record<string, unknown>) => JSON.stringify(left) === JSON.stringify(right)

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

const poolStatusLabels: Record<string, string> = {
  empty: '尚未配置 Key',
  ready: '可以启动新任务',
  active: '运行中',
  draining: '正在安全排空',
  blocked: '已阻塞，等待人工核对',
  exhausted: '所有 Key 额度均已用尽',
  disabled: '尚未启用',
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

const memberStatusPresentation: Record<ApifyKeyPoolMember['status'], {
  label: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}> = {
  active: { label: '主用', tone: 'success' },
  standby: { label: '备用', tone: 'neutral' },
  draining: { label: '排空中', tone: 'warning' },
  depleted: { label: '额度已用尽', tone: 'warning' },
  invalid: { label: 'Key 无效', tone: 'danger' },
}

const memberErrorLabels: Record<string, string> = {
  quota_exhausted: '额度不足，等待下个周期',
  apify_quota_exhausted: '额度不足，等待下个周期',
  apify_credits_depleted: '额度不足，等待下个周期',
  invalid_token: 'Key 无效，请排空后轮换',
  apify_invalid_token: 'Key 无效，请排空后轮换',
  apify_token_invalid: 'Key 无效，请排空后轮换',
  run_outcome_unknown: '启动结果未知，需要人工核对',
  apify_start_outcome_unknown: '启动结果未知，需要人工核对',
  apify_restart_start_outcome_unknown: '重启后启动结果未知，需要人工核对',
}

function ApifyPoolStatusCell({ member }: { member: ApifyKeyPoolMember | null }) {
  if (!member) return <div className="min-w-48">
    <p className="type-control">等待加入池</p>
    <p className="type-meta mt-1 text-muted">刷新后仍未加入时，请检查服务状态</p>
  </div>

  const presentation = memberStatusPresentation[member.status] ?? { label: '状态未知', tone: 'neutral' as const }
  return <div className="min-w-52">
    <StatusIndicator
      label={presentation.label}
      tone={presentation.tone}
      icon={member.status === 'draining'
        ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
        : member.status === 'active'
          ? <Icons.CircleCheck size={13} aria-hidden="true" />
          : member.status === 'invalid'
            ? <Icons.CircleX size={13} aria-hidden="true" />
            : member.status === 'depleted'
              ? <Icons.TriangleAlert size={13} aria-hidden="true" />
              : <Icons.CircleDashed size={13} aria-hidden="true" />}
    />
    <p className="type-meta mt-2 text-muted">
      {member.active_run_count > 0 ? `${member.active_run_count} 个运行中任务` : '没有运行中任务'}
    </p>
    {member.blocked_until && <p className="type-meta mt-1 text-muted">受阻至 {formatDateTime(member.blocked_until)}</p>}
    {member.cycle_end_at && <p className="type-meta mt-1 text-muted">额度周期至 {formatDateTime(member.cycle_end_at)}</p>}
    <p className="type-meta mt-1 text-muted">最近检查 {formatDateTime(member.last_checked_at)}</p>
    {member.last_error_code && <p className="type-meta mt-1 text-danger">
      {memberErrorLabels[member.last_error_code] ?? 'Key 需要管理员检查'}
    </p>}
  </div>
}

function FormField({ label, name, defaultValue = '', type = 'text', min, max, required = false }: {
  label: string; name: string; defaultValue?: string | number; type?: string; min?: number; max?: number; required?: boolean
}) {
  return <TextField fullWidth name={name} defaultValue={String(defaultValue)} isRequired={required}><Label>{label}</Label><Input type={type} min={min} max={max} /></TextField>
}

function SecretQuotaCell({ secret, userId }: { secret: SecretRef; userId: string }) {
  const { api } = useAppContext()
  const supported = isApifySecret(secret)
  const [manualAction, setManualAction] = useState<'refresh' | 'retry' | null>(null)
  const [retryError, setRetryError] = useState<unknown>(null)
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

  async function refetchQuota(action: 'refresh' | 'retry') {
    if (action === 'retry') setRetryError(quota.error)
    setManualAction(action)
    try {
      await quota.refetch()
    } finally {
      setManualAction(null)
    }
  }

  if (!supported) return <span className="type-meta text-muted">暂不支持查询</span>
  if (!secret.is_set) return <span className="type-meta text-muted">Key 未配置，无法查询</span>
  const retrying = manualAction === 'retry'
  const retryBusy = retrying || quota.isFetching
  if (!quota.data && (quota.isError || retrying)) {
    return <div className="min-w-56" role="alert" aria-busy={retryBusy}>
      <p className="type-meta text-danger">{errorMessage(
        quota.isError ? quota.error : retryError,
        '额度查询失败，请稍后重试。',
      )}</p>
      <Button
        className="mt-1"
        size="sm"
        variant="ghost"
        aria-label={retryBusy ? `正在重试 ${secret.name} 额度` : `重试 ${secret.name} 额度`}
        isDisabled={retryBusy}
        onPress={() => void refetchQuota('retry')}
      ><Icons.RefreshCw size={14} className={retryBusy ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />{retryBusy ? '重试中…' : '重试'}</Button>
    </div>
  }
  if (quota.isPending) return <span className="type-meta text-muted" aria-live="polite">正在查询额度…</span>
  if (!quota.data) return <span className="type-meta text-muted">暂无额度数据</span>

  const refreshing = manualAction === 'refresh' || (quota.isFetching && !retrying)
  const refreshError = quota.isError || retrying
    ? errorMessage(quota.isError ? quota.error : retryError, '额度刷新失败，请稍后重试。')
    : null
  return <div className="min-w-64" aria-live="polite" aria-busy={refreshing || retryBusy}>
    <p className="type-control">套餐剩余 {formatUsd(quota.data.remaining_included_credits_usd)}</p>
    <p className="type-meta mt-1 text-muted">
      本月已用 {formatUsd(quota.data.monthly_usage_usd)} · 硬上限剩余 {formatUsd(quota.data.remaining_hard_limit_usd)}
    </p>
    <div className="mt-1 flex items-center gap-2">
      <span className="type-meta text-muted">周期至 {formatCycleEnd(quota.data.cycle_end_at)}</span>
      {refreshError ? (
        <Button
          size="sm"
          variant="ghost"
          aria-label={retryBusy ? `正在重试 ${secret.name} 额度` : `重试 ${secret.name} 额度`}
          isDisabled={retryBusy}
          onPress={() => void refetchQuota('retry')}
        ><Icons.RefreshCw size={14} className={retryBusy ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />{retryBusy ? '重试中…' : '重试'}</Button>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          isIconOnly
          aria-label={refreshing ? `正在刷新 ${secret.name} 额度` : `刷新 ${secret.name} 额度`}
          isDisabled={refreshing}
          onPress={() => void refetchQuota('refresh')}
        ><Icons.RefreshCw size={14} className={refreshing ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" /></Button>
      )}
      {refreshing && <span className="sr-only" role="status">正在刷新 {secret.name} 额度</span>}
      {refreshError && retryBusy && <span className="sr-only" role="status">正在重试 {secret.name} 额度</span>}
    </div>
    {refreshError && <p className="type-meta mt-1 text-danger" role="alert">{refreshError}</p>}
  </div>
}

function SecretRowActions({ secret, onChanged, lifecycleLocked = false, lockMessage = '请先安全排空，再轮换或删除' }: {
  secret: SecretRef
  onChanged: (secretId: string, action: 'rotate' | 'delete') => void
  lifecycleLocked?: boolean
  lockMessage?: string
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
      actionToast.success('Key 已轮换', { description: secret.name })
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
      actionToast.success('Key 已删除', { description: secret.name })
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
      <Button ref={rotateTriggerRef} size="sm" type="button" variant="ghost" aria-label={`轮换 ${secret.name}`} isDisabled={lifecycleLocked}>轮换</Button>
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
        <Button ref={deleteTriggerRef} size="sm" type="button" variant="danger" aria-label={`删除 ${secret.name}`} isDisabled={lifecycleLocked || secret.used_by.length > 0 || removing}>删除</Button>
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
    {lifecycleLocked && <span className="type-meta basis-full text-muted">{lockMessage}</span>}
  </div>
}

function apifyPoolActionError(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError && (
    caught.code === 'apify_key_pool_generation_conflict'
    || caught.code === 'apify_key_pool_conflict'
  )) {
    return 'Key 池刚刚发生变化，已刷新最新顺序，请重试。'
  }
  return errorMessage(caught, fallback)
}

function ApifyKeyPoolTable({ secrets, userId, onSecretChanged }: {
  secrets: SecretRef[]
  userId: string
  onSecretChanged: (secretId: string, action: 'rotate' | 'delete') => void
}) {
  const { api } = useAppContext()
  const queryClient = useQueryClient()
  const poolQuery = useQuery({
    queryKey: queryKeys.apifyKeyPool(userId),
    queryFn: ({ signal }) => api.apifyKeyPool(signal),
    retry: false,
    refetchOnWindowFocus: false,
    refetchInterval: (query) => query.state.data?.status === 'draining' ? 2_000 : false,
  })
  const orderMutation = useMutation({
    mutationFn: ({ secretIds, expectedGeneration }: { secretIds: string[]; expectedGeneration: number }) => (
      api.reorderApifyKeyPool(secretIds, expectedGeneration)
    ),
    onSuccess: (pool) => {
      queryClient.setQueryData(queryKeys.apifyKeyPool(userId), pool)
      actionToast.success('Apify Key 顺序已更新')
    },
    onError: (caught, variables) => {
      const message = apifyPoolActionError(caught, 'Key 顺序更新失败，请稍后重试。')
      if (caught instanceof ApiError && (
        caught.code === 'apify_key_pool_generation_conflict'
        || caught.code === 'apify_key_pool_conflict'
      )) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(userId) })
      }
      actionToast.danger('Key 顺序更新失败', {
        description: message,
        onRetry: () => {
          if (!orderMutation.isPending) orderMutation.mutate(variables)
        },
      })
    },
  })
  const drainMutation = useMutation({
    mutationFn: (secretId: string) => api.drainApifyKey(secretId),
    onSuccess: (pool, secretId) => {
      queryClient.setQueryData(queryKeys.apifyKeyPool(userId), pool)
      const secret = secrets.find((item) => item.id === secretId)
      actionToast.success('已提交安全排空', { description: secret?.name })
    },
    onError: (caught, secretId) => {
      const message = apifyPoolActionError(caught, '安全排空失败，请稍后重试。')
      actionToast.danger('安全排空失败', {
        description: message,
        onRetry: () => {
          if (!drainMutation.isPending) drainMutation.mutate(secretId)
        },
      })
    },
  })

  const apifySecrets = secrets.filter(isApifySecret)
  const secretsById = new Map(apifySecrets.map((secret) => [secret.id, secret]))
  const orderedMembers = [...(poolQuery.data?.members ?? [])].sort((left, right) => left.position - right.position)
  const memberIds = new Set(orderedMembers.map((member) => member.secret_id))
  const rows: Array<{ secret: SecretRef; member: ApifyKeyPoolMember | null }> = [
    ...orderedMembers.flatMap((member) => {
      const secret = secretsById.get(member.secret_id)
      return secret ? [{ secret, member }] : []
    }),
    ...apifySecrets.filter((secret) => !memberIds.has(secret.id)).map((secret) => ({ secret, member: null })),
  ]
  const unresolvedMembers = orderedMembers.filter((member) => !secretsById.has(member.secret_id)).length
  const poolBusy = poolQuery.data?.enabled === true && (
    poolQuery.data.status === 'draining'
    || poolQuery.data.status === 'blocked'
  )

  function moveMember(secretId: string, offset: -1 | 1) {
    const pool = poolQuery.data
    if (!pool || orderMutation.isPending || drainMutation.isPending || poolBusy) return
    const members = [...pool.members].sort((left, right) => left.position - right.position)
    const index = members.findIndex((member) => member.secret_id === secretId)
    const target = index + offset
    if (index < 0 || target < 0 || target >= members.length) return
    const memberLocked = (member: ApifyKeyPoolMember) => pool.enabled && (
      member.status === 'active'
      || member.status === 'draining'
      || member.active_run_count > 0
      || pool.active_secret_id === member.secret_id
    )
    if (memberLocked(members[index]) || memberLocked(members[target])) return
    const reordered = [...members]
    const [moving] = reordered.splice(index, 1)
    reordered.splice(target, 0, moving)
    orderMutation.mutate({
      secretIds: reordered.map((member) => member.secret_id),
      expectedGeneration: pool.generation,
    })
  }

  const poolStatus = poolQuery.data
    ? poolStatusLabels[poolQuery.data.status] ?? '状态需要检查'
    : '正在读取'
  const activeName = poolQuery.data?.active_secret_id
    ? secretsById.get(poolQuery.data.active_secret_id)?.name
    : null
  const poolTone = poolQuery.data?.status === 'ready'
    ? 'success'
    : poolQuery.data?.status === 'blocked' || poolQuery.data?.status === 'exhausted'
      ? 'danger'
      : poolQuery.data?.status === 'draining'
        ? 'warning'
        : 'neutral'
  const poolIcon = poolQuery.data?.status === 'draining'
    ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
    : poolQuery.data?.status === 'ready'
      ? <Icons.CircleCheck size={13} aria-hidden="true" />
      : poolQuery.data?.status === 'blocked' || poolQuery.data?.status === 'exhausted'
        ? <Icons.CircleX size={13} aria-hidden="true" />
        : <Icons.CircleDashed size={13} aria-hidden="true" />

  return <Card variant="secondary" className="p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <Card.Title>Apify Key 池</Card.Title>
        <Card.Description className="mt-1">
          所有 Apify 来源统一使用此池；额度不足时先停止旧 Key 的任务，再切换到下一备用 Key。
        </Card.Description>
      </div>
      <StatusIndicator label={poolStatus} tone={poolTone} icon={poolIcon} />
    </div>
    {poolQuery.isPending && <div className="mt-4"><LoadingState label="正在读取 Apify Key 池" rows={1} /></div>}
    {poolQuery.isError && <div className="mt-4"><HeroNotice title="Apify Key 池读取失败">
      为避免误操作，池状态恢复前不会提供排序或排空操作。
    </HeroNotice></div>}
    {poolQuery.data && !poolQuery.data.enabled && <div className="mt-4"><HeroNotice title="Apify Key 池尚未启用" status="warning" role="status">
      当前仍处于兼容阶段；可以预先维护备用顺序，但不会自动切换。
    </HeroNotice></div>}
    {poolQuery.data?.enabled && <p className="type-meta mt-3 text-muted">
      {activeName ? `当前主用：${activeName}` : '当前没有可用的主用 Key'} · {poolStatus}
    </p>}
    {unresolvedMembers > 0 && <div className="mt-4"><HeroNotice title="部分 Key 元数据尚未加载" status="warning" role="status">
      已隐藏无法安全识别的池成员，请刷新页面后再操作。
    </HeroNotice></div>}
    <div className="mt-4 min-w-0 max-w-full">
      <Table variant="secondary" className="max-w-full">
        <Table.ScrollContainer className="max-w-full overflow-x-auto" data-testid="apify-key-pool-scroll">
          <Table.Content aria-label="Apify Key 池">
            <Table.Header>
              <Table.Column isRowHeader>Key</Table.Column>
              <Table.Column>池状态</Table.Column>
              <Table.Column>额度</Table.Column>
              <Table.Column>操作</Table.Column>
            </Table.Header>
            <Table.Body
              items={rows}
              renderEmptyState={() => <div className="p-6 text-center text-muted">尚未配置 Apify Key</div>}
            >
              {({ secret, member }) => {
                const memberIndex = member ? orderedMembers.findIndex((item) => item.secret_id === member.secret_id) : -1
                const poolEnabled = poolQuery.data?.enabled === true
                const poolStateUnknown = poolEnabled && !member
                const lifecycleLocked = poolStateUnknown || (
                  poolEnabled && Boolean(member && (
                    member.status === 'active'
                    || member.status === 'draining'
                    || member.active_run_count > 0
                    || poolQuery.data?.active_secret_id === secret.id
                  ))
                )
                const controlsDisabled = !member || poolQuery.isError || orderMutation.isPending || drainMutation.isPending || poolBusy
                const previousMember = memberIndex > 0 ? orderedMembers[memberIndex - 1] : null
                const nextMember = memberIndex >= 0 && memberIndex < orderedMembers.length - 1 ? orderedMembers[memberIndex + 1] : null
                const neighborLocked = (candidate: ApifyKeyPoolMember | null) => poolEnabled && Boolean(candidate && (
                  candidate.status === 'active'
                  || candidate.status === 'draining'
                  || candidate.active_run_count > 0
                  || poolQuery.data?.active_secret_id === candidate.secret_id
                ))
                const draining = drainMutation.isPending && drainMutation.variables === secret.id
                const canDrain = Boolean(
                  poolQuery.data?.enabled
                  && member
                  && (lifecycleLocked || poolQuery.data.active_secret_id === secret.id),
                )
                return <Table.Row id={secret.id}>
                  <Table.Cell>
                    <div className="min-w-44">
                      <p className="type-control">{secret.name}</p>
                      <code className="type-meta text-muted">{secret.env_name}</code>
                    </div>
                  </Table.Cell>
                  <Table.Cell><ApifyPoolStatusCell member={member} /></Table.Cell>
                  <Table.Cell><SecretQuotaCell secret={secret} userId={userId} /></Table.Cell>
                  <Table.Cell>
                    <div className="flex min-w-64 flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        isIconOnly
                        aria-label={`上移 ${secret.name}`}
                        isDisabled={controlsDisabled || memberIndex <= 0 || lifecycleLocked || neighborLocked(previousMember)}
                        onPress={() => moveMember(secret.id, -1)}
                      ><Icons.ArrowUp size={14} aria-hidden="true" /></Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        isIconOnly
                        aria-label={`下移 ${secret.name}`}
                        isDisabled={controlsDisabled || memberIndex < 0 || memberIndex >= orderedMembers.length - 1 || lifecycleLocked || neighborLocked(nextMember)}
                        onPress={() => moveMember(secret.id, 1)}
                      ><Icons.ArrowDown size={14} aria-hidden="true" /></Button>
                      {canDrain && <Button
                        size="sm"
                        variant="secondary"
                        aria-label={`安全排空 ${secret.name}`}
                        isDisabled={draining || member?.status === 'draining' || poolQuery.data?.status === 'blocked'}
                        onPress={() => drainMutation.mutate(secret.id)}
                      ><Icons.CircleStop size={14} aria-hidden="true" />{draining || member?.status === 'draining' ? '排空中…' : '安全排空'}</Button>}
                      <SecretRowActions
                        secret={secret}
                        lifecycleLocked={lifecycleLocked}
                        lockMessage={poolStateUnknown ? '池状态确认前不可轮换或删除' : undefined}
                        onChanged={onSecretChanged}
                      />
                    </div>
                  </Table.Cell>
                </Table.Row>
              }}
            </Table.Body>
          </Table.Content>
        </Table.ScrollContainer>
      </Table>
    </div>
  </Card>
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

function StorageArchiveSettings() {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [activePlan, setActivePlan] = useState<StoragePlan | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const summary = useQuery({
    queryKey: queryKeys.storageSummary(user.id),
    queryFn: ({ signal }) => api.storageSummary(signal),
  })
  const archives = useQuery({
    queryKey: queryKeys.storageArchives(user.id),
    queryFn: ({ signal }) => api.storageArchives(signal),
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
    {summary.isLoading
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
      {archives.isLoading && <div className="mt-4"><LoadingState label="正在读取归档批次" rows={2} /></div>}
      {archives.isError && <div className="mt-4"><HeroNotice title="归档批次读取失败" status="warning" /></div>}
      {!archives.isLoading && !archives.isError && !(archives.data?.archives.length) && <p className="type-meta mt-4 text-muted">尚无归档批次。</p>}
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
  const config = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal), staleTime: queryStaleTime.settings })
  const feedEndMessagesStatus = useQuery({
    queryKey: queryKeys.feedEndMessages(user.id),
    queryFn: ({ signal }) => api.feedEndMessages(signal),
    enabled: admin,
    staleTime: queryStaleTime.settings,
    retry: false,
    refetchInterval: (query) => ['pending', 'refreshing'].includes(
      query.state.data?.status ?? '',
    ) ? 2_000 : false,
  })
  const ignored = useQuery({ queryKey: queryKeys.ignored(user.id), queryFn: ({ signal }) => api.ignoredFeed(200, 0, signal), staleTime: queryStaleTime.collection })
  const secrets = useQuery({ queryKey: queryKeys.secrets(user.id), queryFn: ({ signal }) => api.secrets(signal), enabled: admin })
  const [aiOverride, setAiOverride] = useState<{ provider: string; model: string; apiKeyEnv: string } | null>(null)
  const [feedEndRefreshDaysOverride, setFeedEndRefreshDaysOverride] = useState<string | null>(null)
  const [feedEndStyleOverride, setFeedEndStyleOverride] = useState<string | null>(null)
  const [expandedFeedEndScenes, setExpandedFeedEndScenes] = useState<Set<FeedEndMessageScene>>(() => new Set())
  const [secretDraft, setSecretDraft] = useState<SecretDraft>(emptySecretDraft)
  const [secretFieldErrors, setSecretFieldErrors] = useState<SecretFieldErrors>({})
  const [secretFormError, setSecretFormError] = useState('')
  const [rssInitialFetchWindowOverride, setRssInitialFetchWindowOverride] = useState<string | null>(null)
  const [feedWindowDaysOverride, setFeedWindowDaysOverride] = useState<string | null>(null)
  const [topicsOverride, setTopicsOverride] = useState<string[] | null>(null)
  const [dirtyCoreSections, setDirtyCoreSections] = useState<Set<CoreSettingsSection>>(() => new Set())
  const coreRevisions = useRef<Record<CoreSettingsSection, number>>({
    ai: 0,
    feed_end_messages: 0,
    rsshub: 0,
    filtering: 0,
    topics: 0,
  })
  const aiFormRef = useRef<HTMLFormElement>(null)
  const feedEndMessagesFormRef = useRef<HTMLFormElement>(null)
  const rsshubFormRef = useRef<HTMLFormElement>(null)
  const filteringFormRef = useRef<HTMLFormElement>(null)
  const [activeSection, setActiveSection] = useState<string>(
    () => settingsSectionFromHash(location.hash, user.role)?.id ?? 'settings-about',
  )
  const ai = recordOf(config.data?.config.ai)
  const configuredAiProvider = String(ai.provider ?? 'gemini')
  const configuredAiDefaults = aiDefaultsForProvider(configuredAiProvider)
  const configuredAiDraft = {
    provider: configuredAiProvider,
    model: String(ai.model ?? configuredAiDefaults.model),
    apiKeyEnv: String(ai.api_key_env ?? ''),
  }
  const aiDraft = aiOverride ?? configuredAiDraft
  const feedEndMessages = recordOf(config.data?.config.feed_end_messages)
  const feedEndRefreshDays = feedEndRefreshDaysOverride
    ?? String(feedEndMessages.refresh_days ?? 7)
  const feedEndStyle = feedEndStyleOverride
    ?? String(feedEndMessages.style_preset ?? 'restrained')
  const savedFeedEndGenerationEnabled = ai.enabled !== false
    && feedEndMessages.ai_generation_enabled === true
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
  const aiDraftRef = useRef(aiDraft)
  const topicsDraftRef = useRef(topicsDraft)
  useLayoutEffect(() => {
    aiDraftRef.current = aiDraft
    topicsDraftRef.current = topicsDraft
  }, [aiDraft, topicsDraft])
  const rsshubAccessKeySet = (config.data?.env_status ?? []).some(
    (item) => item.name === 'RSSHUB_ACCESS_KEY' && item.set === true,
  )
  const sectionOptions = useMemo(() => settingsSectionsForRole(user.role), [user.role])
  const secretDirty = Object.entries(secretDraft).some(([key, value]) => value !== emptySecretDraft[key as keyof SecretDraft])
  const settingsDirty = dirtyCoreSections.size > 0 || secretDirty

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
          !sameSettingsPayload(payloadFor(section), configuredPayloadFor(section)),
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
    const section = settingsSectionFromHash(location.hash, user.role)
    if (!section) return
    const frame = window.requestAnimationFrame(() => {
      setActiveSection(section.id)
      const target = document.getElementById(section.id)
      target?.scrollIntoView?.({
        block: 'start',
        behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      })
      target?.focus({ preventScroll: true })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [location.hash, user.role])

  useEffect(() => {
    if (typeof IntersectionObserver === 'undefined') return
    const targets = sectionOptions
      .map((section) => document.getElementById(section.id))
      .filter((target): target is HTMLElement => Boolean(target))
    if (!targets.length) return
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => Math.abs(left.boundingClientRect.top) - Math.abs(right.boundingClientRect.top))
      const id = visible[0]?.target.id
      if (!id || id === activeSection) return
      setActiveSection(id)
      const nextUrl = `${window.location.pathname}${window.location.search}#${id}`
      window.history.replaceState(window.history.state, '', nextUrl)
    }, {
      rootMargin: '-12% 0px -68% 0px',
      threshold: [0, 0.01, 0.5],
    })
    targets.forEach((target) => observer.observe(target))
    return () => observer.disconnect()
  }, [activeSection, sectionOptions])

  function jumpToSection(id: string) {
    if (!sectionOptions.some((section) => section.id === id)) return
    setActiveSection(id)
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
    const apifySecret = (secrets.data?.secrets ?? []).some((secret) => secret.id === secretId && isApifySecret(secret))
    if (action === 'rotate') {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.secretQuota(user.id, secretId) }),
        ...(apifySecret
          ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(user.id) })]
          : []),
      ])
      return
    }
    queryClient.removeQueries({ queryKey: queryKeys.secretQuota(user.id, secretId) })
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
      ...(apifySecret
        ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(user.id) })]
        : []),
    ])
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
      if (savedWithoutNewerEdits.includes('ai')) setAiOverride(null)
      if (savedWithoutNewerEdits.includes('feed_end_messages')) {
        setFeedEndRefreshDaysOverride(null)
        setFeedEndStyleOverride(null)
      }
      if (savedWithoutNewerEdits.includes('filtering')) {
        setRssInitialFetchWindowOverride(null)
        setFeedWindowDaysOverride(null)
      }
      if (savedWithoutNewerEdits.includes('topics')) setTopicsOverride(null)
      if (result?.config) queryClient.setQueryData(queryKeys.config(user.id), result)
      actionToast.success(submitted.sections.length > 1 ? '全部配置已保存' : '设置已保存')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) }),
        ...(submitted.sections.some((section) => section === 'ai' || section === 'feed_end_messages')
          ? [queryClient.invalidateQueries({ queryKey: queryKeys.feedEndMessages(user.id) })]
          : []),
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
  const feedEndMessagesRefreshMutation = useMutation({
    mutationFn: () => api.refreshFeedEndMessages(),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.feedEndMessages(user.id), result)
      actionToast.success('已标记触底文案刷新', {
        description: 'Worker 会在普通任务队列空闲后处理。',
      })
    },
    onError: (caught) => actionToast.danger('触底文案刷新请求失败', {
      description: errorMessage(caught, '请稍后重试。'),
    }),
  })
  const restoreMutation = useMutation({
    mutationFn: (articleId: string) => api.updateItemState(articleId, { dismissed: false }),
    onSuccess: async (_result, articleId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.ignored(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.feed(user.id, { hideDismissed: false, unreadFirst: false }) }),
      ])
      const restored = ignored.data?.items.find((item) => item.id === articleId)
      actionToast.success('已恢复到信息流', { description: restored?.presentation?.content?.title || restored?.title })
    },
    onError: (caught) => actionToast.danger('恢复失败', { description: errorMessage(caught, '请稍后重试。') }),
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
      actionToast.danger('新增 Key 失败', { description: message })
      return
    }
    feedback.begin('secret-create', 'new')
    try {
      await api.createSecret(submitted)
      setSecretDraft(emptySecretDraft)
      setSecretFieldErrors({})
      setSecretFormError('')
      feedback.clear('secret-create', 'new')
      actionToast.success('Key 已安全保存')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
        ...(submitted.kind === 'apify'
          ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(user.id) })]
          : []),
      ])
    } catch (caught) {
      const message = secretCreateErrorMessage(caught)
      setSecretFormError(message)
      feedback.fail('secret-create', 'new', message)
      actionToast.danger('新增 Key 失败', { description: message })
    }
  }


  function aiPayload(): Record<string, unknown> {
    if (!aiFormRef.current) throw new Error('AI 设置表单尚未加载')
    const data = new FormData(aiFormRef.current)
    const currentAiDraft = aiDraftRef.current
    return {
      enabled: data.has('enabled'), provider: currentAiDraft.provider, model: currentAiDraft.model, api_key_env: currentAiDraft.apiKeyEnv, base_url: inputValue(data, 'base_url'), languages: inputValue(data, 'languages') || 'zh',
      analysis_content_chars: Number(data.get('analysis_content_chars')), analysis_comments_chars: Number(data.get('analysis_comments_chars')), summary_max_chars: Number(data.get('summary_max_chars')), analysis_max_output_tokens: Number(data.get('analysis_max_output_tokens')), enrichment_content_chars: Number(ai.enrichment_content_chars ?? 4000),
    }
  }

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

  function feedEndMessagesPayload(): Record<string, unknown> {
    if (!feedEndMessagesFormRef.current) throw new Error('触底文案设置表单尚未加载')
    const data = new FormData(feedEndMessagesFormRef.current)
    return {
      ai_generation_enabled: data.has('ai_generation_enabled'),
      refresh_days: Number(data.get('refresh_days')),
      style_preset: String(data.get('style_preset') || 'restrained'),
      style_prompt: inputValue(data, 'style_prompt'),
      list_count: Number(data.get('list_count')),
    }
  }

  function rsshubPayload(): Record<string, unknown> {
    if (!rsshubFormRef.current) throw new Error('RSSHub 设置表单尚未加载')
    return { base_url: inputValue(new FormData(rsshubFormRef.current), 'base_url') }
  }

  function reportSectionValidity(section: CoreSettingsSection): boolean {
    const form = section === 'ai'
      ? aiFormRef.current
      : section === 'feed_end_messages'
        ? feedEndMessagesFormRef.current
      : section === 'rsshub'
        ? rsshubFormRef.current
        : section === 'filtering'
          ? filteringFormRef.current
          : null
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

  function payloadFor(section: CoreSettingsSection): Record<string, unknown> {
    if (section === 'ai') return aiPayload()
    if (section === 'feed_end_messages') return feedEndMessagesPayload()
    if (section === 'rsshub') return rsshubPayload()
    if (section === 'filtering') return filteringPayload()
    return { topics: topicsDraftRef.current }
  }

  function configuredPayloadFor(section: CoreSettingsSection): Record<string, unknown> {
    if (section === 'ai') {
      return {
        enabled: ai.enabled !== false,
        provider: configuredAiDraft.provider,
        model: configuredAiDraft.model,
        api_key_env: configuredAiDraft.apiKeyEnv,
        base_url: String(ai.base_url ?? '').trim(),
        languages: Array.isArray(ai.languages) ? ai.languages.join(',').trim() || 'zh' : 'zh',
        analysis_content_chars: Number(ai.analysis_content_chars ?? 1000),
        analysis_comments_chars: Number(ai.analysis_comments_chars ?? 1500),
        summary_max_chars: Number(ai.summary_max_chars ?? 200),
        analysis_max_output_tokens: Number(ai.analysis_max_output_tokens ?? 800),
        enrichment_content_chars: Number(ai.enrichment_content_chars ?? 4000),
      }
    }
    if (section === 'rsshub') {
      return { base_url: String(rsshub.base_url ?? 'http://rsshub:1200').trim() }
    }
    if (section === 'feed_end_messages') {
      return {
        ai_generation_enabled: feedEndMessages.ai_generation_enabled === true,
        refresh_days: Number(feedEndMessages.refresh_days ?? 7),
        style_preset: String(feedEndMessages.style_preset ?? 'restrained'),
        style_prompt: String(feedEndMessages.style_prompt ?? '').trim(),
        list_count: Number(feedEndMessages.list_count ?? 12),
      }
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

  function saveAi(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveCoreSections(['ai'])
  }

  function saveFeedEndMessages(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveCoreSections(['feed_end_messages'])
  }

  function saveFiltering(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveCoreSections(['filtering'])
  }

  function saveRsshub(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    saveCoreSections(['rsshub'])
  }

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
    {settingsDirty && <div
      data-settings-dirty-notice
      className="fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-40 ml-auto max-w-md min-[768px]:bottom-4 min-[768px]:left-auto min-[768px]:right-4"
    >
      <HeroNotice title="有尚未保存的更改" status="warning" role="status">
        <div className="flex flex-wrap items-center gap-3">
          <span className="min-w-0 flex-1">
            {dirtyCoreSections.size > 0
              ? `${dirtyCoreSections.size} 项核心配置待保存${secretDirty ? '；Key 草稿仍需单独保存' : ''}。`
              : 'Key 草稿需要通过密钥表单单独保存。'}
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

    <AdminSection id="settings-about" title="关于 Inteliscope" description="查阅操作方法、产品变化和正式发布记录。">
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" onPress={() => navigate('/manual')}><Icons.BookOpen size={16} aria-hidden="true" />查看操作手册</Button>
        <Button size="sm" variant="secondary" onPress={() => navigate('/changelog')}><Icons.ScrollText size={16} aria-hidden="true" />查看更新日志</Button>
        <a
          href={PRODUCT_RELEASES_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="type-control inline-flex min-h-8 items-center gap-2 rounded-xl border border-separator bg-surface-secondary px-3 text-foreground hover:bg-default focus-visible:outline-2 focus-visible:outline-focus"
        ><Icons.Rocket size={16} aria-hidden="true" />Release 发布页<Icons.ExternalLink size={13} aria-hidden="true" /></a>
      </div>
    </AdminSection>

    <AdminSection id="settings-notifications" title="消息通知" description="选择当前账户的接收方式，并先发送一条安全的模拟通知进行验证。">
      <HeroNotificationSettings />
      {admin && <div className="mt-6 border-t border-separator pt-5">
        <HeroEmailTransportSettings />
      </div>}
    </AdminSection>

    <AdminSection id="settings-ai" title="助手与 AI" description="本地助手通过只读 Remote MCP 使用当前账户的数据。">
      <Button size="sm" variant="secondary" onPress={() => navigate('/agents')}><Icons.Bot size={16} />管理助手连接</Button>
      {!admin && <Card variant="transparent" className="mt-4 p-4"><Card.Title>工作区设置只读</Card.Title><Card.Description className="mt-1">全局 AI、获取规则、主题、成员和 Key 仅 Owner/Admin 可管理；个人订阅参数仍可在订阅页维护。</Card.Description></Card>}
      {admin && (config.isLoading || secrets.isLoading
        ? <LoadingState label="正在读取 AI 设置" rows={2} />
        : config.isError || secrets.isError
          ? <HeroNotice title="AI 设置读取失败" status="warning">
            <Button size="sm" variant="ghost" onPress={() => {
              void config.refetch()
              void secrets.refetch()
            }}>重试此区域</Button>
          </HeroNotice>
          : <form ref={aiFormRef} className="mt-5 grid gap-4" onChange={() => refreshCoreDirty('ai')} onSubmit={saveAi}>
        <Checkbox name="enabled" defaultSelected={ai.enabled !== false}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用 AI 分析</Checkbox.Content></Checkbox>
        <div className="grid gap-4 min-[720px]:grid-cols-3">
          <HeroSelect label="Provider" value={aiDraft.provider} onChange={(nextProvider) => {
            const defaults = aiDefaultsForProvider(nextProvider)
            const available = (secrets.data?.secrets ?? []).some((secret) => secret.kind === 'ai' && secret.env_name === defaults.apiKeyEnv)
            setAiOverride({ provider: nextProvider, model: defaults.model, apiKeyEnv: available ? defaults.apiKeyEnv : aiDraft.apiKeyEnv })
            refreshCoreDirty('ai')
          }} options={[{ id: 'gemini', label: 'Gemini' }, { id: 'openai', label: 'OpenAI' }, { id: 'anthropic', label: 'Anthropic' }, { id: 'deepseek', label: 'DeepSeek' }]} />
          <TextField fullWidth value={aiDraft.model} onChange={(model) => {
            setAiOverride({ ...aiDraft, model })
            refreshCoreDirty('ai')
          }} isRequired><Label>模型</Label><Input /></TextField>
          <HeroSelect label="AI Key" value={aiDraft.apiKeyEnv} onChange={(apiKeyEnv) => {
            setAiOverride({ ...aiDraft, apiKeyEnv })
            refreshCoreDirty('ai')
          }} options={[{ id: '', label: '请选择' }, ...(secrets.data?.secrets ?? []).filter((secret) => secret.kind === 'ai').map((secret) => ({ id: secret.env_name, label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}` }))]} />
          <FormField name="base_url" label="Base URL" type="url" defaultValue={String(ai.base_url ?? '')} />
          <FormField name="languages" label="输出语言" defaultValue={Array.isArray(ai.languages) ? ai.languages.join(',') : 'zh'} />
          <FormField name="analysis_content_chars" label="正文输入字符" type="number" min={100} max={10000} defaultValue={Number(ai.analysis_content_chars ?? 1000)} />
          <FormField name="analysis_comments_chars" label="评论输入字符" type="number" min={0} max={20000} defaultValue={Number(ai.analysis_comments_chars ?? 1500)} />
          <FormField name="summary_max_chars" label="概括最多字符" type="number" min={100} max={500} defaultValue={Number(ai.summary_max_chars ?? 200)} />
          <FormField name="analysis_max_output_tokens" label="最大输出 Token" type="number" min={256} max={2048} defaultValue={Number(ai.analysis_max_output_tokens ?? 800)} />
        </div>
        <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}><Icons.Save size={15} />{configMutation.isPending && configMutation.variables?.sections.includes('ai') ? '保存中…' : '保存 AI 设置'}</Button>
      </form>)}
      {admin && !config.isLoading && !config.isError && <div className="mt-6 border-t border-separator pt-5">
        <div>
          <h3 className="type-control">信息流触底文案</h3>
          <p className="type-meta mt-1 text-muted">内置中文文案始终可用；独立开关启用后，Worker 只会在普通任务队列空闲时生成三个共享场景。每句可选一个克制 Emoji 或颜文字。</p>
        </div>
        <form
          ref={feedEndMessagesFormRef}
          className="mt-4 grid gap-4"
          onChange={() => refreshCoreDirty('feed_end_messages')}
          onSubmit={saveFeedEndMessages}
        >
          <Checkbox
            name="ai_generation_enabled"
            defaultSelected={feedEndMessages.ai_generation_enabled === true}
          >
            <Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用 AI 定期生成触底文案</Checkbox.Content>
          </Checkbox>
          <div className="grid gap-4 min-[720px]:grid-cols-3">
            <HeroSelect
              name="refresh_days"
              label="更新周期"
              value={feedEndRefreshDays}
              onChange={(value) => {
                setFeedEndRefreshDaysOverride(value)
                refreshCoreDirty('feed_end_messages')
              }}
              options={[
                { id: '1', label: '每天' },
                { id: '7', label: '每 7 天（默认）' },
                { id: '30', label: '每 30 天' },
              ]}
            />
            <HeroSelect
              name="style_preset"
              label="文案风格"
              value={feedEndStyle}
              onChange={(value) => {
                setFeedEndStyleOverride(value)
                refreshCoreDirty('feed_end_messages')
              }}
              options={[
                { id: 'restrained', label: '克制（默认）' },
                { id: 'warm', label: '温和' },
                { id: 'light_humor', label: '轻幽默' },
              ]}
            />
            <FormField
              name="list_count"
              label="每场景条数"
              type="number"
              min={3}
              max={30}
              defaultValue={Number(feedEndMessages.list_count ?? 12)}
              required
            />
          </div>
          <TextField
            fullWidth
            name="style_prompt"
            defaultValue={String(feedEndMessages.style_prompt ?? '')}
          >
            <Label>自定义风格补充</Label>
            <Input maxLength={500} placeholder="可留空，最多 500 字；不能覆盖安全约束" />
          </TextField>
          <Button className="w-fit" type="submit" isDisabled={configMutation.isPending}>
            <Icons.Save size={15} aria-hidden="true" />
            {configMutation.isPending && configMutation.variables?.sections.includes('feed_end_messages')
              ? '保存中…'
              : '保存触底文案设置'}
          </Button>
        </form>

        <Card variant="transparent" className="mt-5 border border-separator p-4">
          {feedEndMessagesStatus.isLoading
            ? <LoadingState label="正在读取触底文案状态" rows={2} />
            : feedEndMessagesStatus.isError || !feedEndMessagesStatus.data
              ? <HeroNotice title="触底文案状态读取失败" status="warning">
                <Button size="sm" variant="ghost" onPress={() => void feedEndMessagesStatus.refetch()}>重试状态读取</Button>
              </HeroNotice>
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
                  <Button
                    size="sm"
                    variant="secondary"
                    isDisabled={
                      !savedFeedEndGenerationEnabled
                      || feedEndMessagesRefreshMutation.isPending
                      || feedEndMessagesStatus.data.status === 'pending'
                      || feedEndMessagesStatus.data.status === 'refreshing'
                    }
                    onPress={() => feedEndMessagesRefreshMutation.mutate()}
                  >
                    <Icons.RefreshCw
                      size={14}
                      className={feedEndMessagesRefreshMutation.isPending ? 'animate-spin motion-reduce:animate-none' : ''}
                      aria-hidden="true"
                    />
                    {feedEndMessagesStatus.data.status === 'pending'
                      ? '已等待刷新'
                      : feedEndMessagesStatus.data.status === 'refreshing'
                        ? '正在刷新'
                        : '立即刷新'}
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
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-controls={listId}
                            aria-expanded={expanded}
                            aria-label={`${expanded ? '隐藏' : '展开'}${label}完整文案列表`}
                            onPress={() => setExpandedFeedEndScenes((current) => {
                              const next = new Set(current)
                              if (next.has(scene)) next.delete(scene)
                              else next.add(scene)
                              return next
                            })}
                          >
                            {expanded ? '隐藏' : '展开'}
                          </Button>
                        </div>
                      </div>
                      <ol
                        id={listId}
                        aria-label={`${label}完整文案列表`}
                        className={`${expanded ? 'grid' : 'hidden'} mt-2 max-h-72 gap-1.5 overflow-y-auto rounded-lg pr-1 focus-visible:outline-2 focus-visible:outline-focus`}
                        hidden={!expanded}
                        tabIndex={0}
                      >
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
      </div>}
    </AdminSection>

    <AdminSection id="settings-ignored" title="已忽略内容" description="忽略后的信息只在这里恢复，不会继续占用日常浏览空间。">
      {ignored.isLoading && <LoadingState label="正在读取已忽略内容" rows={2} />}
      {ignored.isError && <HeroNotice title="已忽略内容读取失败" />}
      {!ignored.isLoading && !ignored.isError && !ignored.data?.items.length && <Card variant="transparent" className="p-4"><Card.Title>暂无已忽略内容</Card.Title></Card>}
      <div className="grid gap-2">{(ignored.data?.items ?? []).map((item) => <Card key={item.id} variant="transparent" className="flex-row items-center gap-3 p-3">
        <div className="min-w-0 flex-1"><Card.Title className="truncate">{item.presentation?.content?.title || item.title || '无标题内容'}</Card.Title><Card.Description className="truncate">{item.presentation?.source?.name || item.source || '未知来源'}</Card.Description></div>
        <Button size="sm" variant="ghost" isDisabled={restoreMutation.isPending && restoreMutation.variables === item.id} onPress={() => restoreMutation.mutate(item.id)}>{restoreMutation.isPending && restoreMutation.variables === item.id ? '恢复中…' : '恢复'}</Button>
      </Card>)}</div>
    </AdminSection>

    {admin && <>
      <AdminSection id="settings-fetching" title="获取与主题" description="控制抓取窗口和未来可选主题；兼容评分、精选与日报字段不在当前产品中显示。">
        {config.isLoading
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
      </AdminSection>

      <AdminSection id="settings-storage" title="存储与归档" description="预演工作区清理、90 日冷归档与恢复；所有操作均先核对候选指纹并记录审计。">
        <StorageArchiveSettings />
      </AdminSection>

      <AdminSection id="settings-secrets" title="密钥" description="真实 Key 只写入 SecretStore，保存后永不回显。">
        {secrets.isLoading
          ? <LoadingState label="正在读取密钥" rows={2} />
          : secrets.isError
            ? <HeroNotice title="密钥读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void secrets.refetch()}>重试此区域</Button></HeroNotice>
            : <>
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
        <div className="mt-5">
          <ApifyKeyPoolTable
            secrets={secrets.data?.secrets ?? []}
            userId={user.id}
            onSecretChanged={secretChanged}
          />
        </div>
        <div className="mt-5 min-w-0 max-w-full">
          <h3 className="type-page-title mb-3">AI Key</h3>
          <Table variant="secondary" className="max-w-full">
            <Table.ScrollContainer className="max-w-full overflow-x-auto" data-testid="secret-table-scroll">
              <Table.Content aria-label="已配置 AI Key">
                <Table.Header>
                  <Table.Column isRowHeader>Key</Table.Column>
                  <Table.Column>类型</Table.Column>
                  <Table.Column>状态</Table.Column>
                  <Table.Column>额度</Table.Column>
                  <Table.Column>操作</Table.Column>
                </Table.Header>
                <Table.Body
                  items={(secrets.data?.secrets ?? []).filter((secret) => !isApifySecret(secret))}
                  renderEmptyState={() => <div className="p-6 text-center text-muted">尚未配置 AI Key</div>}
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
                      <Table.Cell><span className="type-meta">{isApifySecret(secret) ? 'Apify' : 'AI'} · {presentation.provider}</span></Table.Cell>
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
        </>}
      </AdminSection>

    </>}
    </div>
  </PageFrame></div>
}
