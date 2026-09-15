import { useEffect, useState } from 'react'

import { Icons, StatusIndicator } from '../../../design-system'
import type { OpenClawRunActivity, OpenClawRunPhase, OpenClawRunTrace } from '../openclawContracts'

const runPhaseLabels: Record<OpenClawRunPhase, string> = {
  sending: '正在发送请求',
  waiting: '等待 OpenClaw 响应',
  thinking: '正在思考',
  using_tool: '正在使用工具',
  composing: '正在整理回答',
  streaming: '正在生成回答',
  stopping: '正在停止',
  completed: '处理完成',
  aborted: '已停止',
  failed: '处理失败',
}

const QUICK_ACTIVITY_THRESHOLD_MS = 400

function activityStatusLabel(activity: OpenClawRunActivity): string {
  if (activity.status === 'running') return '进行中'
  if (activity.status === 'failed') return '失败'
  if (activity.status === 'stopped') return '已停止'
  return activity.endedAt === undefined ? '结果未确认' : '已完成'
}

function activityDuration(activity: OpenClawRunActivity, now: number): string {
  const end = activity.endedAt ?? (activity.status === 'running' ? now : undefined)
  if (end === undefined) return '耗时未知'
  const milliseconds = Math.max(0, end - activity.startedAt)
  if (milliseconds < 1_000) return `${Math.max(0.1, Math.round(milliseconds / 100) / 10).toFixed(1)}秒`
  const seconds = Math.round(milliseconds / 100) / 10
  return `${seconds}秒`
}

function ActivityIcon({ activity }: { activity: OpenClawRunActivity }) {
  if (activity.status === 'running') return <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
  if (activity.status === 'failed') return <Icons.CircleX size={13} aria-hidden="true" />
  if (activity.status === 'stopped') return <Icons.Square size={11} aria-hidden="true" />
  return <Icons.Check size={13} aria-hidden="true" />
}

export function OpenClawActivityTrace({ trace, running }: {
  trace: OpenClawRunTrace
  running: boolean
}) {
  const [expandedOverride, setExpandedOverride] = useState<boolean | null>(null)
  const [now, setNow] = useState(trace.startedAt)
  const expanded = expandedOverride ?? running

  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => setNow(Date.now()), 400)
    return () => window.clearInterval(timer)
  }, [running])

  const endedAt = trace.endedAt ?? now
  const elapsedSeconds = Math.max(0, Math.floor((endedAt - trace.startedAt) / 1000))
  const activeTool = [...trace.activities].reverse().find((activity) => activity.status === 'running')
  const activeToolVisible = Boolean(activeTool && now - activeTool.startedAt >= QUICK_ACTIVITY_THRESHOLD_MS)
  const phaseLabel = trace.phase === 'using_tool' && activeTool && activeToolVisible
    ? `正在${activeTool.label}`
    : runPhaseLabels[trace.phase]
  const activityCount = trace.activitiesTruncated ? `至少 ${trace.activities.length}` : `${trace.activities.length}`
  const summary = trace.status === 'completed'
    ? `已完成 ${activityCount} 个步骤`
    : trace.status === 'aborted'
      ? trace.activities.length ? `已停止 · 完成 ${trace.activities.filter((activity) => activity.status === 'completed').length} 个步骤` : '已停止，未生成回答'
      : trace.status === 'failed'
        ? '处理失败'
        : phaseLabel
  const visibleActivities = trace.activities.filter((activity) => {
    if (!running) return true
    if (activity.id === 'context') return true
    if (activity.status === 'running') return now - activity.startedAt >= QUICK_ACTIVITY_THRESHOLD_MS
    if (activity.status !== 'completed' || activity.endedAt === undefined) return true
    return activity.endedAt - activity.startedAt >= QUICK_ACTIVITY_THRESHOLD_MS
  })
  const tone = trace.status === 'failed' ? 'danger' : trace.status === 'aborted' ? 'neutral' : running ? 'accent' : 'success'

  return <div data-openclaw-activity data-run-status={trace.status} className="mt-2 min-w-0 rounded-xl border border-separator bg-default/45 px-2.5 py-2">
    <button
      type="button"
      className="flex min-h-7 w-full min-w-0 items-center gap-2 rounded-lg text-left focus-visible:outline-2 focus-visible:outline-focus"
      aria-expanded={expanded}
      onClick={() => setExpandedOverride(!expanded)}
    >
      <StatusIndicator
        label={summary}
        tone={tone}
        icon={running
          ? <Icons.LoaderCircle size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          : trace.status === 'failed'
            ? <Icons.CircleX size={13} aria-hidden="true" />
            : trace.status === 'aborted'
              ? <Icons.Square size={11} aria-hidden="true" />
              : <Icons.Check size={13} aria-hidden="true" />}
        className="min-w-0 flex-1"
      />
      <span aria-hidden="true" aria-live="off" className="type-meta shrink-0 tabular-nums text-muted">{elapsedSeconds}秒</span>
      <Icons.ChevronDown size={13} aria-hidden="true" className={`shrink-0 text-muted transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
    </button>
    <span className="sr-only" role="status">{phaseLabel}</span>
    {expanded && <div className="quiet-scroll-region mt-1 grid max-h-40 gap-1 overflow-y-auto border-t border-separator pt-1.5">
      {trace.activitiesTruncated && <span className="type-meta pl-5 text-muted">仅显示最近 20 个步骤</span>}
      {visibleActivities.length ? visibleActivities.map((activity) => <div
        key={activity.id}
        data-activity-status={activity.status}
        className={`type-meta flex min-w-0 items-center gap-2 ${activity.status === 'failed' ? 'text-danger' : activity.status === 'running' ? 'text-accent' : 'text-muted'}`}
      >
        <span className="grid size-3.5 shrink-0 place-items-center"><ActivityIcon activity={activity} /></span>
        <span className="min-w-0 break-words [overflow-wrap:anywhere]">{activity.label}</span>
        <span className="shrink-0">· {activityStatusLabel(activity)} · {activityDuration(activity, now)}</span>
      </div>) : <span className="type-meta text-muted">未收到详细步骤</span>}
    </div>}
  </div>
}
