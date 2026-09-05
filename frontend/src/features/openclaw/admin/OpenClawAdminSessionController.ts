import type { OpenClawClientPort } from '../openclawContracts'
import { gatewaySupportsMethod, generateDeviceIdentity, GatewayRequestError, OPENCLAW_ADMIN_SCOPES, OpenClawGatewayClient, type GatewayHello, type OpenClawGatewayClientOptions } from '../openclawGateway'
import { OPENCLAW_ADMIN_METHODS, OpenClawWorkspaceError, type OpenClawAdminMethod } from '../workspace/openclawWorkspaceContracts'

const CLIENT_UPLOAD_LIMIT = 20 * 1024 * 1024
const UPLOAD_CHUNK_SIZE = 512 * 1024
const IDLE_TIMEOUT_MS = 10 * 60 * 1000
type UnknownRecord = Record<string, unknown>
export type OpenClawAdminSessionState = 'connecting' | 'authorized' | 'expired' | 'disconnected' | 'failed'
export type OpenClawAutomationSchedule = { kind: 'at'; at: string } | { kind: 'every'; everyMs: number } | { kind: 'cron'; expr: string; tz: string }
export type OpenClawAutomationDraft = { name: string; message: string; schedule: OpenClawAutomationSchedule }
export type OpenClawAutomation = OpenClawAutomationDraft & { id: string; enabled: boolean; nextRunAtMs?: number; lastRunAtMs?: number; lastRunStatus?: 'ok' | 'error' | 'skipped' }
export type OpenClawAutomationRun = { runId?: string; jobId: string; status?: 'ok' | 'error' | 'skipped'; completionStatus?: 'succeeded' | 'failed' | 'unknown'; summary?: string; error?: string; ts: number }

