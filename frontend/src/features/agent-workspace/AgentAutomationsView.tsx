import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  Button, Card, EmptyState, FieldError, FormSelect, Icons, Input, Label, LoadingState, Modal,
  StableAsyncButton, StatusIndicator, StatusNotice, Switch, TextArea, TextField, actionToast,
} from '../../design-system'
import type { OpenClawChatController } from '../openclaw'
import type { OpenClawAutomation, OpenClawAutomationDraft, OpenClawAutomationRun, OpenClawAutomationSchedule } from '../openclaw/admin/OpenClawAdminSessionController'
import { AdminAuthorizationDialog, AdminConnectedNotice } from './OpenClawAdminAuthorization'
import { automationLocalTime, projectAutomationDraft } from './agentAutomationDraft'
import { useOpenClawAdminSession } from './useOpenClawAdminSession'

type ScheduleKind = OpenClawAutomationSchedule['kind']
type ConfirmAction =
  | { kind: 'save'; draft: OpenClawAutomationDraft; target: OpenClawAutomation | 'new' }
  | { kind: 'toggle'; target: OpenClawAutomation; enabled: boolean }
  | { kind: 'run'; target: OpenClawAutomation }
  | { kind: 'remove'; target: OpenClawAutomation }

function scheduleLabel(schedule: OpenClawAutomationSchedule): string {
  if (schedule.kind === 'at') return `一次 · ${new Date(schedule.at).toLocaleString()}`
  if (schedule.kind === 'every') return `每 ${Math.round(schedule.everyMs / 60_000)} 分钟`
  return `${schedule.expr} · ${schedule.tz}`
}

function confirmationText(action: ConfirmAction): string {
  if (action.kind === 'save') return `${action.target === 'new' ? '创建' : '修改'} Automation “${action.draft.name}”？Gateway 将持久保存此计划。`
  if (action.kind === 'toggle') return `${action.enabled ? '启用' : '停用'} Automation “${action.target.name}”？`
  if (action.kind === 'run') return `立即运行 Automation “${action.target.name}”？`
  return `删除 Automation “${action.target.name}”？此操作无法由 Inscope 回滚。`
}

