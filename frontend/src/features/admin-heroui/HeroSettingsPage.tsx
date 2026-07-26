import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { ApifyKeyPoolMember, SecretRef } from '../../api/types'
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

export function HeroSettingsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const admin = canAdministerWorkspace(user)
  const config = useQuery({ queryKey: queryKeys.config(user.id), queryFn: ({ signal }) => api.config(signal) })
  const ignored = useQuery({ queryKey: queryKeys.ignored(user.id), queryFn: ({ signal }) => api.ignoredFeed(200, 0, signal) })
  const secrets = useQuery({ queryKey: queryKeys.secrets(user.id), queryFn: ({ signal }) => api.secrets(signal), enabled: admin })
  const [aiOverride, setAiOverride] = useState<{ provider: string; model: string; apiKeyEnv: string } | null>(null)
  const [secretDraft, setSecretDraft] = useState<SecretDraft>({ name: '', kind: 'ai', provider: '', envName: '', value: '' })
  const [secretFieldErrors, setSecretFieldErrors] = useState<SecretFieldErrors>({})
  const [secretFormError, setSecretFormError] = useState('')
  const [rssInitialFetchWindowOverride, setRssInitialFetchWindowOverride] = useState<string | null>(null)
  const [activeSection, setActiveSection] = useState<string>(
    () => settingsSectionFromHash(location.hash, user.role)?.id ?? 'settings-about',
  )
  const [settingsDirty, setSettingsDirty] = useState(false)
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
  const rssInitialFetchWindow = rssInitialFetchWindowOverride
    ?? String(filtering.rss_initial_fetch_window_hours ?? 168)
  const rsshub = recordOf(config.data?.config.rsshub)
  const rsshubAccessKeySet = (config.data?.env_status ?? []).some(
    (item) => item.name === 'RSSHUB_ACCESS_KEY' && item.set === true,
  )
  const sectionOptions = useMemo(() => settingsSectionsForRole(user.role), [user.role])

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
    mutationFn: ({ action, payload }: { action: string; payload: Record<string, unknown> }) => api.configAction(action, payload),
    onMutate: ({ action }) => feedback.begin('config-save', action),
    onSuccess: (_result, { action }) => {
      feedback.clear('config-save', action)
      setSettingsDirty(false)
      actionToast.success('设置已保存')
      void queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) })
    },
    onError: (caught, { action }) => {
      const message = errorMessage(caught, '设置保存失败。')
      feedback.clear('config-save', action)
      actionToast.danger('设置保存失败', { description: message })
    },
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
      setSecretDraft({ name: '', kind: 'ai', provider: '', envName: '', value: '' })
      setSecretFieldErrors({})
      setSecretFormError('')
      setSettingsDirty(false)
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
      rss_initial_fetch_window_hours: Number(data.get('rss_initial_fetch_window_hours')),
      recent_item_limit: Number(data.get('recent_item_limit')),
    } })
  }

  function saveRsshub(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const data = new FormData(event.currentTarget)
    configMutation.mutate({
      action: 'set_rsshub',
      payload: { base_url: inputValue(data, 'base_url') },
    })
  }

  return <div className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto"><PageFrame width="admin" className="grid gap-5 p-4 min-[768px]:p-6">
    <AdminPageHeader description={`当前账户：${user.display_name || user.username} · ${user.role}`} />
    {settingsDirty && <div
      data-settings-dirty-notice
      className="fixed inset-x-4 bottom-[calc(5rem+env(safe-area-inset-bottom))] z-40 ml-auto max-w-sm min-[768px]:bottom-4 min-[768px]:left-auto min-[768px]:right-4"
    >
      <HeroNotice title="有尚未保存的更改" status="warning" role="status">离开或刷新页面前，请先保存当前设置。</HeroNotice>
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
          : <form className="mt-5 grid gap-4" onChange={() => setSettingsDirty(true)} onSubmit={saveAi}>
        <Checkbox name="enabled" defaultSelected={ai.enabled !== false}><Checkbox.Content><Checkbox.Control><Checkbox.Indicator /></Checkbox.Control>启用 AI 分析</Checkbox.Content></Checkbox>
        <div className="grid gap-4 min-[720px]:grid-cols-3">
          <HeroSelect label="Provider" value={aiDraft.provider} onChange={(nextProvider) => {
            const defaults = aiDefaultsForProvider(nextProvider)
            const available = (secrets.data?.secrets ?? []).some((secret) => secret.kind === 'ai' && secret.env_name === defaults.apiKeyEnv)
            setAiOverride({ provider: nextProvider, model: defaults.model, apiKeyEnv: available ? defaults.apiKeyEnv : aiDraft.apiKeyEnv })
            setSettingsDirty(true)
          }} options={[{ id: 'gemini', label: 'Gemini' }, { id: 'openai', label: 'OpenAI' }, { id: 'anthropic', label: 'Anthropic' }, { id: 'deepseek', label: 'DeepSeek' }]} />
          <TextField fullWidth value={aiDraft.model} onChange={(model) => {
            setAiOverride({ ...aiDraft, model })
            setSettingsDirty(true)
          }} isRequired><Label>模型</Label><Input /></TextField>
          <HeroSelect label="AI Key" value={aiDraft.apiKeyEnv} onChange={(apiKeyEnv) => {
            setAiOverride({ ...aiDraft, apiKeyEnv })
            setSettingsDirty(true)
          }} options={[{ id: '', label: '请选择' }, ...(secrets.data?.secrets ?? []).filter((secret) => secret.kind === 'ai').map((secret) => ({ id: secret.env_name, label: `${secret.name} · ${secret.is_set ? '已设置' : '未设置'}` }))]} />
          <FormField name="base_url" label="Base URL" type="url" defaultValue={String(ai.base_url ?? '')} />
          <FormField name="languages" label="输出语言" defaultValue={Array.isArray(ai.languages) ? ai.languages.join(',') : 'zh'} />
          <FormField name="analysis_content_chars" label="正文输入字符" type="number" min={100} max={10000} defaultValue={Number(ai.analysis_content_chars ?? 1000)} />
          <FormField name="analysis_comments_chars" label="评论输入字符" type="number" min={0} max={20000} defaultValue={Number(ai.analysis_comments_chars ?? 1500)} />
          <FormField name="summary_max_chars" label="概括最多字符" type="number" min={100} max={500} defaultValue={Number(ai.summary_max_chars ?? 200)} />
          <FormField name="analysis_max_output_tokens" label="最大输出 Token" type="number" min={256} max={2048} defaultValue={Number(ai.analysis_max_output_tokens ?? 800)} />
        </div>
        <Button className="w-fit" type="submit" isDisabled={feedback.isPending('config-save', 'set_ai')}><Icons.Save size={15} />{feedback.isPending('config-save', 'set_ai') ? '保存中…' : '保存 AI 设置'}</Button>
      </form>)}
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
          <form className="grid gap-4 min-[720px]:grid-cols-[minmax(0,1fr)_auto] min-[720px]:items-end" onChange={() => setSettingsDirty(true)} onSubmit={saveRsshub}>
            <FormField name="base_url" label="RSSHub Base URL" type="url" defaultValue={String(rsshub.base_url ?? 'http://rsshub:1200')} />
            <Button className="w-fit" type="submit" isDisabled={feedback.isPending('config-save', 'set_rsshub')}>{feedback.isPending('config-save', 'set_rsshub') ? '保存中…' : '保存 RSSHub 地址'}</Button>
          </form>
        </div>
        <form className="grid gap-4" onChange={() => setSettingsDirty(true)} onSubmit={saveFiltering}>
          <div className="grid gap-4 min-[720px]:grid-cols-3">
            <FormField name="time_window_hours" label="日常抓取窗口（小时）" type="number" min={1} max={720} defaultValue={Number(filtering.time_window_hours ?? 24)} />
            <HeroSelect
              name="rss_initial_fetch_window_hours"
              label="RSS 首次抓取窗口"
              value={rssInitialFetchWindow}
              onChange={(value) => {
                setRssInitialFetchWindowOverride(value)
                setSettingsDirty(true)
              }}
              description="RSS 或 RSSHub 订阅在首次成功前使用该窗口；成功后恢复日常窗口。"
              options={[
                { id: '168', label: '7 天' },
                { id: '720', label: '30 天' },
              ]}
            />
            <FormField name="recent_item_limit" label="历史预览条数" type="number" min={1} max={200} defaultValue={Number(filtering.recent_item_limit ?? 20)} />
          </div>
          <Button className="w-fit" type="submit" isDisabled={feedback.isPending('config-save', 'set_filtering')}>{feedback.isPending('config-save', 'set_filtering') ? '保存中…' : '保存获取设置'}</Button>
        </form>
        <div className="mt-6 border-t border-separator pt-5"><h3 className="type-control mb-4">阅读主题库</h3><HeroTopicLibrary key={JSON.stringify(config.data?.taxonomy?.topics ?? config.data?.config.tags ?? [])} topics={(config.data?.taxonomy?.topics ?? (Array.isArray(config.data?.config.tags) ? config.data.config.tags : [])).filter((topic): topic is string => typeof topic === 'string')} pending={feedback.isPending('config-save', 'set_tags')} onSave={(topics) => configMutation.mutate({ action: 'set_tags', payload: { topics } })} /></div>
        </>}
      </AdminSection>

      <AdminSection id="settings-secrets" title="密钥" description="真实 Key 只写入 SecretStore，保存后永不回显。">
        {secrets.isLoading
          ? <LoadingState label="正在读取密钥" rows={2} />
          : secrets.isError
            ? <HeroNotice title="密钥读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void secrets.refetch()}>重试此区域</Button></HeroNotice>
            : <>
        <form className="grid gap-3 min-[760px]:grid-cols-5" noValidate onChange={() => setSettingsDirty(true)} onSubmit={createSecret}>
          <TextField fullWidth value={secretDraft.name} onChange={(name) => {
            setSecretDraft((current) => ({ ...current, name }))
            clearSecretFieldError('name')
          }} isRequired isInvalid={Boolean(secretFieldErrors.name)}>
            <Label>Key 名称</Label><Input />{secretFieldErrors.name && <FieldError>{secretFieldErrors.name}</FieldError>}
          </TextField>
          <div>
            <HeroSelect label="Key 类型" value={secretDraft.kind} onChange={(kind) => {
              setSecretDraft((current) => ({ ...current, kind }))
              setSettingsDirty(true)
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