function recordOf(value: unknown, label: string): UnknownRecord { if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} 返回格式无效。`); return value as UnknownRecord }
function stringOf(value: unknown, maxLength = 4_096): string | undefined {
  if (typeof value !== 'string') return undefined
  const normalized = Array.from(value).filter((character) => { const code = character.charCodeAt(0); return (code > 31 && code !== 127) || code === 9 || code === 10 || code === 13 }).join('').trim()
  return normalized ? normalized.slice(0, maxLength) : undefined
}
function positiveNumber(value: unknown): number | undefined { return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : undefined }
function parseSchedule(value: unknown): OpenClawAutomationSchedule | null {
  const row = value && typeof value === 'object' ? value as UnknownRecord : null
  if (row?.kind === 'at' && stringOf(row.at)) return { kind: 'at', at: stringOf(row.at)! }
  if (row?.kind === 'every' && positiveNumber(row.everyMs)) return { kind: 'every', everyMs: positiveNumber(row.everyMs)! }
  if (row?.kind === 'cron' && stringOf(row.expr)) return { kind: 'cron', expr: stringOf(row.expr)!, tz: stringOf(row.tz) ?? 'UTC' }
  return null
}
function parseAutomation(value: unknown): OpenClawAutomation | null {
  const row = value && typeof value === 'object' ? value as UnknownRecord : null; const payload = row?.payload && typeof row.payload === 'object' ? row.payload as UnknownRecord : null; const state = row?.state && typeof row.state === 'object' ? row.state as UnknownRecord : null; const delivery = row?.delivery && typeof row.delivery === 'object' ? row.delivery as UnknownRecord : null
  const id = stringOf(row?.id); const name = stringOf(row?.name); const message = payload?.kind === 'agentTurn' ? stringOf(payload.message) : undefined; const schedule = parseSchedule(row?.schedule)
  if (!id || !name || !message || !schedule || row?.sessionTarget !== 'isolated' || delivery?.mode !== 'none') return null
  const lastRunStatus = state?.lastRunStatus
  return { id, name, message, schedule, enabled: row?.enabled === true, ...(positiveNumber(state?.nextRunAtMs) !== undefined ? { nextRunAtMs: positiveNumber(state?.nextRunAtMs) } : {}), ...(positiveNumber(state?.lastRunAtMs) !== undefined ? { lastRunAtMs: positiveNumber(state?.lastRunAtMs) } : {}), ...(lastRunStatus === 'ok' || lastRunStatus === 'error' || lastRunStatus === 'skipped' ? { lastRunStatus } : {}) }
}
function bytesToBase64(bytes: Uint8Array): string { let binary = ''; for (const byte of bytes) binary += String.fromCharCode(byte); return btoa(binary) }
async function sha256Hex(buffer: ArrayBuffer): Promise<string> { const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', buffer)); return Array.from(digest, (byte) => byte.toString(16).padStart(2, '0')).join('') }
function requireAcknowledgement(value: unknown, label: string): void { const row = recordOf(value, label); if (row.ok !== true && row.acknowledged !== true) throw new Error(`${label} 未返回有效回执。`) }

export class OpenClawAdminSessionController {
  private idleTimer: number | null = null
  private hello: GatewayHello | null = null
  private state: OpenClawAdminSessionState = 'connecting'
  private listeners = new Set<(state: OpenClawAdminSessionState) => void>()
  private constructor(private client: OpenClawClientPort) {}
  static async connect(input: { gatewayUrl: string; token: string; clientFactory?: (options: OpenClawGatewayClientOptions) => OpenClawClientPort }): Promise<OpenClawAdminSessionController> {
    const token = input.token.trim(); if (!token) throw new OpenClawWorkspaceError('forbidden', '需要 OpenClaw operator.admin 临时授权。')
    const identity = await generateDeviceIdentity(); const factory = input.clientFactory ?? ((options) => new OpenClawGatewayClient(options))
    const sessionRef: { current?: OpenClawAdminSessionController } = {}
    const client = factory({ url: input.gatewayUrl, bootstrapToken: token, deviceIdentity: identity, credentialClass: 'ephemeral-admin', requestedScopes: OPENCLAW_ADMIN_SCOPES, platform: navigator.platform || 'web', deviceFamily: 'browser-temporary-admin', onClose: () => sessionRef.current?.handleRemoteClose() })
    const session = new OpenClawAdminSessionController(client)
    sessionRef.current = session
    try {
      session.hello = await client.connect()
      session.transition('authorized')
      session.touch()
      return session
    } catch (error) {
      session.transition('failed')
      if (client.destroy) client.destroy()
      else client.close()
      throw error
    }
  }
  subscribe(listener: (state: OpenClawAdminSessionState) => void): () => void { this.listeners.add(listener); listener(this.state); return () => this.listeners.delete(listener) }
  capabilities(): Record<OpenClawAdminMethod, boolean> { return Object.fromEntries(OPENCLAW_ADMIN_METHODS.map((method) => [method, gatewaySupportsMethod(this.hello, method)])) as Record<OpenClawAdminMethod, boolean> }
  close(reason: OpenClawAdminSessionState = 'disconnected'): void { if (this.idleTimer !== null) window.clearTimeout(this.idleTimer); this.idleTimer = null; this.hello = null; if (this.client.destroy) this.client.destroy(); else this.client.close(); this.transition(reason) }
  private handleRemoteClose(): void { if (this.idleTimer !== null) window.clearTimeout(this.idleTimer); this.idleTimer = null; this.hello = null; if (this.client.destroy) this.client.destroy(); this.transition('disconnected') }
  private transition(state: OpenClawAdminSessionState): void { if (this.state === state) return; this.state = state; for (const listener of this.listeners) listener(state) }
  private touch(): void { if (this.idleTimer !== null) window.clearTimeout(this.idleTimer); this.idleTimer = window.setTimeout(() => this.close('expired'), IDLE_TIMEOUT_MS) }
  private async request<T>(method: OpenClawAdminMethod, params: Record<string, unknown>): Promise<T> {
    if (!this.hello) throw new OpenClawWorkspaceError('unavailable', '临时管理连接已关闭。')
    if (!gatewaySupportsMethod(this.hello, method)) throw new OpenClawWorkspaceError('unsupported', `当前 Gateway 不支持 ${method}。`)
    this.touch()
    try { return await this.client.request<T>(method, params) }
    catch (error) {
      const forbidden = error instanceof GatewayRequestError && (error.code === 'FORBIDDEN' || error.code === 'MISSING_SCOPE')
      throw new OpenClawWorkspaceError(forbidden ? 'forbidden' : 'failed', forbidden ? '当前临时管理权限不允许此操作。' : 'OpenClaw 暂时无法完成管理操作，请重试。')
    }
  }
  async uploadAndInstallSkill(input: { file: File; slug: string; force: boolean; gatewayLimit?: number; onProgress?: (completedBytes: number) => void }): Promise<void> {
    const slug = input.slug.trim(); if (!slug || !/^[a-z0-9][a-z0-9-]*$/u.test(slug)) throw new Error('Skill 标识只能使用小写字母、数字和连字符。')
    if (!input.file.name.toLowerCase().endsWith('.zip')) throw new Error('只允许上传 ZIP Skill。')
    const limit = Math.min(CLIENT_UPLOAD_LIMIT, input.gatewayLimit ?? CLIENT_UPLOAD_LIMIT); if (input.file.size <= 0 || input.file.size > limit) throw new Error(`ZIP 必须小于或等于 ${Math.floor(limit / 1024 / 1024)} MiB。`)
    const buffer = await input.file.arrayBuffer(); const sha256 = await sha256Hex(buffer)
    const begun = recordOf(await this.request('skills.upload.begin', { kind: 'skill-archive', slug, sizeBytes: input.file.size, sha256, force: input.force, idempotencyKey: crypto.randomUUID() }), 'skills.upload.begin'); const uploadId = stringOf(begun.uploadId)
    if (!uploadId) throw new Error('Gateway 没有返回上传标识。')
    for (let offset = 0; offset < buffer.byteLength; offset += UPLOAD_CHUNK_SIZE) {
      const chunk = new Uint8Array(buffer, offset, Math.min(UPLOAD_CHUNK_SIZE, buffer.byteLength - offset)); const response = recordOf(await this.request('skills.upload.chunk', { uploadId, offset, dataBase64: bytesToBase64(chunk) }), 'skills.upload.chunk'); const nextOffset = positiveNumber(response.nextOffset ?? response.offset)
      if (!Number.isInteger(nextOffset) || nextOffset !== offset + chunk.byteLength) throw new Error('Gateway 返回的上传 offset 不连续。'); input.onProgress?.(offset + chunk.byteLength)
    }
    requireAcknowledgement(await this.request('skills.upload.commit', { uploadId, sha256 }), 'skills.upload.commit')
    requireAcknowledgement(await this.request('skills.install', { source: 'upload', uploadId, slug, force: input.force, sha256 }), 'skills.install')
  }
  async updateSkillEnabled(skillKey: string, enabled: boolean): Promise<void> { requireAcknowledgement(await this.request('skills.update', { skillKey: skillKey.trim(), enabled }), 'skills.update') }
  async listAutomations(): Promise<OpenClawAutomation[]> { const root = recordOf(await this.request('cron.list', { includeDisabled: true, limit: 100, offset: 0, sortBy: 'updatedAtMs', sortDir: 'desc' }), 'cron.list'); if (!Array.isArray(root.jobs)) throw new Error('cron.list 返回格式无效。'); return root.jobs.flatMap((job) => parseAutomation(job) ?? []) }
  async getAutomation(id: string): Promise<OpenClawAutomation> { const root = recordOf(await this.request('cron.get', { id: id.trim() }), 'cron.get'); const projected = parseAutomation(root.job ?? root); if (!projected) throw new Error('cron.get 没有返回可验证的 Automation。'); return projected }
  async schedulerStatus(): Promise<{ enabled: boolean }> { const result = recordOf(await this.request('cron.status', {}), 'cron.status'); return { enabled: result.enabled === true } }
  async createAutomation(draft: OpenClawAutomationDraft): Promise<OpenClawAutomation> { const root = recordOf(await this.request('cron.add', { name: draft.name.trim(), enabled: false, schedule: draft.schedule, sessionTarget: 'isolated', wakeMode: 'now', payload: { kind: 'agentTurn', message: draft.message.trim() }, delivery: { mode: 'none' } }), 'cron.add'); const projected = parseAutomation(root.job ?? root); if (!projected) throw new Error('cron.add 没有返回可验证的 Automation。'); return projected }
  async updateAutomation(id: string, draft: OpenClawAutomationDraft): Promise<void> { await this.getAutomation(id); requireAcknowledgement(await this.request('cron.update', { id, patch: { name: draft.name.trim(), schedule: draft.schedule, payload: { kind: 'agentTurn', message: draft.message.trim() }, sessionTarget: 'isolated', delivery: { mode: 'none' } } }), 'cron.update') }
  async setAutomationEnabled(id: string, enabled: boolean): Promise<void> { await this.getAutomation(id); requireAcknowledgement(await this.request('cron.update', { id, patch: { enabled } }), 'cron.update') }
  async removeAutomation(id: string): Promise<void> { await this.getAutomation(id); requireAcknowledgement(await this.request('cron.remove', { id }), 'cron.remove') }
  async runAutomation(id: string): Promise<{ runId: string }> { await this.getAutomation(id); const result = recordOf(await this.request('cron.run', { id }), 'cron.run'); const runId = stringOf(result.runId); if (!runId) throw new Error('cron.run 未返回有效运行回执。'); return { runId } }
  async automationRuns(id: string): Promise<OpenClawAutomationRun[]> {
    const root = recordOf(await this.request('cron.runs', { scope: 'job', id, limit: 50, offset: 0, sortDir: 'desc' }), 'cron.runs'); const entries = Array.isArray(root.entries) ? root.entries : Array.isArray(root.runs) ? root.runs : []
    return entries.flatMap((value) => { const row = value && typeof value === 'object' ? value as UnknownRecord : null; const jobId = stringOf(row?.jobId); const ts = positiveNumber(row?.ts); if (!jobId || ts === undefined) return []; return [{ jobId, ts, ...(stringOf(row?.runId) ? { runId: stringOf(row?.runId) } : {}), ...(row?.status === 'ok' || row?.status === 'error' || row?.status === 'skipped' ? { status: row.status } : {}), ...(row?.completionStatus === 'succeeded' || row?.completionStatus === 'failed' || row?.completionStatus === 'unknown' ? { completionStatus: row.completionStatus } : {}), ...(stringOf(row?.summary, 2_000) ? { summary: stringOf(row?.summary, 2_000) } : {}), ...(stringOf(row?.error) ? { error: 'Gateway 报告 Automation 执行失败。' } : {}) }] })
  }
}
