import type { Page, Route } from '@playwright/test'

function jsonBody(data: unknown) { return { contentType: 'application/json', body: JSON.stringify({ ok: true, data }) } }
export async function installAgentApi(page: Page, enabled = false) {
  await page.addInitScript(() => window.sessionStorage.setItem('inteliscope.ui.insights-dismissed.v1:e2e-agent', '1'))
  await page.route((url) => url.pathname.startsWith('/api/'), async (route: Route) => {
    const url = new URL(route.request().url())
    if (url.pathname === '/api/auth/status') return route.fulfill(jsonBody({ authenticated: true, user: { id: 'e2e-agent', username: 'agent', display_name: 'Agent 验收', role: 'member', enabled: true } }))
    if (url.pathname === '/api/me/agent-delegations') return route.fulfill(jsonBody({ enabled: true, mcp_url: '/mcp', subscription_writes_enabled: false, openclaw_chat: { enabled, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4, target_version: '2026.8.1' }, token_ttl_days: 90, max_active: 5, connections: [] }))
    if (url.pathname === '/api/feed/latest') return route.fulfill(jsonBody({ schema_version: 2, items: [] }))
    if (url.pathname === '/api/catalog/sources') return route.fulfill(jsonBody({ sources: [] }))
    if (url.pathname === '/api/me/source-health') return route.fulfill(jsonBody({ summary: { total: 0, healthy: 0, attention: 0, failing: 0, untested: 0 }, items: [] }))
    if (url.pathname === '/api/jobs') return route.fulfill(jsonBody({ jobs: [] }))
    return route.fulfill({ status: 404, ...jsonBody(null) })
  })
}

