import type { OpenClawAutomation, OpenClawAutomationRun, OpenClawAutomationSchedule } from './automationTypes'

export type AutomationPage<T> = { items: T[]; nextOffset: number | null }
type Row = Record<string, unknown>
function rowOf(value: unknown): Row | null { return value && typeof value === 'object' && !Array.isArray(value) ? value as Row : null }
function text(value: unknown): string | undefined { return typeof value === 'string' && value.trim() ? value : undefined }
function number(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined }

function scheduleOf(value: unknown): OpenClawAutomationSchedule | null {
  const row = rowOf(value)
  if (row?.kind === 'at' && text(row.at)) return { kind: 'at', at: row.at as string }
  if (row?.kind === 'every' && number(row.everyMs)) return { kind: 'every', everyMs: row.everyMs as number }
  if (row?.kind === 'cron' && text(row.expr)) return { kind: 'cron', expr: row.expr as string, tz: text(row.tz) || 'UTC' }
  return null
}

export function parseAutomation(value: unknown): OpenClawAutomation | null {
  const row = rowOf(value), payload = rowOf(row?.payload), state = rowOf(row?.state), delivery = rowOf(row?.delivery)
  const id = text(row?.id), name = text(row?.name), message = payload?.kind === 'agentTurn' ? text(payload.message) : undefined
  const schedule = scheduleOf(row?.schedule)
  if (!id || !name || message === undefined || !schedule || row?.sessionTarget !== 'isolated' || delivery?.mode !== 'none') return null
  if (message.length > 400000) throw new Error('此提示词超过编辑器支持范围，已停止加载以免截断保存。')
  return { id, name, message, schedule, enabled: row.enabled === true,
    ...(text(row.agentId) ? { agentId: text(row.agentId) } : {}),
    ...(number(state?.nextRunAtMs) !== undefined ? { nextRunAtMs: number(state?.nextRunAtMs) } : {}),
    ...(number(state?.lastRunAtMs) !== undefined ? { lastRunAtMs: number(state?.lastRunAtMs) } : {}),
    ...(['ok', 'error', 'skipped'].includes(String(state?.lastRunStatus)) ? { lastRunStatus: state!.lastRunStatus as 'ok' | 'error' | 'skipped' } : {}) }
}

export function nextOffset(root: Row, offset: number, count: number): number | null {
  if (root.hasMore === false) return null
  if (root.hasMore !== true && (root.nextOffset === undefined || root.nextOffset === null)) return null
  if (!Number.isSafeInteger(root.nextOffset) || Number(root.nextOffset) <= offset || Number(root.nextOffset) > offset + count) {
    throw new Error('Gateway 分页游标无效，请刷新重试。')
  }
  return Number(root.nextOffset)
}

export function parseRunPage(value: unknown, id: string, offset: number): AutomationPage<OpenClawAutomationRun> {
  const root = rowOf(value)
  const entries = root && (Array.isArray(root.entries) ? root.entries : Array.isArray(root.runs) ? root.runs : null)
  if (!root || !entries) throw new Error('cron.runs 返回格式无效。')
  const items: OpenClawAutomationRun[] = entries.flatMap((value) => {
    const row = rowOf(value), jobId = text(row?.jobId), ts = number(row?.ts)
    if (!row || jobId !== id || ts === undefined) return []
    return [{ jobId, ts, ...(text(row.runId) ? { runId: text(row.runId) } : {}),
      ...(['ok', 'error', 'skipped'].includes(String(row.status)) ? { status: row.status as 'ok' | 'error' | 'skipped' } : {}),
      ...(['succeeded', 'failed', 'unknown'].includes(String(row.completionStatus)) ? { completionStatus: row.completionStatus as 'succeeded' | 'failed' | 'unknown' } : {}),
      ...(text(row.summary) ? { summary: text(row.summary)!.slice(0, 2000) } : {}), ...(row.error ? { error: 'Gateway 报告 Automation 执行失败。' } : {}) }]
  })
  return { items, nextOffset: nextOffset(root, offset, entries.length) }
}
