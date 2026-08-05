import { useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { ApifyKeyPoolMember, SecretRef } from '../../api/types'
import { useActionFeedback } from '../../app/ActionFeedback'
import { useAppContext } from '../../app/AppContext'
import { SettingsDisclosure, SettingsGroup, SettingsItem, SettingsSection, StatusBadge } from '../../components/settings'
import {
  actionToast,
  Button,
  FieldError,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  StatusNotice,
  TextField,
} from '../../design-system'
import { HeroSelect } from '../admin-heroui/HeroAdminControls'
import { canAdministerWorkspace, secretPresentation } from './settingsModel'
import {
  apifyPoolActionError,
  emptySecretDraft,
  formatCycleEnd,
  formatDateTime,
  formatUsd,
  isApifySecret,
  memberErrorLabels,
  memberStatusPresentation,
  poolStatusLabels,
  secretActionError,
  secretCreateErrorMessage,
  secretQuotaStaleTime,
  validateSecretDraft,
  type SecretDraft,
  type SecretField,
  type SecretFieldErrors,
} from './settingsSecretsModel'

function SecretQuotaDetails({ secret, userId }: { secret: SecretRef; userId: string }) {
  const { api } = useAppContext()
  const [manualAction, setManualAction] = useState<'refresh' | 'retry' | null>(null)
  const [retryError, setRetryError] = useState<unknown>(null)
  const supported = isApifySecret(secret)
  const quota = useQuery({
    queryKey: queryKeys.secretQuota(userId, secret.id),
    queryFn: () => api.secretQuota(secret.id),
    enabled: supported && secret.is_set,
    staleTime: secretQuotaStaleTime,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  async function refetch(action: 'refresh' | 'retry') {
    if (action === 'retry') setRetryError(quota.error)
    setManualAction(action)
    try {
      await quota.refetch()
    } finally {
      setManualAction(null)
    }
  }

  if (!supported) return <span className="type-meta text-muted">暂不支持查询额度</span>
  if (!secret.is_set) return <span className="type-meta text-muted">Key 未配置，无法查询额度</span>
  if (quota.isPending) return <span className="type-meta text-muted" aria-live="polite">正在查询额度…</span>

  const retrying = manualAction === 'retry'
  const refreshing = manualAction === 'refresh' || (quota.isFetching && !retrying)
  const retryBusy = retrying || quota.isFetching
  const failure = quota.isError || retrying
    ? secretActionError(quota.isError ? quota.error : retryError, '额度查询失败，请稍后重试。')
    : null

  if (!quota.data) return <div className="flex flex-wrap items-center gap-2" role="alert" aria-busy={retryBusy}>
    <span className="type-meta text-danger">{failure ?? '暂无额度数据'}</span>
    <Button size="sm" variant="ghost" aria-label={retryBusy ? `正在重试 ${secret.name} 额度` : `重试 ${secret.name} 额度`} isDisabled={retryBusy} onPress={() => void refetch('retry')}>
      <Icons.RefreshCw size={14} className={retryBusy ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />
      {retryBusy ? '重试中…' : '重试'}
    </Button>
  </div>

  return <div className="grid gap-1" aria-live="polite" aria-busy={refreshing || retryBusy}>
    <span className="type-control">套餐剩余 {formatUsd(quota.data.remaining_included_credits_usd)}</span>
    <span className="type-meta text-muted">本月已用 {formatUsd(quota.data.monthly_usage_usd)} · 硬上限剩余 {formatUsd(quota.data.remaining_hard_limit_usd)}</span>
    <div className="flex flex-wrap items-center gap-2">
      <span className="type-meta text-muted">周期至 {formatCycleEnd(quota.data.cycle_end_at)}</span>
      <Button
        size="sm"
        variant="ghost"
        isIconOnly
        aria-label={refreshing ? `正在刷新 ${secret.name} 额度` : failure ? `重试 ${secret.name} 额度` : `刷新 ${secret.name} 额度`}
        isDisabled={refreshing || retryBusy}
        onPress={() => void refetch(failure ? 'retry' : 'refresh')}
      ><Icons.RefreshCw size={14} className={refreshing || retryBusy ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" /></Button>
    </div>
    {failure && <span className="type-meta text-danger" role="alert">{failure}</span>}
  </div>
}

function SecretActions({ secret, lifecycleLocked = false, lockMessage = '请先安全排空，再轮换或删除', onChanged }: {
  secret: SecretRef
  lifecycleLocked?: boolean
  lockMessage?: string
  onChanged: (secretId: string, action: 'rotate' | 'delete' | 'connection') => void
}) {
  const { api } = useAppContext()
  const feedback = useActionFeedback()
  const [rotateOpen, setRotateOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [value, setValue] = useState('')
  const [rotateError, setRotateError] = useState('')
  const [deleteError, setDeleteError] = useState('')
  const rotateTriggerRef = useRef<HTMLButtonElement>(null)
  const deleteTriggerRef = useRef<HTMLButtonElement>(null)
  const rotating = feedback.isPending('secret-rotate', secret.id)
  const removing = feedback.isPending('secret-delete', secret.id)

  function closeRotate() {
    setRotateOpen(false)
    setRotateError('')
    setValue('')
    queueMicrotask(() => rotateTriggerRef.current?.focus())
  }

  function closeDelete() {
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
      closeRotate()
      actionToast.success('Key 已轮换', { description: secret.name })
      onChanged(secret.id, 'rotate')
    } catch (caught) {
      const message = secretActionError(caught, '轮换失败，请稍后重试。')
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
      closeDelete()
      actionToast.success('Key 已删除', { description: secret.name })
      onChanged(secret.id, 'delete')
    } catch (caught) {
      const message = secretActionError(caught, '删除失败。')
      setDeleteError(message)
      feedback.fail('secret-delete', secret.id, message)
    }
  }

  return <div className="grid gap-2">
    <div className="flex flex-wrap gap-2">
      <Modal isOpen={rotateOpen} onOpenChange={(open) => {
        if (rotating) return
        if (open) setRotateOpen(true)
        else closeRotate()
      }}>
        <Button ref={rotateTriggerRef} size="sm" variant="ghost" isDisabled={lifecycleLocked} aria-label={`轮换 ${secret.name}`}>轮换</Button>
        <Modal.Backdrop isDismissable={!rotating} isKeyboardDismissDisabled={rotating}>
          <Modal.Container><Modal.Dialog>
            <Modal.Header><Modal.Heading>{`轮换 ${secret.name}`}</Modal.Heading></Modal.Header>
            <Modal.Body><form id={`rotate-secret-${secret.id}`} className="grid gap-3" onSubmit={rotate}>
              <TextField fullWidth value={value} onChange={setValue} isRequired><Label>新 Key 值</Label><Input type="password" autoComplete="new-password" placeholder="粘贴新 Key（不会回显）" /></TextField>
              {rotateError && <StatusNotice title={rotateError} status="warning" />}
            </form></Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={rotating} onPress={closeRotate}>取消轮换</Button>
              <Button type="submit" form={`rotate-secret-${secret.id}`} isDisabled={rotating}>{rotating ? '轮换中…' : '确认轮换'}</Button>
            </Modal.Footer>
          </Modal.Dialog></Modal.Container>
        </Modal.Backdrop>
      </Modal>
      <Modal isOpen={deleteOpen} onOpenChange={(open) => {
        if (removing) return
        if (open) setDeleteOpen(true)
        else closeDelete()
      }}>
        <Button ref={deleteTriggerRef} size="sm" variant="danger" isDisabled={lifecycleLocked || secret.used_by.length > 0 || removing} aria-label={`删除 ${secret.name}`}>删除</Button>
        <Modal.Backdrop isDismissable={!removing} isKeyboardDismissDisabled={removing}>
          <Modal.Container><Modal.Dialog>
            <Modal.Header><Modal.Heading>{`删除 ${secret.name}？`}</Modal.Heading></Modal.Header>
            <Modal.Body><p>删除后无法恢复；如需再次使用，必须重新添加 Key。</p>{deleteError && <div className="mt-3"><StatusNotice title={deleteError} status="warning" /></div>}</Modal.Body>
            <Modal.Footer>
              <Button type="button" variant="ghost" isDisabled={removing} onPress={closeDelete}>取消删除</Button>
              <Button type="button" variant="danger" isDisabled={removing} onPress={() => void remove()}>{removing ? '删除中…' : '确认删除'}</Button>
            </Modal.Footer>
          </Modal.Dialog></Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </div>
    {lifecycleLocked && <span className="type-meta text-muted">{lockMessage}</span>}
  </div>
}

function SecretConnectionEditor({ secret, onChanged }: {
  secret: SecretRef
  onChanged: (secretId: string, action: 'rotate' | 'delete' | 'connection') => void
}) {
  const { api } = useAppContext()
  const feedback = useActionFeedback()
  const [open, setOpen] = useState(false)
  const [baseUrl, setBaseUrl] = useState(secret.base_url ?? '')
  const [error, setError] = useState('')
  const triggerRef = useRef<HTMLButtonElement>(null)
  const saving = feedback.isPending('secret-connection', secret.id)

  function close() {
    if (saving) return
    setOpen(false)
    setBaseUrl(secret.base_url ?? '')
    setError('')
    queueMicrotask(() => triggerRef.current?.focus())
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    feedback.begin('secret-connection', secret.id)
    try {
      await api.updateSecretConnection(secret.id, baseUrl.trim())
      feedback.succeed('secret-connection', secret.id, `${secret.name} 的连接地址已保存。`)
      setOpen(false)
      actionToast.success('连接地址已保存', { description: secret.name })
      onChanged(secret.id, 'connection')
    } catch (caught) {
      const message = secretActionError(caught, '连接地址保存失败，请稍后重试。')
      setError(message)
      feedback.fail('secret-connection', secret.id, message)
    }
  }

  return <Modal isOpen={open} onOpenChange={(next) => next ? setOpen(true) : close()}>
    <Button ref={triggerRef} size="sm" variant="ghost" aria-label={`编辑 ${secret.name} 的连接地址`}>连接地址</Button>
    <Modal.Backdrop isDismissable={!saving} isKeyboardDismissDisabled={saving}>
      <Modal.Container><Modal.Dialog>
        <Modal.Header><Modal.Heading>{`编辑 ${secret.name} 的连接地址`}</Modal.Heading></Modal.Header>
        <Modal.Body><form id={`secret-connection-${secret.id}`} className="grid gap-3" onSubmit={save}>
          <TextField fullWidth value={baseUrl} onChange={setBaseUrl}>
            <Label>Base URL</Label>
            <Input type="url" placeholder="留空则沿用全局 AI Base URL" />
          </TextField>
          <p className="type-meta text-muted">仅保存此 Key 的连接地址；不保存真实 Key，也不会显示凭据。</p>
          {error && <StatusNotice title={error} status="warning" />}
        </form></Modal.Body>
        <Modal.Footer>
          <Button type="button" variant="ghost" isDisabled={saving} onPress={close}>取消</Button>
          <Button type="submit" form={`secret-connection-${secret.id}`} isDisabled={saving}>{saving ? '保存中…' : '保存连接地址'}</Button>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}

function ApifyMemberState({ member }: { member: ApifyKeyPoolMember | null }) {
  if (!member) return <div className="grid gap-1"><StatusBadge>等待加入池</StatusBadge><span className="type-meta text-muted">刷新后仍未加入时，请检查服务状态。</span></div>
  const presentation = memberStatusPresentation[member.status]
  return <div className="grid gap-1">
    <StatusBadge tone={presentation.tone}>{presentation.label}</StatusBadge>
    <span className="type-meta text-muted">{member.active_run_count > 0 ? `${member.active_run_count} 个运行中任务` : '没有运行中任务'} · 最近检查 {formatDateTime(member.last_checked_at)}</span>
    {member.blocked_until && <span className="type-meta text-muted">受阻至 {formatDateTime(member.blocked_until)}</span>}
    {member.cycle_end_at && <span className="type-meta text-muted">额度周期至 {formatDateTime(member.cycle_end_at)}</span>}
    {member.last_error_code && <span className="type-meta text-danger">{memberErrorLabels[member.last_error_code] ?? 'Key 需要管理员检查'}</span>}
  </div>
}

function ApifyKeyPoolGroup({ secrets, userId, onSecretChanged }: { secrets: SecretRef[]; userId: string; onSecretChanged: (secretId: string, action: 'rotate' | 'delete' | 'connection') => void }) {
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
    mutationFn: ({ secretIds, expectedGeneration }: { secretIds: string[]; expectedGeneration: number }) => api.reorderApifyKeyPool(secretIds, expectedGeneration),
    onSuccess: (pool) => {
      queryClient.setQueryData(queryKeys.apifyKeyPool(userId), pool)
      actionToast.success('Apify Key 顺序已更新')
    },
    onError: (caught, variables) => {
      const message = apifyPoolActionError(caught, 'Key 顺序更新失败，请稍后重试。')
      if (caught instanceof ApiError && ['apify_key_pool_generation_conflict', 'apify_key_pool_conflict'].includes(caught.code)) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(userId) })
      }
      actionToast.danger('Key 顺序更新失败', { description: message, onRetry: () => !orderMutation.isPending && orderMutation.mutate(variables) })
    },
  })
  const drainMutation = useMutation({
    mutationFn: (secretId: string) => api.drainApifyKey(secretId),
    onSuccess: (pool, secretId) => {
      queryClient.setQueryData(queryKeys.apifyKeyPool(userId), pool)
      actionToast.success('已提交安全排空', { description: secrets.find((secret) => secret.id === secretId)?.name })
    },
    onError: (caught, secretId) => {
      const message = apifyPoolActionError(caught, '安全排空失败，请稍后重试。')
      actionToast.danger('安全排空失败', { description: message, onRetry: () => !drainMutation.isPending && drainMutation.mutate(secretId) })
    },
  })
  const apifySecrets = secrets.filter(isApifySecret)
  const secretsById = new Map(apifySecrets.map((secret) => [secret.id, secret]))
  const orderedMembers = [...(poolQuery.data?.members ?? [])].sort((left, right) => left.position - right.position)
  const memberIds = new Set(orderedMembers.map((member) => member.secret_id))
  const rows = [
    ...orderedMembers.flatMap((member) => {
      const secret = secretsById.get(member.secret_id)
      return secret ? [{ secret, member }] : []
    }),
    ...apifySecrets.filter((secret) => !memberIds.has(secret.id)).map((secret) => ({ secret, member: null })),
  ]
  const pool = poolQuery.data
  const poolBusy = pool?.enabled === true && ['draining', 'blocked'].includes(pool.status)
  const unresolvedMembers = orderedMembers.some((member) => !secretsById.has(member.secret_id))

  function memberLocked(member: ApifyKeyPoolMember | null) {
    return Boolean(pool?.enabled && member && (member.status === 'active' || member.status === 'draining' || member.active_run_count > 0 || pool.active_secret_id === member.secret_id))
  }

  function moveMember(secretId: string, offset: -1 | 1) {
    if (!pool || orderMutation.isPending || drainMutation.isPending || poolBusy) return
    const members = [...pool.members].sort((left, right) => left.position - right.position)
    const index = members.findIndex((member) => member.secret_id === secretId)
    const target = index + offset
    if (index < 0 || target < 0 || target >= members.length || memberLocked(members[index]) || memberLocked(members[target])) return
    const next = [...members]
    const [moving] = next.splice(index, 1)
    next.splice(target, 0, moving)
    orderMutation.mutate({ secretIds: next.map((member) => member.secret_id), expectedGeneration: pool.generation })
  }

  const status = pool ? poolStatusLabels[pool.status] ?? '状态需要检查' : '正在读取'
  const statusTone = pool?.status === 'ready' ? 'success' : ['blocked', 'exhausted'].includes(pool?.status ?? '') ? 'danger' : pool?.status === 'draining' ? 'warning' : 'neutral'
  return <SettingsSection title="Apify Key 池" description="所有 Apify 来源统一使用此池；额度不足时先停止旧 Key 的任务，再切换到下一备用 Key。">
    {poolQuery.isPending
      ? <LoadingState label="正在读取 Apify Key 池" rows={2} />
      : poolQuery.isError
        ? <StatusNotice title="Apify Key 池读取失败" status="warning">为避免误操作，池状态恢复前不会提供排序或排空操作。</StatusNotice>
        : <>
          <div className="mb-3 flex flex-wrap items-center gap-2"><StatusBadge tone={statusTone}>{status}</StatusBadge>{pool?.enabled && <span className="type-meta text-muted">当前主用：{pool.active_secret_id ? secretsById.get(pool.active_secret_id)?.name ?? '需要检查' : '无可用 Key'}</span>}</div>
          {pool && !pool.enabled && <StatusNotice title="Apify Key 池尚未启用" status="warning">当前仍处于兼容阶段；可以预先维护备用顺序，但不会自动切换。</StatusNotice>}
          {unresolvedMembers && <div className="mt-3"><StatusNotice title="部分 Key 元数据尚未加载" status="warning">已隐藏无法安全识别的池成员，请刷新页面后再操作。</StatusNotice></div>}
          <SettingsGroup ariaLabel="Apify Key 池" className="mt-3">
            {!rows.length
              ? <SettingsItem label="尚未配置 Apify Key" description="新增 Apify Key 后可在这里查看额度并维护主备顺序。" icon={<Icons.KeyRound size={17} aria-hidden="true" />} />
              : rows.map(({ secret, member }) => {
                const index = member ? orderedMembers.findIndex((item) => item.secret_id === member.secret_id) : -1
                const previous = index > 0 ? orderedMembers[index - 1] : null
                const next = index >= 0 && index < orderedMembers.length - 1 ? orderedMembers[index + 1] : null
                const poolStateUnknown = pool?.enabled && !member
                const lifecycleLocked = Boolean(poolStateUnknown || memberLocked(member))
                const controlsDisabled = !member || Boolean(poolQuery.isError) || orderMutation.isPending || drainMutation.isPending || poolBusy
                const canDrain = Boolean(pool?.enabled && member && lifecycleLocked)
                const draining = drainMutation.isPending && drainMutation.variables === secret.id
                const memberPresentation = member ? memberStatusPresentation[member.status] : null
                return <SettingsItem
                  key={secret.id}
                  density="compact"
                  label={secret.name}
                  description={`${secret.provider} · ${secret.env_name}`}
                  icon={<Icons.KeyRound size={17} aria-hidden="true" />}
                  trailing={<div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="ghost" isIconOnly aria-label={`上移 ${secret.name}`} isDisabled={controlsDisabled || index <= 0 || lifecycleLocked || memberLocked(previous)} onPress={() => moveMember(secret.id, -1)}><Icons.ArrowUp size={14} aria-hidden="true" /></Button>
                    <Button size="sm" variant="ghost" isIconOnly aria-label={`下移 ${secret.name}`} isDisabled={controlsDisabled || index < 0 || index >= orderedMembers.length - 1 || lifecycleLocked || memberLocked(next)} onPress={() => moveMember(secret.id, 1)}><Icons.ArrowDown size={14} aria-hidden="true" /></Button>
                    {canDrain && <Button size="sm" variant="secondary" aria-label={`安全排空 ${secret.name}`} isDisabled={draining || member?.status === 'draining' || pool?.status === 'blocked'} onPress={() => drainMutation.mutate(secret.id)}><Icons.CircleStop size={14} aria-hidden="true" />{draining || member?.status === 'draining' ? '排空中…' : '安全排空'}</Button>}
                  </div>}
                >
                  <div className="grid gap-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <StatusBadge tone={memberPresentation?.tone ?? 'neutral'}>{memberPresentation?.label ?? '等待加入池'}</StatusBadge>
                      {member && <span className="type-meta text-muted">顺位 {member.position} · {member.active_run_count > 0 ? `${member.active_run_count} 个运行中任务` : '当前无运行中任务'}</span>}
                    </div>
                    <SecretQuotaDetails secret={secret} userId={userId} />
                    <SettingsDisclosure title="运行详情" description="查看检查时间、周期、错误和安全锁定状态。">
                      <div className="grid gap-3"><ApifyMemberState member={member} /><SecretActions secret={secret} lifecycleLocked={lifecycleLocked} lockMessage={poolStateUnknown ? '池状态确认前不可轮换或删除' : undefined} onChanged={onSecretChanged} /></div>
                    </SettingsDisclosure>
                  </div>
                </SettingsItem>
              })}
          </SettingsGroup>
        </>}
  </SettingsSection>
}

