import type { GatewayEvent } from '../openclawGateway'
import type {
  OpenClawRunActivity,
  OpenClawRunTrace,
  OpenClawSanitizedAgentEvent,
} from '../openclawContracts'
import { recordOf, stringOf } from './openclawProjectionUtils'

const MAX_RUN_ACTIVITIES = 20
const INTELISCOPE_TOOL_LABELS: Record<string, string> = {
  get_my_feed: '读取信息流',
  get_item: '读取文章详情',
  list_subscriptions: '查看订阅',
  source_health: '检查来源健康',
  list_jobs: '查找运行记录',
  get_job: '读取任务详情',
  get_source_setup_guide: '读取来源配置指引',
  search_bilibili_users: '查找 Bilibili 账号',
  resolve_source: '验证公开来源',
  web_search: '搜索公开网页',
  list_available_sources: '查找可用来源',
  diagnose_source: '诊断来源',
  diagnose_job: '诊断任务',
  query_operation_logs: '查询脱敏操作事件',
  prepare_create_subscription: '准备创建订阅',
  prepare_update_subscription: '准备更新订阅',
  prepare_delete_subscription: '准备删除订阅',
  apply_subscription_change: '应用订阅变更',
}

function safeAgentIdentifier(value: unknown, maxLength = 160): string | null {
  const candidate = stringOf(value)
  if (!candidate || candidate.length > maxLength || !/^[a-zA-Z0-9_.:/-]+$/u.test(candidate)) return null
  return candidate
}

function projectToolLabel(value: unknown): { key: string | null; label: string } {
  const identifier = safeAgentIdentifier(value, 200)?.toLocaleLowerCase() ?? null
  if (!identifier) return { key: null, label: '使用工具' }
  for (const [key, label] of Object.entries(INTELISCOPE_TOOL_LABELS)) {
    if (
      identifier === key
      || identifier.endsWith(`__${key}`)
      || identifier.endsWith(`.${key}`)
      || identifier.endsWith(`/${key}`)
      || identifier.endsWith(`:${key}`)
    ) return { key, label }
  }
  return { key: null, label: '使用工具' }
}

export function projectOpenClawAgentEvent(
  event: GatewayEvent,
  expectedSessionKey: string,
): OpenClawSanitizedAgentEvent | null {
  if (event.event !== 'agent') return null
  const payload = recordOf(event.payload)
  if (!payload || stringOf(payload.sessionKey) !== expectedSessionKey) return null
  const runId = safeAgentIdentifier(payload.runId)
  const stream = safeAgentIdentifier(payload.stream, 48)?.toLocaleLowerCase()
  const seqCandidate = payload.seq ?? event.seq
  const seq = typeof seqCandidate === 'number' && Number.isFinite(seqCandidate) && seqCandidate >= 0
    ? Math.floor(seqCandidate)
    : null
  if (!runId || !stream || seq === null) return null
  const data = recordOf(payload.data) ?? {}
  const phase = safeAgentIdentifier(data.phase ?? data.state, 32)?.toLocaleLowerCase() ?? null
  const tool = stream === 'tool' ? projectToolLabel(data.name) : { key: null, label: '' }
  const timestamp = typeof payload.ts === 'number' && Number.isFinite(payload.ts) && payload.ts > 0
    ? payload.ts
    : Date.now()
  const status = safeAgentIdentifier(data.status, 32)?.toLocaleLowerCase()
  return {
    runId,
    seq,
    stream,
    phase,
    timestamp,
    toolCallId: safeAgentIdentifier(data.toolCallId ?? data.callId),
    toolKey: tool.key,
    toolLabel: stream === 'tool' ? tool.label : null,
    failed: data.isError === true || status === 'error' || status === 'failed' || phase === 'error',
  }
}

function mergeRunActivity(
  activities: OpenClawRunActivity[],
  event: OpenClawSanitizedAgentEvent,
): OpenClawRunActivity[] {
  const terminal = event.phase === 'result' || event.phase === 'end' || event.phase === 'done' || event.failed
  const status: OpenClawRunActivity['status'] = event.failed ? 'failed' : terminal ? 'completed' : 'running'
  const id = event.toolCallId
    ?? [...activities].reverse().find((activity) => activity.status === 'running' && activity.id.startsWith(`tool:${event.toolKey ?? 'unknown'}:`))?.id
    ?? `tool:${event.toolKey ?? 'unknown'}:${event.seq}`
  const existingIndex = activities.findIndex((activity) => activity.id === id)
  const next = activities.map((activity) => ({ ...activity }))
  const activity: OpenClawRunActivity = {
    id,
    label: event.toolLabel ?? '使用工具',
    status,
    startedAt: existingIndex >= 0 ? next[existingIndex].startedAt : event.timestamp,
    ...(terminal ? { endedAt: event.timestamp } : {}),
  }
  if (existingIndex >= 0) next[existingIndex] = activity
  else next.push(activity)
  return next.slice(-MAX_RUN_ACTIVITIES)
}

export function applyAgentEventToTrace(
  trace: OpenClawRunTrace | null,
  event: OpenClawSanitizedAgentEvent,
): OpenClawRunTrace {
  const current: OpenClawRunTrace = trace ?? {
    runId: event.runId,
    phase: 'waiting',
    status: 'running',
    startedAt: event.timestamp,
    activities: [],
  }
  if (event.stream === 'tool') {
    return {
      ...current,
      runId: event.runId,
      phase: 'using_tool',
      status: 'running',
      activities: mergeRunActivity(current.activities, event),
    }
  }
  if (event.stream === 'thinking' || event.stream === 'plan') {
    return { ...current, runId: event.runId, phase: 'thinking', status: 'running' }
  }
  if (event.stream === 'assistant') {
    return { ...current, runId: event.runId, phase: 'composing', status: 'running' }
  }
  if (event.stream === 'lifecycle') {
    if (event.failed || event.phase === 'error') {
      return { ...current, runId: event.runId, phase: 'failed', status: 'failed', endedAt: event.timestamp }
    }
    if (event.phase === 'end' || event.phase === 'done') {
      return { ...current, runId: event.runId, phase: 'composing', status: 'running' }
    }
    return { ...current, runId: event.runId, phase: 'thinking', status: 'running' }
  }
  if (event.stream === 'error') {
    return { ...current, runId: event.runId, phase: 'failed', status: 'failed', endedAt: event.timestamp }
  }
  return { ...current, runId: event.runId, phase: 'waiting', status: 'running' }
}