export function AgentAutomationsView({ chat }: { chat: OpenClawChatController }) {
  const authorization = useOpenClawAdminSession(chat.gatewayUrl)
  const [automations, setAutomations] = useState<OpenClawAutomation[]>([])
  const [schedulerEnabled, setSchedulerEnabled] = useState<boolean | null>(null)
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [schedulerError, setSchedulerError] = useState('')
  const [busy, setBusy] = useState('')
  const [editing, setEditing] = useState<OpenClawAutomation | 'new' | null>(null)
  const [confirming, setConfirming] = useState<ConfirmAction | null>(null)
  const [runsTarget, setRunsTarget] = useState<OpenClawAutomation | null>(null)
  const [runs, setRuns] = useState<OpenClawAutomationRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsError, setRunsError] = useState('')
  const [authorizationOpen, setAuthorizationOpen] = useState(false)
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [scheduleKind, setScheduleKind] = useState<ScheduleKind>('every')
  const [at, setAt] = useState('')
  const [everyMinutes, setEveryMinutes] = useState('60')
  const [cronExpr, setCronExpr] = useState('0 9 * * *')
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')

  const load = useCallback(async () => {
    if (!authorization.admin) return
    setListLoading(true)
    setListError('')
    setSchedulerError('')
    const [items, scheduler] = await Promise.allSettled([
      authorization.admin.listAutomations(), authorization.admin.schedulerStatus(),
    ])
    if (items.status === 'fulfilled') setAutomations(items.value)
    else setListError(items.reason instanceof Error ? items.reason.message : 'Automation 列表读取失败。')
    if (scheduler.status === 'fulfilled') setSchedulerEnabled(scheduler.value.enabled)
    else setSchedulerError(scheduler.reason instanceof Error ? scheduler.reason.message : 'Scheduler 状态读取失败。')
    setListLoading(false)
  }, [authorization.admin])

  useEffect(() => { void Promise.resolve().then(load) }, [load])

  function openEditor(target: OpenClawAutomation | 'new') {
    setEditing(target)
    if (target === 'new') {
      setName(''); setMessage(''); setScheduleKind('every'); setEveryMinutes('60'); setCronExpr('0 9 * * *'); setAt('')
      return
    }
    setName(target.name); setMessage(target.message); setScheduleKind(target.schedule.kind)
    if (target.schedule.kind === 'at') setAt(automationLocalTime(target.schedule.at))
    if (target.schedule.kind === 'every') setEveryMinutes(String(target.schedule.everyMs / 60_000))
    if (target.schedule.kind === 'cron') { setCronExpr(target.schedule.expr); setTimezone(target.schedule.tz) }
  }

  const formResult = useMemo(() => projectAutomationDraft({ name, message, scheduleKind, at, everyMinutes, cronExpr, timezone }), [at, cronExpr, everyMinutes, message, name, scheduleKind, timezone])

  async function executeConfirmed() {
    if (!authorization.admin || !confirming) return
    const action = confirming
    setBusy(action.kind === 'save' ? 'save' : action.target.id)
    try {
      if (action.kind === 'save') {
        if (action.target === 'new') await authorization.admin.createAutomation(action.draft)
        else await authorization.admin.updateAutomation(action.target.id, action.draft)
        setEditing(null)
      } else if (action.kind === 'toggle') await authorization.admin.setAutomationEnabled(action.target.id, action.enabled)
      else if (action.kind === 'run') await authorization.admin.runAutomation(action.target.id)
      else await authorization.admin.removeAutomation(action.target.id)
      actionToast.success(action.kind === 'run' ? '运行已入队' : 'Automation 操作已完成')
      setConfirming(null)
      await load()
    } catch (reason) {
      setListError(reason instanceof Error ? reason.message : 'Automation 操作失败。')
    } finally { setBusy('') }
  }

  async function showRuns(target: OpenClawAutomation) {
    if (!authorization.admin) return
    setRunsTarget(target); setRuns([]); setRunsError(''); setRunsLoading(true)
    try { setRuns(await authorization.admin.automationRuns(target.id)) }
    catch (reason) { setRunsError(reason instanceof Error ? reason.message : '运行记录读取失败。') }
    finally { setRunsLoading(false) }
  }

  const capabilities = authorization.admin?.capabilities()
  const locked = !authorization.admin

  return <div className="quiet-scroll-region h-full overflow-y-auto p-4 min-[768px]:p-6" data-agent-automations-view data-page-scroll-region>
    <div className="mx-auto grid max-w-5xl gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1"><h2 className="type-section-title">Automations</h2><p className="type-body mt-1 text-muted">由 OpenClaw Gateway 保存和执行；关闭 Inscope 页面后仍会继续。</p></div>
        {locked ? <Button onPress={() => setAuthorizationOpen(true)}><Icons.LockKeyhole size={16} />临时授权</Button> : <Button isDisabled={!capabilities?.['cron.add']} onPress={() => openEditor('new')}><Icons.Plus size={16} />新建</Button>}
      </div>
      {authorization.admin && <AdminConnectedNotice onClose={authorization.close} />}
      {authorization.state === 'expired' && <StatusNotice title="临时管理连接已过期" status="warning">请在需要写操作时重新授权。</StatusNotice>}
      {locked ? <div className="grid min-h-56 place-items-center border-y border-separator py-10 text-center"><div className="max-w-md"><Icons.LockKeyhole size={24} className="mx-auto text-accent" aria-hidden="true" /><h3 className="type-page-title mt-3">管理操作已锁定</h3><p className="type-body mt-1 text-muted">授权后读取和管理 Automation；普通聊天连接不会获得 admin 权限。</p></div></div> : <>
        {schedulerEnabled === false && <StatusNotice title="Gateway Scheduler 已停用" status="warning">Inscope 不会自动开启 Scheduler。</StatusNotice>}
        {schedulerError && <StatusNotice title="Scheduler 状态读取失败" status="danger">{schedulerError}</StatusNotice>}
        {listLoading && !automations.length ? <LoadingState label="正在读取 Automations" rows={4} /> : automations.length ? <div className="grid gap-2">
          {automations.map((automation) => <Card key={automation.id} variant="secondary" className="p-4"><div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-1"><strong className="type-control block truncate">{automation.name}</strong><p className="type-meta mt-1 text-muted">{scheduleLabel(automation.schedule)} · isolated session</p><p className="type-body mt-2 line-clamp-2 text-muted">{automation.message}</p></div>
            <StatusIndicator tone={automation.enabled ? 'success' : 'neutral'} label={automation.enabled ? '已启用' : '已停用'} />
            <Switch isSelected={automation.enabled} isDisabled={busy === automation.id} aria-label={`${automation.enabled ? '停用' : '启用'} ${automation.name}`} onChange={(enabled) => setConfirming({ kind: 'toggle', target: automation, enabled })}><Switch.Control><Switch.Thumb /></Switch.Control></Switch>
            <div className="flex flex-wrap gap-1"><Button size="sm" variant="ghost" isDisabled={Boolean(busy)} onPress={() => void showRuns(automation)}>记录</Button><Button size="sm" variant="ghost" isDisabled={Boolean(busy)} onPress={() => openEditor(automation)}>修改</Button><Button size="sm" variant="ghost" isDisabled={Boolean(busy)} onPress={() => setConfirming({ kind: 'run', target: automation })}><Icons.Play size={14} />运行</Button><Button size="sm" variant="ghost" className="text-danger" isDisabled={Boolean(busy)} onPress={() => setConfirming({ kind: 'remove', target: automation })}><Icons.Trash2 size={14} />删除</Button></div>
          </div></Card>)}
        </div> : <EmptyState title="没有 Automations" description="新建的计划默认停用，确认后再单独启用。" />}
      </>}
      {listError && <StatusNotice title="Automation 操作失败" status="danger">{listError}</StatusNotice>}
    </div>

    <AutomationEditor
      open={Boolean(editing)}
      isNew={editing === 'new'}
      values={{ name, message, scheduleKind, at, everyMinutes, cronExpr, timezone }}
      errors={formResult.errors}
      busy={busy === 'save'}
      onChange={{ setName, setMessage, setScheduleKind, setAt, setEveryMinutes, setCronExpr, setTimezone }}
      onClose={() => setEditing(null)}
      onContinue={() => formResult.draft && editing && setConfirming({ kind: 'save', draft: formResult.draft, target: editing })}
      ready={Boolean(formResult.draft)}
    />

    <Modal isOpen={Boolean(confirming)} onOpenChange={(open) => !open && !busy && setConfirming(null)}><Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={Boolean(busy)}><Modal.Container size="sm"><Modal.Dialog>
      <Modal.Header><Modal.Heading>确认 Gateway 写操作</Modal.Heading></Modal.Header>
      <Modal.Body><p className="type-body text-muted">{confirming ? confirmationText(confirming) : ''}</p></Modal.Body>
      <Modal.Footer><Button variant="ghost" isDisabled={Boolean(busy)} onPress={() => setConfirming(null)}>返回</Button><StableAsyncButton pending={Boolean(busy)} pendingContent="提交中…" onPress={executeConfirmed}>确认执行</StableAsyncButton></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>

    <Modal isOpen={Boolean(runsTarget)} onOpenChange={(open) => !open && setRunsTarget(null)}><Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
      <Modal.Header><Modal.Heading>{runsTarget?.name ?? '运行记录'}</Modal.Heading></Modal.Header>
      <Modal.Body>{runsLoading ? <LoadingState label="正在读取运行记录" rows={3} /> : runsError ? <div className="grid gap-3"><StatusNotice title="运行记录读取失败" status="danger">{runsError}</StatusNotice><Button variant="secondary" onPress={() => runsTarget && void showRuns(runsTarget)}>重试</Button></div> : runs.length ? <div className="grid gap-2">{runs.map((run, index) => <Card key={run.runId ?? `${run.ts}:${index}`} variant="secondary" className="p-3"><div className="flex items-center justify-between gap-3"><span className="type-control">{new Date(run.ts).toLocaleString()}</span><StatusIndicator tone={run.completionStatus === 'succeeded' ? 'success' : run.completionStatus === 'failed' ? 'danger' : 'neutral'} label={run.completionStatus ?? run.status ?? '未知'} /></div><p className="type-meta mt-2 text-muted">{run.summary ?? run.error ?? run.runId ?? 'Gateway 未返回摘要'}</p></Card>)}</div> : <EmptyState title="没有运行记录" />}</Modal.Body>
      <Modal.Footer><Button onPress={() => setRunsTarget(null)}>关闭</Button></Modal.Footer>
    </Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
    <AdminAuthorizationDialog open={authorizationOpen} onOpenChange={setAuthorizationOpen} connecting={authorization.connecting} error={authorization.error} onConnect={authorization.connect} />
  </div>
}

