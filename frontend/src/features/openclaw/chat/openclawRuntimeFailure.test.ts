import { describe, expect, it } from 'vitest'
import { GatewayRequestError, OpenClawSocketClosedError } from '../openclawGateway'
import { runtimeFailureMessage } from './openclawSetupIssue'
import { OpenClawModelSwitchError, verifyModelSwitch } from './openclawModelSwitchError'
import type { OpenClawRuntimeProjection } from './openclawRuntimeProjection'

describe('model switch failure recovery', () => {
  it.each([
    ['MODEL_INHERITANCE_UNRESOLVED', 'Gateway 未能固定所选模型'],
    ['MODEL_SELECTION_MISMATCH', 'Gateway 返回的模型与选择不一致'],
    ['MODEL_SELECTION_UNVERIFIED', '无法确认新会话的模型'],
  ] as const)('preserves the typed %s reason', (code, message) => {
    const result = runtimeFailureMessage(new OpenClawModelSwitchError(code), 'switch')
    expect(result).toContain(message)
    expect(result.match(/原对话和输入已保留/g)).toHaveLength(1)
  })

  it.each([
    ['FORBIDDEN', '权限不足'], ['MODEL_CONTEXT_LIMIT', '对话过长'], ['TIMEOUT', '核对会话'],
  ])('uses the safe Gateway code %s', (code, message) => {
    const result = runtimeFailureMessage(new GatewayRequestError({ code, message: 'SECRET_SENTINEL' }), 'switch')
    expect(result).toContain(message)
    expect(result).not.toContain('SECRET_SENTINEL')
  })

  it('does not diagnose generic fork/context errors as excess context', () => {
    for (const message of ['fork failed SECRET_SENTINEL', 'context unavailable SECRET_SENTINEL']) {
      expect(runtimeFailureMessage(new GatewayRequestError({ code: 'INTERNAL', message }), 'switch'))
        .toBe('未能切换模型，请稍后重试。 原对话和输入已保留。')
    }
    expect(runtimeFailureMessage(new Error('transcript too large'), 'switch')).toContain('对话过长')
  })

  it('offers reconnection on socket closure without exposing the reason', () => {
    expect(runtimeFailureMessage(new OpenClawSocketClosedError({ code: 1006, reason: 'SECRET_SENTINEL' }), 'switch'))
      .toBe('连接已中断，请重新连接后核对会话。 原对话和输入已保留。')
  })

  it('requires verified selection and an exact model before activation', () => {
    const projection = { selection: { modelSafety: 'verified', modelId: 'deepseek/flash' }, invalidSessionModel: false } as OpenClawRuntimeProjection
    expect(() => verifyModelSwitch(projection, 'deepseek/flash')).not.toThrow()
    expect(() => verifyModelSwitch(projection, 'google/gemini')).toThrow('模型与选择不一致')
    expect(() => verifyModelSwitch({ ...projection, selection: { ...projection.selection, modelSafety: 'unknown' } }, 'deepseek/flash')).toThrow('无法确认')
    expect(() => verifyModelSwitch({ ...projection, selection: { ...projection.selection, modelSafety: 'unsafe_fork' } }, 'deepseek/flash')).toThrow('未能固定')
  })
})
