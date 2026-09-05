import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  Button,
  EmptyState,
  FormSelect,
  LoadingState,
  Modal,
  StableAsyncButton,
  StatusIndicator,
  StatusNotice,
  actionToast,
} from '../../design-system'
import {
  OPENCLAW_TASK_STATUSES,
  type OpenClawChatController,
  type OpenClawTask,
  type OpenClawTaskStatus,
} from '../openclaw'

const statusLabels: Record<OpenClawTaskStatus, string> = {
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  timed_out: '超时',
}

function taskTone(status: OpenClawTaskStatus) {
  if (status === 'completed') return 'success' as const
  if (status === 'failed' || status === 'timed_out') return 'danger' as const
  if (status === 'running') return 'accent' as const
  if (status === 'queued') return 'warning' as const
  return 'neutral' as const
}

function TaskDialogs({
  detail,
  cancelTarget,
  cancelling,
  onCloseDetail,
  onCloseCancel,
  onCancel,
}: {
  detail: OpenClawTask | null
  cancelTarget: OpenClawTask | null
  cancelling: boolean
  onCloseDetail: () => void
  onCloseCancel: () => void
  onCancel: () => void
}) {
  return <>
    <Modal isOpen={Boolean(detail)} onOpenChange={(open) => !open && onCloseDetail()}>
      <Modal.Backdrop><Modal.Container size="lg"><Modal.Dialog>
        <Modal.Header><Modal.Heading>{detail?.title ?? 'Task 详情'}</Modal.Heading></Modal.Header>
        <Modal.Body><div className="grid gap-3">
          <StatusIndicator tone={detail ? taskTone(detail.status) : 'neutral'} label={detail ? statusLabels[detail.status] : '读取中'} />
          {detail?.prompt && <section><strong className="type-label">提示词</strong><pre className="type-body mt-1 whitespace-pre-wrap rounded-[var(--inteliscope-radius-control)] bg-default p-3">{detail.prompt}</pre></section>}
          {detail?.result && <section><strong className="type-label">结果</strong><pre className="type-body mt-1 whitespace-pre-wrap rounded-[var(--inteliscope-radius-control)] bg-default p-3">{detail.result}</pre></section>}
          {detail?.error && <StatusNotice title={detail.error} status="danger" />}
        </div></Modal.Body>
        <Modal.Footer><Button onPress={onCloseDetail}>关闭</Button></Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
    <Modal isOpen={Boolean(cancelTarget)} onOpenChange={(open) => !open && !cancelling && onCloseCancel()}>
      <Modal.Backdrop isDismissable={!cancelling} isKeyboardDismissDisabled={cancelling}><Modal.Container size="sm"><Modal.Dialog>
        <Modal.Header><Modal.Heading>取消 Task？</Modal.Heading></Modal.Header>
        <Modal.Body><p className="type-body text-muted">Gateway 可能已经产生外部副作用；取消不会回滚已完成的操作。</p></Modal.Body>
        <Modal.Footer>
          <Button variant="ghost" isDisabled={cancelling} onPress={onCloseCancel}>返回</Button>
          <StableAsyncButton variant="danger" pending={cancelling} pendingContent="取消中…" onPress={onCancel}>确认取消</StableAsyncButton>
        </Modal.Footer>
      </Modal.Dialog></Modal.Container></Modal.Backdrop>
    </Modal>
  </>
}