function AutomationEditor({ open, isNew, values, errors, busy, onChange, onClose, onContinue, ready }: {
  open: boolean
  isNew: boolean
  values: { name: string; message: string; scheduleKind: ScheduleKind; at: string; everyMinutes: string; cronExpr: string; timezone: string }
  errors: Partial<Record<'name' | 'message' | 'at' | 'everyMinutes' | 'cronExpr' | 'timezone', string>>
  busy: boolean
  onChange: { setName: (value: string) => void; setMessage: (value: string) => void; setScheduleKind: (value: ScheduleKind) => void; setAt: (value: string) => void; setEveryMinutes: (value: string) => void; setCronExpr: (value: string) => void; setTimezone: (value: string) => void }
  onClose: () => void
  onContinue: () => void
  ready: boolean
}) {
  return <Modal isOpen={open} onOpenChange={(next) => !next && !busy && onClose()}><Modal.Backdrop isDismissable={!busy} isKeyboardDismissDisabled={busy}><Modal.Container size="lg"><Modal.Dialog>
    <Modal.Header><Modal.Heading>{isNew ? '新建 Automation' : '修改 Automation'}</Modal.Heading></Modal.Header>
    <Modal.Body><div className="grid gap-3">
      <TextField fullWidth value={values.name} onChange={onChange.setName} isRequired isInvalid={Boolean(errors.name)}><Label>名称</Label><Input aria-label="Automation 名称" />{errors.name && <FieldError>{errors.name}</FieldError>}</TextField>
      <TextField fullWidth value={values.message} onChange={onChange.setMessage} isRequired isInvalid={Boolean(errors.message)}><Label>Agent 提示词</Label><TextArea aria-label="Automation 提示词" className="min-h-28" />{errors.message && <FieldError>{errors.message}</FieldError>}</TextField>
      <FormSelect label="计划类型" value={values.scheduleKind} options={[{ id: 'at', label: '一次执行' }, { id: 'every', label: '固定间隔' }, { id: 'cron', label: 'Cron 表达式' }]} onChange={(value) => onChange.setScheduleKind(value as ScheduleKind)} />
      {values.scheduleKind === 'at' && <TextField fullWidth value={values.at} onChange={onChange.setAt} isInvalid={Boolean(errors.at)}><Label>执行时间</Label><Input type="datetime-local" aria-label="执行时间" />{errors.at && <FieldError>{errors.at}</FieldError>}</TextField>}
      {values.scheduleKind === 'every' && <TextField fullWidth value={values.everyMinutes} onChange={onChange.setEveryMinutes} isInvalid={Boolean(errors.everyMinutes)}><Label>间隔（分钟）</Label><Input type="number" min="1" aria-label="间隔（分钟）" />{errors.everyMinutes && <FieldError>{errors.everyMinutes}</FieldError>}</TextField>}
      {values.scheduleKind === 'cron' && <div className="grid gap-3 min-[640px]:grid-cols-2"><TextField fullWidth value={values.cronExpr} onChange={onChange.setCronExpr} isInvalid={Boolean(errors.cronExpr)}><Label>Cron 表达式</Label><Input aria-label="Cron 表达式" />{errors.cronExpr && <FieldError>{errors.cronExpr}</FieldError>}</TextField><TextField fullWidth value={values.timezone} onChange={onChange.setTimezone} isInvalid={Boolean(errors.timezone)}><Label>IANA 时区</Label><Input aria-label="IANA 时区" />{errors.timezone && <FieldError>{errors.timezone}</FieldError>}</TextField></div>}
      <StatusNotice title="仅 agentTurn · isolated session" status="info">不提供 Webhook、外部频道、Shell、秘密字段或自动启用。</StatusNotice>
    </div></Modal.Body>
    <Modal.Footer><Button variant="ghost" isDisabled={busy} onPress={onClose}>取消</Button><Button isDisabled={!ready} onPress={onContinue}>继续确认</Button></Modal.Footer>
  </Modal.Dialog></Modal.Container></Modal.Backdrop></Modal>
}
