import { describe, expect, it } from 'vitest'

import { GatewayRequestError } from '../openclawGateway'
import { setupIssue } from './openclawSetupIssue'

describe('OpenClaw public setup errors', () => {
  it('never exposes a raw Gateway secret sentinel or malformed request id', () => {
    const issue = setupIssue(new GatewayRequestError({ code: 'INTERNAL', message: 'SECRET_SENTINEL token=/private/path', details: { requestId: 'bad id SECRET_SENTINEL' } }))
    expect(issue.message).toBe('OpenClaw 连接失败，请检查 Gateway 后重试。')
    expect(JSON.stringify(issue)).not.toContain('SECRET_SENTINEL')
    expect(issue.requestId).toBeUndefined()
  })

  it('maps the Gateway invalid-request form for a missing session without exposing its key', () => {
    const issue = setupIssue(new GatewayRequestError({
      code: 'INVALID_REQUEST',
      message: 'unknown session key "agent:main:dashboard:SECRET_SESSION_KEY"',
    }))

    expect(issue).toEqual({ kind: 'session', message: '之前的 OpenClaw 会话已失效，请重新连接。' })
    expect(JSON.stringify(issue)).not.toContain('SECRET_SESSION_KEY')
  })
})
