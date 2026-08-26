import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type {
  SystemSetting,
  SystemSettingChange,
  SystemSettingProposal,
  SystemSettingValue,
} from '../../api/systemSettingsService'
import { useAppContext } from '../../app/AppContext'
import { SettingsGroup, SettingsItem, SettingsSection, StatusBadge } from '../../components/settings'
import {
  Button,
  Icons,
  Input,
  Label,
  LoadingState,
  Modal,
  PageFrame,
  Switch,
  TextField,
  actionToast,
} from '../../design-system'
import { HeroNotice } from '../admin-heroui/HeroAdminControls'
import { canAdministerSettings } from './settingsNavigation'
import { preserveSettingsReturnState } from './settingsReturnState'

const CATEGORY_LABELS: Record<SystemSetting['category'], string> = {
  capacity: '容量与配额',
  jobs: '任务与调度',
  retention: '数据保留',
  storage: '存储格式',
  acquisition: '共享采集',
}

const SOURCE_LABELS: Record<SystemSetting['source'], string> = {
  override: '数据库覆盖',
  environment: '环境变量',
  default: '内置默认',
}

const TIMING_LABELS: Record<string, string> = {
  next_operation: '下次操作',
  new_jobs: '新任务',
  next_failure: '下次失败',
  next_maintenance: '下次维护',
  next_snapshot: '下次快照',
}

type Draft = Record<string, SystemSettingValue | null>

function errorMessage(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : '系统参数操作失败。'
}

function settingDescription(setting: SystemSetting): string {
  const range = setting.kind === 'integer' ? `范围 ${setting.minimum}–${setting.maximum}` : '布尔值'
  return `${setting.description} · ${setting.env_name} · ${range} · ${TIMING_LABELS[setting.effect_timing] ?? setting.effect_timing}`
}

function SystemSettingControl({ setting, draft, onChange, onReset, onValidityChange }: {
  setting: SystemSetting
  draft: Draft
  onChange: (value: SystemSettingValue) => void
  onReset: () => void
  onValidityChange: (valid: boolean) => void
}) {
  const changed = Object.prototype.hasOwnProperty.call(draft, setting.key)
  const drafted = changed ? draft[setting.key] : setting.value
  const value = drafted === null ? setting.fallback_value : drafted
  const [integerValue, setIntegerValue] = useState(String(value))
  const reset = () => {
    setIntegerValue(String(setting.fallback_value))
    onValidityChange(true)
    onReset()
  }
  return <div className="grid justify-items-end gap-2">
    {setting.kind === 'boolean' ? <Switch
      aria-label={setting.key}
      isSelected={Boolean(value)}
      onChange={onChange}
    ><Switch.Control><Switch.Thumb /></Switch.Control></Switch> : <TextField
      aria-label={setting.key}
      value={integerValue}
      onChange={(next) => {
        setIntegerValue(next)
        const numeric = Number(next)
        const valid = /^-?\d+$/.test(next)
          && numeric >= Number(setting.minimum)
          && numeric <= Number(setting.maximum)
        onValidityChange(valid)
        if (valid) onChange(numeric)
      }}
      className="w-32"
    ><Input type="number" min={setting.minimum ?? undefined} max={setting.maximum ?? undefined} /></TextField>}
    <div className="flex flex-wrap justify-end gap-1.5">
      <StatusBadge tone={setting.source === 'override' ? 'accent' : 'neutral'}>{SOURCE_LABELS[setting.source]}</StatusBadge>
      <StatusBadge tone={setting.risk === 'high' ? 'warning' : 'neutral'}>{setting.risk} 风险</StatusBadge>
    </div>
    {(setting.override !== null || changed) && <Button size="sm" variant="ghost" onPress={reset}>恢复环境/默认值</Button>}
  </div>
}

