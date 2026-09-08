export type OpenClawAutomationSchedule = { kind: 'at'; at: string } | { kind: 'every'; everyMs: number } | { kind: 'cron'; expr: string; tz: string }
export type OpenClawAutomationDraft = { agentId?: string; name: string; message: string; schedule: OpenClawAutomationSchedule }
export type OpenClawAutomation = OpenClawAutomationDraft & { id: string; enabled: boolean; nextRunAtMs?: number; lastRunAtMs?: number; lastRunStatus?: 'ok' | 'error' | 'skipped' }
export type OpenClawAutomationRun = { runId?: string; jobId: string; status?: 'ok' | 'error' | 'skipped'; completionStatus?: 'succeeded' | 'failed' | 'unknown'; summary?: string; error?: string; ts: number }