export async function installGatewayFixture(page: Page, directory = false) {
  await page.addInitScript((directory) => {
    const requests: Array<{ method: string; params: Record<string, unknown> }> = []
    let title = ''
    const history = Array.from({ length: 205 }, (_, index) => ({ key: `agent:research:dashboard:${index}`, agentId: 'research', displayName: `历史记录 ${String(index).padStart(3, '0')}`, updatedAt: 1000 - index, archived: false, hasActiveRun: false }))
    history.push({ key: 'agent:research:dashboard:archived', agentId: 'research', displayName: '归档记录', updatedAt: 1001, archived: true, hasActiveRun: false })
    let skillEnabled = false
    let createdWorktree = false
    let taskCancelled = false
    const automation = { agentId: 'main', id: 'cron-1', name: '每天阅读摘要', enabled: false, schedule: { kind: 'every', everyMs: 3600000 }, sessionTarget: 'isolated', payload: { kind: 'agentTurn', message: '整理今日阅读要点' }, delivery: { mode: 'none' } }
    ;(window as unknown as { __gatewayRequests: typeof requests }).__gatewayRequests = requests
    class FixtureWebSocket {
      readyState = 1
      private listeners = new Map<string, Array<(event: unknown) => void>>()
      constructor() {
        ;(window as unknown as { __renameSession: () => void }).__renameSession = () => { title = '整理我的订阅'; this.emit('message', { data: JSON.stringify({ type: 'event', event: 'sessions.changed', payload: { sessionKey: 'root' } }) }) }
        window.setTimeout(() => {
          this.emit('open', {})
          this.emit('message', { data: JSON.stringify({ type: 'event', event: 'connect.challenge', payload: { nonce: 'fixture-nonce' } }) })
        }, 0)
      }
      addEventListener(type: string, listener: (event: unknown) => void) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]) }
      private emit(type: string, event: unknown) { for (const listener of this.listeners.get(type) ?? []) listener(event) }
      send(raw: string) {
        const frame = JSON.parse(raw) as { id: string; method: string; params: Record<string, unknown> }
        if (typeof frame.method !== 'string') return // Ignore Vite HMR ping frames, not Gateway RPCs.
        requests.push({ method: frame.method, params: frame.params })
        if (frame.method === 'chat.history' && (window as unknown as { __failHistory?: boolean }).__failHistory) { window.setTimeout(() => this.emit('message', { data: JSON.stringify({ type: 'res', id: frame.id, ok: false, error: { code: 'UNAVAILABLE', message: 'fixture history failure' } }) }), 0); return }
        const held = window as unknown as { __holdHistory?: boolean; __releaseHistory?: () => void }
        if (frame.method === 'chat.history' && held.__holdHistory) { held.__releaseHistory = () => this.emit('message', { data: JSON.stringify({ type: 'res', id: frame.id, ok: true, payload: { messages: [] } }) }); return }
        const methods = [
          'projects.list', 'sessions.create', 'sessions.list', 'sessions.preview', 'sessions.delete', 'sessions.send', 'worktrees.branches',
          'tasks.list', 'tasks.get', 'tasks.cancel', 'artifacts.list', 'artifacts.get', 'artifacts.download', 'skills.status',
          'skills.update', 'cron.list', 'cron.get', 'cron.status', 'cron.add', 'cron.update', 'cron.run', 'cron.runs', 'cron.remove',
        ]
        let payload: unknown = { ok: true }
        if (frame.method === 'connect') payload = { protocol: 4, auth: { role: 'operator', scopes: frame.params.scopes ?? ['operator.read', 'operator.write'], deviceToken: 'fixture-device-token' }, snapshot: { sessionDefaults: { defaultAgentId: 'main' } }, features: { methods } }
        else if (frame.method === 'sessions.create') {
          if (frame.params.worktree) createdWorktree = true
          payload = frame.params.worktree ? { ok: true, key: 'child', runStarted: true, runId: 'run-1', worktree: { id: 'wt-1', path: '/tmp/wt-1', branch: 'openclaw/ui' } } : { key: 'root' }
        }
        else if (frame.method === 'sessions.delete') {
          const index = history.findIndex((row) => row.key === frame.params.key)
          if (index >= 0) history.splice(index, 1)
          payload = { ok: true, deleted: index >= 0, key: frame.params.key }
        }
        else if (frame.method === 'models.list') payload = { models: [{ id: 'gpt', provider: 'openai', name: 'GPT', available: true, input: ['text'] }] }
        else if (frame.method === 'agents.list') payload = { defaultId: 'main', agents: ['main', 'research'].map((id) => ({ id, model: { primary: 'openai/gpt' } })) }
        else if (frame.method === 'sessions.describe') payload = { session: { key: frame.params.key, agentId: history.find((row) => row.key === frame.params.key)?.agentId ?? 'main', modelProvider: 'openai', model: 'gpt' } }
        else if (frame.method === 'tools.effective') payload = { groups: [{ tools: [{ id: 'inteliscope', source: 'mcp' }] }] }
        else if (frame.method === 'chat.history') payload = { messages: [] }
        else if (frame.method === 'sessions.list') {
          const root = { key: 'root', displayName: title || (window as unknown as { __sessionLabel?: string }).__sessionLabel || 'Inscope · 127.0.0.1:8080 · 384f86ea20d2477f', agentId: 'main', updatedAt: 2000, archived: false, hasActiveRun: false, totalTokens: 10, contextTokens: 100 }
          const rows = directory ? [root, ...history] : [root, ...(createdWorktree ? [{ key: 'child', parentSessionKey: 'root', displayName: '登录校验测试', hasActiveRun: true, archived: false }] : [])]
          const filtered = rows.filter((row) => (frame.params.archived === undefined || frame.params.archived === 'all' || ('archived' in row && row.archived === frame.params.archived)) && (!frame.params.search || `${row.key} ${row.displayName}`.includes(String(frame.params.search))))
          const offset = Number(frame.params.offset ?? 0); const limit = Number(frame.params.limit ?? 50)
          const sessions = filtered.slice(offset, offset + limit); const hasMore = offset + limit < filtered.length
          payload = { sessions, hasMore, totalCount: filtered.length, ...(hasMore ? { nextOffset: offset + limit } : {}) }
        }
        else if (frame.method === 'sessions.preview') payload = { previews: [{ key: (frame.params.keys as string[])[0], status: 'empty', items: [] }] }
        else if (frame.method === 'projects.list') payload = { projects: [{ id: 'infohub', displayName: 'InfoHub', repoRoot: '/repo', source: 'configured' }] }
        else if (frame.method === 'worktrees.branches') payload = { branches: [{ name: 'main', kind: 'local' }], defaultBranch: 'main' }
        else if (frame.method === 'tasks.list') payload = { tasks: [{ id: 'task-1', title: 'Fixture task', status: taskCancelled ? 'cancelled' : 'running', sessionKey: String(frame.params.sessionKey) }] }
        else if (frame.method === 'tasks.get') payload = { task: { id: 'task-1', title: 'Fixture task', status: 'running', sessionKey: frame.params.sessionKey, prompt: '检查登录校验', result: '已定位需要补充的校验' } }
        else if (frame.method === 'tasks.cancel') { taskCancelled = true; payload = { found: true, cancelled: true } }
        else if (frame.method === 'artifacts.list') payload = { artifacts: [{ id: 'artifact-1', title: 'result.md', type: 'text', mimeType: 'text/markdown', sizeBytes: 14, sessionKey: String(frame.params.sessionKey), download: { mode: 'bytes' } }] }
        else if (frame.method === 'artifacts.get' || frame.method === 'artifacts.download') payload = { artifact: { id: 'artifact-1', title: 'result.md', type: 'text', mimeType: 'text/markdown', sizeBytes: 14, sessionKey: frame.params.sessionKey, download: { mode: 'bytes' } }, encoding: 'base64', data: btoa('Example report') }
        else if (frame.method === 'skills.status') {
          const managedAllowed = (window as unknown as { __managedAllowedSkills?: string[] }).__managedAllowedSkills
          const managedCatalog = [
            { skillKey: 'report', name: '阅读报告', description: '把文章整理成阅读报告', disabled: false, eligible: true, missing: { bins: [], env: [] }, install: [] },
            { skillKey: 'pdf', name: 'PDF 提取', description: '提取 PDF 内容', disabled: false, eligible: false, missing: { bins: ['pdftotext'], env: [] }, install: [] },
          ]
          payload = { skills: managedAllowed === undefined
            ? [{ ...managedCatalog[0], disabled: !skillEnabled, eligible: skillEnabled }]
            : managedCatalog.filter((skill) => managedAllowed.includes(skill.skillKey)) }
        }
        else if (frame.method === 'skills.update') { skillEnabled = frame.params.enabled === true; payload = { ok: true } }
        else if (frame.method === 'cron.list') payload = { jobs: [automation] }
        else if (frame.method === 'cron.status') payload = { enabled: true }
        else if (frame.method === 'cron.get' || frame.method === 'cron.add') payload = { job: automation }
        else if (frame.method === 'cron.update') { automation.enabled = (frame.params.patch as { enabled: boolean }).enabled; payload = { ok: true } }
        else if (frame.method === 'cron.run') payload = { runId: 'scheduled-run' }
        else if (frame.method === 'cron.runs') payload = { entries: [{ jobId: 'cron-1', runId: 'scheduled-run', ts: 1788570000000, completionStatus: 'succeeded', summary: '阅读摘要已生成' }] }
        window.setTimeout(() => this.emit('message', { data: JSON.stringify({ type: 'res', id: frame.id, ok: true, payload }) }), 0)
      }
      close() { this.readyState = 3; this.emit('close', { code: 1000 }) }
    }
    ;(window as unknown as { WebSocket: typeof WebSocket }).WebSocket = FixtureWebSocket as unknown as typeof WebSocket
  }, directory)
}