export function SettingsSecretsPage() {
  const { api, user } = useAppContext()
  const feedback = useActionFeedback()
  const queryClient = useQueryClient()
  const admin = canAdministerWorkspace(user)
  const [createOpen, setCreateOpen] = useState(false)
  const [draft, setDraft] = useState<SecretDraft>(emptySecretDraft)
  const [fieldErrors, setFieldErrors] = useState<SecretFieldErrors>({})
  const [formError, setFormError] = useState('')
  const secrets = useQuery({
    queryKey: queryKeys.secrets(user.id),
    queryFn: ({ signal }) => api.secrets(signal),
    enabled: admin,
  })

  function clearFieldError(field: SecretField) {
    setFieldErrors((current) => {
      if (!current[field]) return current
      const next = { ...current }
      delete next[field]
      return next
    })
    setFormError('')
  }

  function closeCreate() {
    if (feedback.isPending('secret-create', 'new')) return
    setCreateOpen(false)
    setFormError('')
    setFieldErrors({})
    setDraft(emptySecretDraft)
  }

  async function createSecret(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const submitted = { name: draft.name.trim(), kind: draft.kind, provider: draft.provider.trim(), env_name: draft.envName.trim(), base_url: draft.baseUrl.trim(), value: draft.value }
    setDraft((current) => ({ ...current, value: '' }))
    setFieldErrors({})
    setFormError('')
    const validation = validateSecretDraft(draft)
    if (Object.keys(validation).length) {
      const message = Object.values(validation)[0] ?? '请检查 Key 表单。'
      setFieldErrors(validation)
      setFormError('请修正标出的字段后重试。')
      feedback.fail('secret-create', 'new', message)
      actionToast.danger('新增 Key 失败', { description: message })
      return
    }
    feedback.begin('secret-create', 'new')
    try {
      await api.createSecret(submitted)
      setDraft(emptySecretDraft)
      setFieldErrors({})
      setFormError('')
      feedback.clear('secret-create', 'new')
      setCreateOpen(false)
      actionToast.success('Key 已安全保存')
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorDiscoverySettings(user.id) }),
        ...(submitted.kind === 'apify' ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(user.id) })] : []),
      ])
    } catch (caught) {
      const message = secretCreateErrorMessage(caught)
      setFormError(message)
      feedback.fail('secret-create', 'new', message)
      actionToast.danger('新增 Key 失败', { description: message })
    }
  }

  function secretChanged(secretId: string, action: 'rotate' | 'delete' | 'connection') {
    const apifySecret = (secrets.data?.secrets ?? []).some((secret) => secret.id === secretId && isApifySecret(secret))
    if (action !== 'delete') {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
        ...(action === 'connection' ? [queryClient.invalidateQueries({ queryKey: queryKeys.config(user.id) })] : []),
        queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorDiscoverySettings(user.id) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.secretQuota(user.id, secretId) }),
        ...(apifySecret ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(user.id) })] : []),
      ])
      return
    }
    queryClient.removeQueries({ queryKey: queryKeys.secretQuota(user.id, secretId) })
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.secrets(user.id) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.apifyActorDiscoverySettings(user.id) }),
      ...(apifySecret ? [queryClient.invalidateQueries({ queryKey: queryKeys.apifyKeyPool(user.id) })] : []),
    ])
  }

  if (!admin) return <Navigate to="/settings" replace />
  const aiSecrets = (secrets.data?.secrets ?? []).filter((secret) => !isApifySecret(secret))
  const creating = feedback.isPending('secret-create', 'new')

  return <div data-settings-page="secrets" className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="密钥" description="真实 Key 仅写入 SecretStore，保存、轮换和使用时都不会回显真实值。">
        <SettingsGroup ariaLabel="密钥管理">
          <SettingsItem label="新增密钥" description="登记 AI 或 Apify Key 的元数据和值；真实值仅在此提交一次。" icon={<Icons.KeyRound size={17} aria-hidden="true" />} trailing={<Button size="sm" onPress={() => setCreateOpen(true)}><Icons.Plus size={15} aria-hidden="true" />新增 Key</Button>} />
        </SettingsGroup>
        <Modal isOpen={createOpen} onOpenChange={(open) => open ? setCreateOpen(true) : closeCreate()}>
          <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">新增 Key</Modal.Trigger>
          <Modal.Backdrop isDismissable={!creating} isKeyboardDismissDisabled={creating}>
            <Modal.Container><Modal.Dialog>
              <Modal.Header><Modal.Heading>新增 Key</Modal.Heading></Modal.Header>
              <Modal.Body><form id="create-secret" className="grid gap-3" noValidate onSubmit={createSecret}>
                <TextField fullWidth value={draft.name} onChange={(name) => { setDraft((current) => ({ ...current, name })); clearFieldError('name') }} isRequired isInvalid={Boolean(fieldErrors.name)}><Label>Key 名称</Label><Input />{fieldErrors.name && <FieldError>{fieldErrors.name}</FieldError>}</TextField>
                <HeroSelect label="Key 类型" value={draft.kind} onChange={(kind) => { setDraft((current) => ({ ...current, kind, baseUrl: kind === 'ai' ? current.baseUrl : '' })); clearFieldError('kind'); clearFieldError('provider'); clearFieldError('baseUrl') }} options={[{ id: 'ai', label: 'AI' }, { id: 'apify', label: 'Apify' }]} />
                {fieldErrors.kind && <FieldError>{fieldErrors.kind}</FieldError>}
                <TextField fullWidth value={draft.provider} onChange={(provider) => { setDraft((current) => ({ ...current, provider })); clearFieldError('provider') }} isRequired isInvalid={Boolean(fieldErrors.provider)}><Label>Key provider</Label><Input />{fieldErrors.provider && <FieldError>{fieldErrors.provider}</FieldError>}</TextField>
                <TextField fullWidth value={draft.envName} onChange={(envName) => { setDraft((current) => ({ ...current, envName })); clearFieldError('envName') }} isRequired isInvalid={Boolean(fieldErrors.envName)}><Label>环境变量名</Label><Input />{fieldErrors.envName && <FieldError>{fieldErrors.envName}</FieldError>}</TextField>
                {draft.kind === 'ai' && <TextField fullWidth value={draft.baseUrl} onChange={(baseUrl) => { setDraft((current) => ({ ...current, baseUrl })); clearFieldError('baseUrl') }} isInvalid={Boolean(fieldErrors.baseUrl)}><Label>Base URL（可选）</Label><Input type="url" placeholder="留空则沿用全局 AI Base URL" />{fieldErrors.baseUrl && <FieldError>{fieldErrors.baseUrl}</FieldError>}</TextField>}
                <TextField fullWidth value={draft.value} onChange={(value) => { setDraft((current) => ({ ...current, value })); clearFieldError('value') }} isRequired isInvalid={Boolean(fieldErrors.value)}><Label>Key 值</Label><Input type="password" autoComplete="new-password" />{fieldErrors.value && <FieldError>{fieldErrors.value}</FieldError>}</TextField>
                {formError && <div data-testid="secret-form-feedback"><StatusNotice title={formError} status="warning" /></div>}
              </form></Modal.Body>
              <Modal.Footer><Button type="button" variant="ghost" isDisabled={creating} onPress={closeCreate}>取消</Button><Button type="submit" form="create-secret" isDisabled={creating}>{creating ? '保存中…' : '安全保存 Key'}</Button></Modal.Footer>
            </Modal.Dialog></Modal.Container>
          </Modal.Backdrop>
        </Modal>
      </SettingsSection>

      {secrets.isPending
        ? <LoadingState label="正在读取密钥元数据" rows={3} />
        : secrets.isError
          ? <StatusNotice title="密钥读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void secrets.refetch()}>重试此区域</Button></StatusNotice>
          : <>
            <ApifyKeyPoolGroup secrets={secrets.data?.secrets ?? []} userId={user.id} onSecretChanged={secretChanged} />
            <SettingsSection title="AI Key" description="每个 AI Key 可独立保存 Base URL；未设置时才沿用全局 AI Base URL。">
              <SettingsGroup ariaLabel="已配置 AI Key">
                {!aiSecrets.length
                  ? <SettingsItem label="尚未配置 AI Key" description="新增 AI Key 后，可在 AI 设置中选择它作为工作区模型凭据。" icon={<Icons.Sparkles size={17} aria-hidden="true" />} />
                  : aiSecrets.map((secret) => {
                    const presentation = secretPresentation(secret)
                    return <SettingsItem key={secret.id} density="compact" label={presentation.name} description={`${presentation.provider} · ${secret.env_name}${secret.base_url ? ` · ${secret.base_url}` : ' · 使用全局 Base URL'}`} icon={<Icons.Sparkles size={17} aria-hidden="true" />} trailing={<div className="flex flex-wrap gap-2"><SecretConnectionEditor secret={secret} onChanged={secretChanged} /><SecretActions secret={secret} onChanged={secretChanged} /></div>}>
                      <div className="flex flex-wrap items-center gap-2"><StatusBadge tone={secret.is_set ? 'success' : 'warning'}>{presentation.status}</StatusBadge><span className="type-meta text-muted">{presentation.usage}</span>{secret.used_by.length > 0 && <span className="type-meta text-muted">正在被 {secret.used_by.map((usage) => usage.name).join('、')} 使用</span>}</div>
                    </SettingsItem>
                  })}
              </SettingsGroup>
            </SettingsSection>
          </>}
    </PageFrame>
  </div>
}
