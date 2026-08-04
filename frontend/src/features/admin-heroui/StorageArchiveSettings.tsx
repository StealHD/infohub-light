import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '../../api/client'
import { queryKeys } from '../../api/queryKeys'
import type { StorageOperation, StoragePlan } from '../../api/types'
import { useAppContext } from '../../app/AppContext'
import { actionToast, Button, Card, Icons, Input, Label, LoadingState, TextField } from '../../design-system'
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

export function StorageArchiveSettings({ queryEnabled }: { queryEnabled: boolean }) {
  const { api, user } = useAppContext()
  const queryClient = useQueryClient()
  const [activePlan, setActivePlan] = useState<StoragePlan | null>(null)
  const [confirmation, setConfirmation] = useState('')
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

  return <div className="grid gap-4">
    {summary.isPending
      ? <LoadingState label="正在读取存储状态" rows={2} />
      : summary.isError
        ? <HeroNotice title="存储状态读取失败" status="warning"><Button size="sm" variant="ghost" onPress={() => void summary.refetch()}>重试此区域</Button></HeroNotice>
        : summary.data && <>
          {!summary.data.readiness.ready && <HeroNotice title="迁移尚未完成" status="warning">必须先完成 Feed Storage v3 与时间索引 v11 的带备份迁移，之后才能生成清理或归档计划。</HeroNotice>}
          <div className="grid gap-3 min-[560px]:grid-cols-2 min-[920px]:grid-cols-4">
            <Card variant="secondary" className="p-4"><Card.Description>稳定内容</Card.Description><Card.Title className="mt-1">{summary.data.counts.content_total} 条</Card.Title><p className="type-meta mt-1 text-muted">在线 {summary.data.counts.content_online} · 冷归档 {summary.data.counts.content_archived}</p></Card>
            <Card variant="secondary" className="p-4"><Card.Description>数据库</Card.Description><Card.Title className="mt-1">{formatBytes(summary.data.bytes.database)}</Card.Title><p className="type-meta mt-1 text-muted">Feed 快照 {summary.data.counts.feed_snapshots}</p></Card>
            <Card variant="secondary" className="p-4"><Card.Description>在线媒体</Card.Description><Card.Title className="mt-1">{formatBytes(summary.data.bytes.media)}</Card.Title><p className="type-meta mt-1 text-muted">{summary.data.counts.media_assets} 个资源</p></Card>
            <Card variant="secondary" className="p-4"><Card.Description>归档文件</Card.Description><Card.Title className="mt-1">{formatBytes(summary.data.bytes.archives)}</Card.Title><p className="type-meta mt-1 text-muted">{summary.data.counts.archive_batches} 个批次</p></Card>
          </div>
          <Card variant="transparent" className="p-4">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1"><Card.Title>安全治理</Card.Title><Card.Description className="mt-1">清理只处理紧凑快照、完成任务、缓存、使用记录和孤立媒体；正文与媒体满 {summary.data.policy.archive_after_days} 天后可转冷归档，永不自动永久删除。</Card.Description><p className="type-meta mt-2 text-muted">最近清理：{formatDateTime(summary.data.last_cleanup_at)}</p></div>
              <div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" isDisabled={!summary.data.readiness.ready || planPending} onPress={() => previewPlan('cleanup')}><Icons.BrushCleaning size={15} aria-hidden="true" />预演标准清理</Button><Button size="sm" variant="secondary" isDisabled={!summary.data.readiness.ready || planPending} onPress={() => previewPlan('archive')}><Icons.Archive size={15} aria-hidden="true" />预演 90 日归档</Button></div>
            </div>
          </Card>
        </>}

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

    <Card variant="transparent" className="p-4">
      <div className="flex flex-wrap items-center gap-3"><div className="min-w-0 flex-1"><Card.Title>冷归档批次</Card.Title><Card.Description className="mt-1">管理员可预演恢复；只有所有者可在恢复完成后预演永久删除。</Card.Description></div><Button size="sm" variant="ghost" isDisabled={archives.isFetching} onPress={() => void archives.refetch()}><Icons.RefreshCw size={14} className={archives.isFetching ? 'animate-spin motion-reduce:animate-none' : ''} aria-hidden="true" />刷新</Button></div>
      {archives.isPending && <div className="mt-4"><LoadingState label="正在读取归档批次" rows={2} /></div>}
      {archives.isError && <div className="mt-4"><HeroNotice title="归档批次读取失败" status="warning" /></div>}
      {!archives.isPending && !archives.isError && !(archives.data?.archives.length) && <p className="type-meta mt-4 text-muted">尚无归档批次。</p>}
      <div className="mt-4 grid gap-2">
        {(archives.data?.archives ?? []).map((archive) => <div key={archive.id} className="flex flex-wrap items-center gap-3 rounded-xl border border-separator bg-surface-secondary p-3">
          <div className="min-w-0 flex-1"><p className="type-control break-all">{archive.id}</p><p className="type-meta mt-1 text-muted">{archive.item_count} 条 · {archive.media_count} 个媒体 · {formatBytes(archive.byte_size)} · {archive.status === 'committed' ? '已归档' : archive.status === 'restored' ? '已恢复' : archive.status === 'deleted' ? '已永久删除' : '失败'}</p></div>
          {archive.status === 'committed' && <Button size="sm" variant="secondary" isDisabled={planPending} onPress={() => previewPlan('restore', archive.id)}><Icons.RotateCcw size={14} aria-hidden="true" />预演恢复</Button>}
          {archive.status === 'restored' && user.role === 'owner' && <Button size="sm" variant="danger" isDisabled={planPending} onPress={() => previewPlan('delete_archive', archive.id)}><Icons.Trash2 size={14} aria-hidden="true" />预演永久删除</Button>}
        </div>)}
      </div>
    </Card>
  </div>
}
