import { useId, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'

import { Icons } from '../../design-system'
import type { ActorOpsV2OperationEvents } from '../../api/actorOpsV2Types'
import type { Job } from '../../api/types'

export function HeroSoftDisclosure({
  label,
  children,
  className = '',
  onOpenChange,
}: {
  label: string
  children: ReactNode
  className?: string
  onOpenChange?: (open: boolean) => void
}) {
  const [open, setOpen] = useState(false)
  const contentId = useId()

  return <div
    data-soft-disclosure={label}
    data-disclosure-state={open ? 'open' : 'closed'}
    className={`${open ? 'w-full basis-full' : 'w-auto'} min-w-0 rounded-lg transition-colors duration-200 ${className}`}
  >
    <button
      type="button"
      aria-expanded={open}
      aria-controls={contentId}
      className={`type-meta inline-flex min-h-7 items-center gap-1.5 rounded-lg px-2 transition-colors duration-200 hover:bg-default hover:text-foreground focus-visible:outline-2 focus-visible:outline-focus ${open ? 'bg-default text-foreground' : 'text-muted'}`}
      onClick={() => {
        const next = !open
        setOpen(next)
        onOpenChange?.(next)
      }}
    >
      <Icons.ChevronRight
        size={14}
        aria-hidden="true"
        className={`shrink-0 transition-transform duration-200 motion-reduce:transition-none ${open ? 'rotate-90' : ''}`}
      />
      {label}
    </button>
    <div
      id={contentId}
      aria-hidden={!open}
      className={`grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none ${open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'}`}
    >
      <div className="min-h-0 overflow-hidden">
        <div className="px-2 pb-2 pt-1">{children}</div>
      </div>
    </div>
  </div>
}

type ActorOpsTraceApi = {
  actorOpsV2Events: (params?: { job_id?: string; limit?: number }, signal?: AbortSignal) => Promise<ActorOpsV2OperationEvents>
}

export function HeroActorOpsTraceDisclosure({
  api, job, actorOps, fallback,
}: {
  api: ActorOpsTraceApi
  job: Job
  actorOps: boolean
  fallback: Record<string, unknown>
}) {
  const [open, setOpen] = useState(false)
  const trace = useQuery({
    queryKey: ['actorops-execution-trace', job.id],
    queryFn: ({ signal }) => api.actorOpsV2Events({ job_id: job.id, limit: 50 }, signal),
    enabled: open && actorOps,
    retry: false,
    refetchInterval: open && actorOps && ['queued', 'running'].includes(job.status) ? 3_000 : false,
  })
  return <HeroSoftDisclosure label={actorOps ? 'Actor 执行链路' : '技术详情'} onOpenChange={setOpen}>
    {!actorOps && <pre className="type-meta whitespace-pre-wrap [overflow-wrap:anywhere]">{JSON.stringify(fallback, null, 2)}</pre>}
    {actorOps && trace.isLoading && <p className="type-meta text-muted">正在读取安全执行链路…</p>}
    {actorOps && trace.isError && <p className="type-meta text-muted">执行链路暂不可用；任务结果不受影响。</p>}
    {actorOps && trace.data && <div className="grid gap-2">
      <p className="type-meta text-muted">链路记录：{trace.data.completeness === 'partial' ? '部分可用' : trace.data.completeness === 'not_recorded' ? '该历史任务未记录' : '完整'}。</p>
      {trace.data.events.map((event) => <p key={event.event_id} className="type-meta text-muted">{new Date(event.timestamp).toLocaleTimeString('zh-CN')} · {event.phase || event.action} · {event.outcome}{event.reason_code || event.error_code ? ` · ${event.reason_code || event.error_code}` : ''}</p>)}
      {!trace.data.events.length && <p className="type-meta text-muted">该任务尚无 Actor 执行链路。</p>}
    </div>}
  </HeroSoftDisclosure>
}
