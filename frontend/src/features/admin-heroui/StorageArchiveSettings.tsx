import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { StorageArchive, StorageOperation, StoragePlan } from '../../api/types'
import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import { useAppContext } from '../../app/AppContext'
import { SettingsCard, SettingsGroup, SettingsItem, SettingsSection, StatusBadge, type StatusBadgeTone } from '../../components/settings'
import { actionToast, Button, Icons, Input, Label, LoadingState, Modal, Popover, Separator, Table, TextField } from '../../design-system'
import { HeroNotice } from './HeroAdminControls'

const recordOf = (value: unknown): Record<string, unknown> => value && typeof value === 'object' ? value as Record<string, unknown> : {}
const errorMessage = (caught: unknown, fallback: string) => caught instanceof ApiError
  ? caught.message
  : caught instanceof Error && caught.message
    ? caught.message
    : fallback

const storageOperationLabels: Record<StorageOperation, string> = {
  cleanup: '标准清理',
  archive: '转入冷归档',
  restore: '恢复归档',
  delete_archive: '永久删除归档',
}

function formatDateTime(value: string | null): string {
  if (!value) return '尚未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚未记录'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1)
  return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: index ? 1 : 0 }).format(value / (1024 ** index))} ${units[index]}`
}

function archiveStatusLabel(status: StorageArchive['status']): string {
  if (status === 'committed') return '已归档'
  if (status === 'restored') return '已恢复'
  if (status === 'deleted') return '已永久删除'
  return '失败'
}

function archiveStatusTone(status: StorageArchive['status']): StatusBadgeTone {
  if (status === 'committed') return 'accent'
  if (status === 'restored') return 'success'
  if (status === 'deleted') return 'neutral'
  return 'danger'
}

type ArchiveActionTarget = {
  archive: StorageArchive
  operation: 'restore' | 'delete_archive'
}

function ArchiveActions({
  archive,
  owner,
  pending,
  onRequest,
}: {
  archive: StorageArchive
  owner: boolean
  pending: boolean
  onRequest: (operation: 'restore' | 'delete_archive', archive: StorageArchive, trigger: HTMLButtonElement | null) => void
}) {
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const canRestore = archive.status === 'committed'
  const canDelete = archive.status === 'restored' && owner

  if (!canRestore && !canDelete) return null

  function choose(operation: 'restore' | 'delete_archive') {
    setOpen(false)
    onRequest(operation, archive, triggerRef.current)
  }

  return <Popover isOpen={open} onOpenChange={setOpen}>
    <Popover.Trigger<'button'>
      ref={triggerRef}
      aria-label={`更多操作：${archive.id}`}
      className="inline-flex size-8 items-center justify-center rounded-lg text-muted hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus pointer-coarse:size-11"
      render={(triggerProps) => <button {...triggerProps} type="button" disabled={pending} />}
    ><Icons.MoreHorizontal size={17} aria-hidden="true" /></Popover.Trigger>
    <Popover.Content placement="bottom end" offset={6} containerPadding={8} className="z-50 w-44 p-0">
      <Popover.Dialog aria-label={`${archive.id} 归档操作`} className="grid gap-0.5 p-2">
        {canRestore && <Button variant="ghost" className="w-full justify-start" onPress={() => choose('restore')}>
          <Icons.RotateCcw size={15} aria-hidden="true" />预演恢复
        </Button>}
        {canDelete && <>
          {canRestore && <Separator className="my-1" />}
          <Button variant="ghost" className="w-full justify-start text-danger" onPress={() => choose('delete_archive')}>
            <Icons.Trash2 size={15} aria-hidden="true" />预演永久删除
          </Button>
        </>}
      </Popover.Dialog>
    </Popover.Content>
  </Popover>
}

export function StorageArchiveSettings({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [activePlan, setActivePlan] = useState<StoragePlan | null>(null)
  const [confirmation, setConfirmation] = useState('')
  const [archiveActionTarget, setArchiveActionTarget] = useState<ArchiveActionTarget | null>(null)
  const archiveActionTriggerRef = useRef<HTMLButtonElement | null>(null)
  const summary = useQuery({
    queryKey: queryKeys.storageSummary(user.id),
    queryFn: ({ signal }) => api.storageSummary(signal),
    enabled: queryEnabled,
  })
  const archives = useQuery({
    queryKey: queryKeys.storageArchives(user.id),
    queryFn: ({ signal }) => api.storageArchives(signal),
    enabled: queryEnabled,
  })
  const preview = useMutation({
    mutationFn: ({ operation, payload = {} }: { operation: StorageOperation; payload?: Record<string, unknown> }) => api.createStoragePlan(operation, payload),
    onSuccess: (plan) => {
      setConfirmation('')
      setActivePlan(plan)
    },
  })
  const apply = useMutation({
    mutationFn: ({ plan, confirmationText }: { plan: StoragePlan; confirmationText: string }) => api.applyStoragePlan(plan.id, confirmationText),
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
  const cleanupCandidateCount = Object.values(previewCounts).reduce<number>((sum, value) => sum + Number(value || 0), 0)
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
    preview.mutate({ operation, payload: batchId ? { batch_id: batchId } : {} })
  }

  function closeArchiveActionDialog() {
    if (planPending) return
    setArchiveActionTarget(null)
    window.requestAnimationFrame(() => archiveActionTriggerRef.current?.focus())
  }

  function requestArchiveAction(operation: 'restore' | 'delete_archive', archive: StorageArchive, trigger: HTMLButtonElement | null) {
    if (planPending) return
    archiveActionTriggerRef.current = trigger
    setArchiveActionTarget({ operation, archive })
  }

  function confirmArchiveAction() {
    if (!archiveActionTarget) return
    previewPlan(archiveActionTarget.operation, archiveActionTarget.archive.id)
    setArchiveActionTarget(null)
    window.requestAnimationFrame(() => archiveActionTriggerRef.current?.focus())
  }

  return <div className="grid gap-7">
    <SettingsSection title="存储概览" description="工作区稳定内容、在线媒体与冷归档的当前占用。">
      {summary.isPending
        ? <LoadingState label="正在读取存储状态" rows={2} />
        : summary.isError
          ? <HeroNotice title="存储状态读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void summary.refetch()}>重试此区域</Button></HeroNotice>
          : summary.data && <>
            {!summary.data.readiness.ready && <HeroNotice title="迁移尚未完成" status="warning">必须先完成 Feed Storage v3 与时间索引 v11 的带备份迁移，之后才能生成清理或归档计划。</HeroNotice>}
            <div className="grid gap-3 min-[560px]:grid-cols-2 min-[920px]:grid-cols-4">
              <SettingsCard title="稳定内容" description={`共 ${summary.data.counts.content_total} 条 · 在线 ${summary.data.counts.content_online} · 冷归档 ${summary.data.counts.content_archived}`} icon={<Icons.Database size={17} aria-hidden="true" />} status={<StatusBadge>{summary.data.counts.content_total} 条</StatusBadge>} variant="inset" />
              <SettingsCard title="数据库" description={`Feed 快照 ${summary.data.counts.feed_snapshots} 份`} icon={<Icons.HardDrive size={17} aria-hidden="true" />} status={<StatusBadge>{formatBytes(summary.data.bytes.database)}</StatusBadge>} variant="inset" />
              <SettingsCard title="在线媒体" description={`${summary.data.counts.media_assets} 个可用资源`} icon={<Icons.Image size={17} aria-hidden="true" />} status={<StatusBadge>{formatBytes(summary.data.bytes.media)}</StatusBadge>} variant="inset" />
              <SettingsCard title="归档文件" description={`${summary.data.counts.archive_batches} 个冷归档批次`} icon={<Icons.Archive size={17} aria-hidden="true" />} status={<StatusBadge>{formatBytes(summary.data.bytes.archives)}</StatusBadge>} variant="inset" />
            </div>
          </>}
    </SettingsSection>

    <SettingsSection title="安全治理" description="所有治理操作先生成候选预演，执行前会重新核对指纹。">
      {summary.data && <SettingsGroup ariaLabel="存储安全治理">
        <SettingsItem
          label="清理与冷归档"
          description={`清理只处理轻量记录和孤立媒体；正文与媒体满 ${summary.data.policy.archive_after_days} 天后可转冷归档，永不自动永久删除。最近清理：${formatDateTime(summary.data.last_cleanup_at)}。`}
          icon={<Icons.ShieldCheck size={17} aria-hidden="true" />}
          trailing={<>
            <Button size="sm" variant="secondary" isDisabled={!summary.data.readiness.ready || planPending} onPress={() => previewPlan('cleanup')}><Icons.BrushCleaning size={15} aria-hidden="true" />预演标准清理</Button>
            <Button size="sm" variant="secondary" isDisabled={!summary.data.readiness.ready || planPending} onPress={() => previewPlan('archive')}><Icons.Archive size={15} aria-hidden="true" />预演 90 日归档</Button>
          </>}
        />
      </SettingsGroup>}

      {preview.isPending && <LoadingState label="正在计算候选项，不会修改数据" rows={1} />}
      {activePlan && activePlan.status === 'previewed' && <HeroNotice title={`${storageOperationLabels[activePlan.operation]}预演`} status={activePlan.operation === 'delete_archive' ? 'warning' : 'default'} role="status">
        <div className="grid gap-3">
          {activePlan.operation === 'cleanup' && <p>预计清理 {cleanupCandidateCount} 条轻量运行记录；稳定内容永久删除数为 0。</p>}
          {activePlan.operation === 'archive' && <p>预计归档 {Number(previewData.item_count ?? 0)} 条内容、{Number(previewData.media_count ?? 0)} 个媒体文件。收藏、稍后读和待通知内容已排除。</p>}
          {activePlan.operation === 'restore' && <p>将校验并恢复 {Number(previewData.item_count ?? 0)} 条内容、{Number(previewData.media_count ?? 0)} 个媒体文件。</p>}
          {activePlan.operation === 'delete_archive' && <><p>这是不可恢复的所有者操作。归档已先恢复到在线存储，预计释放 {formatBytes(Number(previewData.byte_size ?? 0))}。</p><TextField fullWidth value={confirmation} onChange={setConfirmation}><Label>输入确认文本</Label><Input placeholder={requiredConfirmation} /></TextField></>}
          <p className="type-meta text-muted">预演有效至 {formatDateTime(activePlan.expires_at)}；执行前会再次核对候选指纹。</p>
          <div className="flex flex-wrap gap-2"><Button size="sm" variant={activePlan.operation === 'delete_archive' ? 'danger' : 'primary'} isDisabled={!activePlanHasWork || planPending || (activePlan.operation === 'delete_archive' && confirmation !== requiredConfirmation)} onPress={() => apply.mutate({ plan: activePlan, confirmationText: confirmation })}>{!activePlanHasWork ? '无需执行' : apply.isPending ? '执行中…' : `执行${storageOperationLabels[activePlan.operation]}`}</Button><Button size="sm" variant="ghost" isDisabled={planPending} onPress={() => { setActivePlan(null); setConfirmation('') }}>取消</Button></div>
        </div>
      </HeroNotice>}
      {activePlan?.status === 'applied' && <HeroNotice title={`${storageOperationLabels[activePlan.operation]}已完成`} status="success">数据状态已刷新；完整结果已记录到审计计划。</HeroNotice>}
      {planError && <HeroNotice title="存储操作未完成" status="warning" role="alert">{planError}</HeroNotice>}
    </SettingsSection>

    <SettingsSection
      title="冷归档批次"
      description="管理员可预演恢复；只有所有者可在恢复完成后预演永久删除。"
      actions={<Button size="sm" variant="ghost" isDisabled={archives.isFetching} onPress={() => void archives.refetch()}><Icons.RefreshCw size={14} className={archives.isFetching ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />刷新</Button>}
    >
      <SettingsGroup ariaLabel="冷归档批次" className="p-0">
        {archives.isPending && <div className="p-4"><LoadingState label="正在读取归档批次" rows={2} /></div>}
        {archives.isError && <div className="p-4"><HeroNotice title="归档批次读取失败" status="warning" /></div>}
        {!archives.isPending && !archives.isError && !(archives.data?.archives.length) && <div className="p-4"><p className="type-meta text-muted">尚无归档批次。</p></div>}
        {!archives.isPending && !archives.isError && Boolean(archives.data?.archives.length) && <Table className="overflow-hidden bg-surface-secondary" variant="secondary">
          <Table.ScrollContainer className="max-w-full overflow-hidden">
            <Table.Content aria-label="冷归档批次" className="w-full table-fixed">
              <Table.Header className="bg-default/55">
                <Table.Column id="batch" isRowHeader className="h-11 px-3 type-meta text-muted min-[640px]:px-4">批次</Table.Column>
                <Table.Column id="status" className="h-11 w-20 px-2 type-meta text-muted min-[640px]:w-24">状态</Table.Column>
                <Table.Column id="details" className="hidden h-11 px-3 type-meta text-muted min-[640px]:table-cell">内容与体积</Table.Column>
                <Table.Column id="actions" className="h-11 w-12 px-2 text-right type-meta text-muted">操作</Table.Column>
              </Table.Header>
              <Table.Body>{(archives.data?.archives ?? []).map((archive) => <Table.Row key={archive.id} id={archive.id} className="border-b border-separator bg-surface-secondary transition-colors last:border-b-0 hover:bg-default/35">
                <Table.Cell className="px-3 py-3 align-top min-[640px]:px-4">
                  <p className="type-control break-all text-foreground">{archive.id}</p>
                  <p className="type-meta mt-1 text-muted min-[640px]:hidden">{archive.item_count} 条 · {archive.media_count} 个媒体 · {formatBytes(archive.byte_size)}</p>
                </Table.Cell>
                <Table.Cell className="px-2 py-3 align-top"><StatusBadge tone={archiveStatusTone(archive.status)}>{archiveStatusLabel(archive.status)}</StatusBadge></Table.Cell>
                <Table.Cell className="hidden px-3 py-3 align-top min-[640px]:table-cell"><p className="type-meta text-muted">{archive.item_count} 条内容 · {archive.media_count} 个媒体 · {formatBytes(archive.byte_size)}</p></Table.Cell>
                <Table.Cell className="px-2 py-2 text-right align-top"><ArchiveActions archive={archive} owner={user.role === 'owner'} pending={planPending} onRequest={requestArchiveAction} /></Table.Cell>
              </Table.Row>)}</Table.Body>
            </Table.Content>
          </Table.ScrollContainer>
        </Table>}
      </SettingsGroup>
    </SettingsSection>

    <Modal isOpen={Boolean(archiveActionTarget)} onOpenChange={(open) => !open && closeArchiveActionDialog()}>
      <Modal.Trigger aria-hidden="true" tabIndex={-1} className="sr-only">打开归档操作确认</Modal.Trigger>
      <Modal.Backdrop isDismissable={!planPending} isKeyboardDismissDisabled={planPending}>
        <Modal.Container size="sm">
          <Modal.Dialog>
            <Modal.Header><Modal.Heading>{archiveActionTarget?.operation === 'delete_archive' ? '预演永久删除' : '预演恢复归档'}</Modal.Heading></Modal.Header>
            <Modal.Body><p className="type-body text-muted">{archiveActionTarget?.operation === 'delete_archive'
              ? `将为 ${archiveActionTarget.archive.id} 生成永久删除预演。执行前仍需输入精确确认文本，且服务端会重新核对归档状态。`
              : `将为 ${archiveActionTarget?.archive.id ?? ''} 生成恢复预演；确认后不会立即修改数据。`}</p></Modal.Body>
            <Modal.Footer><Button variant="ghost" onPress={closeArchiveActionDialog}>取消</Button><Button variant={archiveActionTarget?.operation === 'delete_archive' ? 'danger' : 'primary'} onPress={confirmArchiveAction}>生成预演</Button></Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  </div>
}