export function AgentTasksView({
  chat,
  scopeKeys,
  writeTrusted,
  onRequireWriteTrust,
  variant = 'page',
}: {
  chat: OpenClawChatController
  scopeKeys: string[]
  writeTrusted: boolean
  onRequireWriteTrust: () => void
  variant?: 'page' | 'inspector'
}) {
  const [status, setStatus] = useState<'all' | OpenClawTaskStatus>('all')
  const [tasks, setTasks] = useState<OpenClawTask[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [detail, setDetail] = useState<OpenClawTask | null>(null)
  const [cancelTarget, setCancelTarget] = useState<OpenClawTask | null>(null)
  const [cancelling, setCancelling] = useState(false)
  const [revision, setRevision] = useState(0)
  const [reliableEventScope, setReliableEventScope] = useState('')
  const scopeSignature = `${chat.gatewayUrl}\u0000${chat.status}\u0000${scopeKeys.join('\u0000')}`
  const taskEventSeen = reliableEventScope === scopeSignature
  const refresh = useCallback(() => setRevision((value) => value + 1), [])

  useEffect(() => chat.workspace.subscribe((event) => {
    if (event === 'task') setReliableEventScope(scopeSignature)
    if (event === 'task' || event === 'sessions.changed') refresh()
  }), [chat.workspace, refresh, scopeSignature])

  useEffect(() => {
    if (chat.status !== 'connected' || !scopeKeys.length || !chat.workspace.capabilities()['tasks.list']) return
    let active = true
    void Promise.resolve().then(() => {
      if (active) { setLoading(true); setError('') }
      return Promise.all(scopeKeys.map((sessionKey) => chat.workspace.listTasks({
          sessionKey,
          ...(status === 'all' ? {} : { status }),
        })))
    })
      .then((pages) => {
        if (!active) return
        const unique = new Map(pages.flatMap((page) => page.tasks).map((task) => [task.id, task]))
        setTasks([...unique.values()]
          .sort((left, right) => String(right.updatedAt ?? right.createdAt ?? '').localeCompare(String(left.updatedAt ?? left.createdAt ?? '')))
          .slice(0, 50))
      })
      .catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : String(reason)) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [chat.status, chat.workspace, revision, scopeKeys, status])

  const hasActiveTasks = useMemo(
    () => tasks.some((task) => task.status === 'queued' || task.status === 'running'),
    [tasks],
  )

  useEffect(() => {
    if (taskEventSeen || !hasActiveTasks) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') refresh()
    }, 2_000)
    return () => window.clearInterval(timer)
  }, [hasActiveTasks, refresh, taskEventSeen])

  async function showDetail(task: OpenClawTask) {
    if (!task.sessionKey) {
      setError('Task 缺少可信 Session 来源，已阻止读取。')
      return
    }
    setDetail(task)
    try {
      setDetail(await chat.workspace.getTask(task.id, task.sessionKey))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    }
  }

  async function cancel() {
    if (!cancelTarget) return
    if (!cancelTarget.sessionKey) {
      setError('Task 缺少可信 Session 来源，已阻止取消。')
      setCancelTarget(null)
      return
    }
    setCancelling(true)
    try {
      const cancelled = await chat.workspace.cancelTask(cancelTarget.id, cancelTarget.sessionKey, '用户从 Inscope Agent Workspace 取消')
      if (!cancelled) throw new Error('Gateway 未确认取消任务。')
      actionToast.success('任务已取消')
      setCancelTarget(null)
      refresh()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setCancelling(false)
    }
  }

  const connected = chat.status === 'connected'
  const unsupported = connected && !chat.workspace.capabilities()['tasks.list']
  const compact = variant === 'inspector'

  return <div className="quiet-scroll-region h-full overflow-y-auto" data-agent-tasks-view data-agent-resource-variant={variant}>
    <div className={compact ? '' : 'mx-auto max-w-5xl p-4 min-[768px]:p-6'}>
      <div className={`flex flex-wrap items-center gap-3 ${compact ? 'border-b border-separator px-4 py-4' : 'mb-4'}`}>
        <div className="min-w-0 flex-1">
          {!compact && <h2 className="type-page-title">后台 Tasks</h2>}
          <p className="type-body mt-1 text-muted">当前 Session 与可信子 Session，最多 50 条。</p>
        </div>
        <FormSelect
          label="Task 状态"
          value={status}
          options={[{ id: 'all', label: '全部状态' }, ...OPENCLAW_TASK_STATUSES.map((id) => ({ id, label: statusLabels[id] }))]}
          onChange={(value) => setStatus(value as typeof status)}
          className="w-40"
        />
      </div>
      <div className={compact ? 'p-4' : ''}>
        {!connected ? <StatusNotice title="连接 Gateway 后查看 Tasks" status="default">当前连接未就绪；已有对话内容不会被清空。</StatusNotice>
          : unsupported ? <StatusNotice title="当前 Gateway 不支持 Tasks" status="warning">缺少 tasks.list；聊天仍可继续使用。</StatusNotice>
          : loading && !tasks.length ? <LoadingState label="正在读取 Tasks" rows={4} />
            : tasks.length ? <div className="divide-y divide-separator border-y border-separator">
              {tasks.map((task) => <div key={task.id} className="flex min-w-0 items-start gap-3 py-3">
                <button type="button" className="min-w-0 flex-1 text-left focus-visible:outline-2 focus-visible:outline-focus" onClick={() => void showDetail(task)}>
                  <strong className="type-control block truncate">{task.title ?? task.id}</strong>
                  <span className="type-meta mt-1 block text-muted">{task.progressSummary ?? task.terminalSummary ?? task.error ?? task.kind ?? 'Gateway task'}</span>
                </button>
                <StatusIndicator tone={taskTone(task.status)} label={statusLabels[task.status]} />
                {(task.status === 'queued' || task.status === 'running') && chat.workspace.capabilities()['tasks.cancel'] && <Button size="sm" variant="ghost" onPress={() => writeTrusted ? setCancelTarget(task) : onRequireWriteTrust()}>取消</Button>}
              </div>)}
            </div>
              : <EmptyState title="没有 Tasks" description="新的 Worktree 任务和后台运行会出现在这里。" />}
        {error && <div className="mt-3"><StatusNotice title="Tasks 操作失败" status="danger">{error}</StatusNotice></div>}
      </div>
    </div>

    <TaskDialogs
      detail={detail}
      cancelTarget={cancelTarget}
      cancelling={cancelling}
      onCloseDetail={() => setDetail(null)}
      onCloseCancel={() => setCancelTarget(null)}
      onCancel={() => void cancel()}
    />
  </div>
}
