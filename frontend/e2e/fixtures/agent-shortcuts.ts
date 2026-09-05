import type { Page } from '@playwright/test'

export async function installShortcutFixture(page: Page) {
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const path = new URL(route.request().url()).pathname
    const values: Record<string, unknown> = {
      '/api/auth/status': { authenticated: true, user: { id: 'shortcuts', username: 'fixture', display_name: '快捷交互验收', role: 'member', enabled: true } },
      '/api/me/agent-delegations': { enabled: true, connections: [], openclaw_chat: { enabled: true, default_gateway_url: 'ws://127.0.0.1:18789', protocol_version: 4 } },
      '/api/feed/latest': { schema_version: 2, items: [] }, '/api/catalog/sources': { sources: [] },
      '/api/me/source-health': { summary: { total: 0 }, items: [] }, '/api/jobs': { jobs: [] },
    }
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify({ ok: true, data: values[path] ?? {} }) })
  })
  await page.addInitScript(() => {
    sessionStorage.setItem('inteliscope.ui.insights-dismissed.v1:shortcuts', '1')
    const state = { requests: [] as Array<{ method: string; params: Record<string, unknown> }>, enabled: true, failSkills: false }
    ;(window as unknown as { shortcutFixture: typeof state }).shortcutFixture = state
    class MockSocket {
      readyState = 1
      listeners = new Map<string, Array<(event: unknown) => void>>()
      constructor() { setTimeout(() => { this.emit('open', {}); this.event('connect.challenge', { nonce: 'fixture' }) }, 0) }
      addEventListener(type: string, callback: (event: unknown) => void) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), callback]) }
      emit(type: string, event: unknown) { this.listeners.get(type)?.forEach((callback) => callback(event)) }
      event(event: string, payload: unknown) { this.emit('message', { data: JSON.stringify({ type: 'event', event, payload }) }) }
      close() { this.readyState = 3; this.emit('close', { code: 1000 }) }
      send(raw: string) {
        const frame = JSON.parse(raw)
        if (typeof frame.method !== 'string') return
        state.requests.push({ method: frame.method, params: frame.params })
        const methods = ['skills.status', 'sessions.create', 'sessions.list', 'sessions.preview', 'projects.list', 'worktrees.branches', 'sessions.patch']
        const payloads: Record<string, unknown> = {
          connect: { protocol: 4, auth: { role: 'operator', scopes: frame.params.scopes, deviceToken: 'fixture' }, snapshot: { sessionDefaults: { defaultAgentId: 'main' } }, features: { methods } },
          'sessions.create': { key: 'root' },
          'sessions.list': { sessions: [{ key: 'root', displayName: '快捷交互测试', totalTokens: 10, contextTokens: 100 }] },
          'sessions.preview': { previews: [{ key: 'root', status: 'empty', items: [] }] },
          'models.list': { models: [{ id: 'gpt', provider: 'openai', name: 'GPT Fixture', available: true, input: ['text'], reasoning: true }] },
          'agents.list': { defaultId: 'main', agents: [{ id: 'main', model: { primary: 'openai/gpt' } }] },
          'sessions.describe': { session: { key: 'root', modelProvider: 'openai', model: 'gpt' } },
          'tools.effective': { groups: [] }, 'chat.history': { messages: [] },
          'skills.status': { skills: [{ skillKey: 'weather', name: 'weather', description: '无副作用天气示例', disabled: !state.enabled, eligible: true, userInvocable: true, commandVisible: true, modelVisible: true, missing: {}, install: [] }] },
          'projects.list': { projects: [{ id: 'demo', displayName: 'Demo', repoRoot: '/demo', source: 'configured' }] },
          'worktrees.branches': { branches: [{ name: 'main', kind: 'local' }], defaultBranch: 'main' },
          'chat.send': { runId: frame.params.idempotencyKey },
        }
        setTimeout(() => {
          const failed = state.failSkills && frame.method === 'skills.status'
          this.emit('message', { data: JSON.stringify({ type: 'res', id: frame.id, ok: !failed, payload: payloads[frame.method] ?? { ok: true }, ...(failed ? { error: { code: 'UNAVAILABLE', message: 'SECRET_SENTINEL' } } : {}) }) })
          if (frame.method === 'chat.send') this.event('chat', { sessionKey: 'root', runId: frame.params.idempotencyKey, state: 'final', message: { role: 'assistant', content: [{ type: 'text', text: '模拟请求已完成' }] } })
        }, 0)
      }
    }
    ;(window as unknown as { WebSocket: typeof WebSocket }).WebSocket = MockSocket as unknown as typeof WebSocket
  })
}

export async function shortcutRequests(page: Page) {
  return page.evaluate(() => (window as unknown as { shortcutFixture: { requests: Array<{ method: string; params: Record<string, unknown> }> } }).shortcutFixture.requests)
}
