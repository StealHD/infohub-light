import type { OpenClawAutomationDraft, OpenClawAutomationSchedule } from '../openclaw/admin/OpenClawAdminSessionController'

export type AutomationFormValues = {
  name: string
  message: string
  scheduleKind: OpenClawAutomationSchedule['kind']
  at: string
  everyMinutes: string
  cronExpr: string
  timezone: string
}

export type AutomationFormResult = {
  draft: OpenClawAutomationDraft | null
  errors: Partial<Record<keyof AutomationFormValues, string>>
}

export function automationLocalTime(value: string): string {
  const date = new Date(value)
  if (!Number.isFinite(date.getTime())) return ''
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function validTimezone(value: string): boolean {
  try {
    new Intl.DateTimeFormat('en', { timeZone: value }).format()
    return true
  } catch {
    return false
  }
}

export function projectAutomationDraft(values: AutomationFormValues, now = Date.now()): AutomationFormResult {
  const errors: AutomationFormResult['errors'] = {}
  const name = values.name.trim()
  const message = values.message
  if (!name) errors.name = '请输入名称。'
  if (!message.trim()) errors.message = '请输入 Agent 提示词。'
  if (message.length > 400000) errors.message = '提示词不能超过 400000 字符，不会自动截断。'
  let schedule: OpenClawAutomationSchedule | null = null

  if (values.scheduleKind === 'at') {
    const parsed = Date.parse(values.at)
    if (!Number.isFinite(parsed) || parsed <= now) errors.at = '执行时间必须是未来的有效时间。'
    else schedule = { kind: 'at', at: new Date(parsed).toISOString() }
  } else if (values.scheduleKind === 'every') {
    const minutes = Number(values.everyMinutes)
    const everyMs = minutes * 60_000
    if (!Number.isFinite(everyMs) || everyMs <= 0 || !Number.isSafeInteger(everyMs)) errors.everyMinutes = '请输入可安全换算的正数分钟。'
    else schedule = { kind: 'every', everyMs }
  } else {
    const expr = values.cronExpr.trim()
    const timezone = values.timezone.trim()
    if (!expr || expr.length > 200 || expr.split(/\s+/u).length < 5) errors.cronExpr = '请输入不超过 200 字符的 Cron 表达式。'
    if (!timezone || !validTimezone(timezone)) errors.timezone = '请输入有效的 IANA 时区。'
    if (!errors.cronExpr && !errors.timezone) schedule = { kind: 'cron', expr, tz: timezone }
  }

  return {
    draft: name && message && schedule && !Object.keys(errors).length ? { name, message, schedule } : null,
    errors,
  }
}