function ProposalDialog({ proposal, confirmation, pending, error, onConfirmation, onClose, onApply }: {
  proposal: SystemSettingProposal
  confirmation: string
  pending: boolean
  error: string
  onConfirmation: (value: string) => void
  onClose: () => void
  onApply: () => void
}) {
  return <Modal isOpen onOpenChange={(open) => !open && !pending && onClose()}>
    <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开系统参数预演</Modal.Trigger>
    <Modal.Backdrop isDismissable={!pending} isKeyboardDismissDisabled={pending}>
      <Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>确认系统参数变更</Modal.Heading></Modal.Header>
        <Modal.Body>
          <div className="grid gap-3">
            {proposal.changes.map((change) => <div key={change.key} className="rounded-lg border border-separator bg-default p-3">
              <code className="type-control break-all">{change.key}</code>
              <p className="type-body mt-1 text-muted">{String(change.before)} → {String(change.after)}{change.reset ? '（删除覆盖值）' : ''} · {TIMING_LABELS[change.effect_timing] ?? change.effect_timing}</p>
            </div>)}
            {proposal.warnings.length > 0 && <HeroNotice title="请确认以下影响" status="warning" role="status"><ul className="mt-2 list-disc pl-5">{proposal.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></HeroNotice>}
            <p className="type-body text-muted">提案于 {new Date(proposal.expires_at).toLocaleString('zh-CN')} 失效。请输入：<code>{proposal.confirmation}</code></p>
            <TextField fullWidth value={confirmation} onChange={onConfirmation} isRequired>
              <Label>精确确认短语</Label><Input autoComplete="off" />
            </TextField>
            {error && <HeroNotice title={error} />}
          </div>
        </Modal.Body>
        <Modal.Footer><Button variant="ghost" isDisabled={pending} onPress={onClose}>取消</Button><Button isDisabled={pending || confirmation !== proposal.confirmation} onPress={onApply}>{pending ? '应用中…' : '应用变更'}</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container>
    </Modal.Backdrop>
  </Modal>
}

export function SettingsSystemPage() {
  const { api, user } = useAppContext()
  const location = useLocation()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Draft>({})
  const [proposal, setProposal] = useState<SystemSettingProposal | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [operationError, setOperationError] = useState('')
  const [invalidKeys, setInvalidKeys] = useState<Set<string>>(() => new Set())
  const query = useQuery({
    queryKey: queryKeys.systemSettings(user.id),
    queryFn: ({ signal }) => api.systemSettings(signal),
    enabled: canAdministerSettings(user.role),
  })
  const changes: SystemSettingChange[] = Object.entries(draft).map(([key, value]) => ({ key, value }))
  const prepare = useMutation({
    mutationFn: () => api.prepareSystemSettings(query.data!.generation, changes),
    onSuccess: (result) => { setProposal(result); setConfirmation(''); setOperationError('') },
    onError: (error) => {
      setOperationError(errorMessage(error))
      if (error instanceof ApiError && error.code === 'system_settings_generation_conflict') void query.refetch()
    },
  })
  const apply = useMutation({
    mutationFn: () => api.applySystemSettings(proposal!.proposal_id, confirmation),
    onSuccess: async (result) => {
      setProposal(null); setConfirmation(''); setDraft({}); setInvalidKeys(new Set()); setOperationError('')
      await queryClient.invalidateQueries({ queryKey: queryKeys.systemSettings(user.id) })
      actionToast.success(`已应用 ${result.changed_keys.length} 个系统参数`)
    },
    onError: (error) => {
      setOperationError(errorMessage(error))
      if (error instanceof ApiError && error.code === 'system_settings_generation_conflict') void query.refetch()
    },
  })

  if (!canAdministerSettings(user.role)) return <Navigate to="/settings" state={preserveSettingsReturnState(location.state)} replace />
  if (query.isLoading) return <PageFrame width="settings" className="p-6"><LoadingState label="正在读取系统参数" rows={5} /></PageFrame>
  if (query.isError || !query.data) return <PageFrame width="settings" className="p-6"><HeroNotice title={errorMessage(query.error)}><Button size="sm" variant="ghost" onPress={() => void query.refetch()}>重试</Button></HeroNotice></PageFrame>

  return <div data-settings-page="system" data-page-scroll-region className="quiet-scroll-region h-full overflow-x-hidden overflow-y-auto">
    <PageFrame width="settings" className="grid gap-7 p-4 pb-10 min-[768px]:p-6 min-[768px]:pb-12">
      <SettingsSection title="系统参数" description={`工作区安全白名单参数 · 当前代次 ${query.data.generation}`} actions={<Button isDisabled={!changes.length || invalidKeys.size > 0 || prepare.isPending} onPress={() => prepare.mutate()}>{prepare.isPending ? '生成预演中…' : `预演 ${changes.length || ''} 项变更`}</Button>}>
        <HeroNotice title="数据库覆盖值优先于环境变量和内置默认值" status="accent" role="status">所有修改都要先预演并输入精确确认短语；页面不提供密钥、地址、数据库路径或付费 Actor 参数。</HeroNotice>
        {operationError && !proposal && <div className="mt-3"><HeroNotice title={operationError} /></div>}
      </SettingsSection>
      {Object.entries(CATEGORY_LABELS).map(([category, label]) => {
        const settings = query.data.settings.filter((setting) => setting.category === category)
        return <SettingsSection key={category} title={label} description={`${settings.length} 个可调参数`}>
          <SettingsGroup ariaLabel={label}>{settings.map((setting) => <SettingsItem
            key={setting.key}
            label={setting.key}
            description={settingDescription(setting)}
            icon={<Icons.SlidersHorizontal size={17} aria-hidden="true" />}
            trailing={<SystemSettingControl
              setting={setting}
              draft={draft}
              onChange={(value) => setDraft((current) => ({ ...current, [setting.key]: value }))}
              onReset={() => setDraft((current) => {
                const next = { ...current }
                if (setting.override === null) delete next[setting.key]
                else next[setting.key] = null
                return next
              })}
              onValidityChange={(valid) => setInvalidKeys((current) => {
                if (current.has(setting.key) !== valid) return current
                const next = new Set(current)
                if (valid) next.delete(setting.key)
                else next.add(setting.key)
                return next
              })}
            />}
          />)}</SettingsGroup>
        </SettingsSection>
      })}
    </PageFrame>
    {proposal && <ProposalDialog proposal={proposal} confirmation={confirmation} pending={apply.isPending} error={operationError} onConfirmation={setConfirmation} onClose={() => { setProposal(null); setConfirmation(''); setOperationError('') }} onApply={() => apply.mutate()} />}
  </div>
}
