import { describe, expect, it } from 'vitest'
import { acquireRuntime, validateSendSelection } from './openclawRuntimeGuard'
import { createOpenClawLifecycleRefs } from './openclawLifecycleRefs'
import { projectOpenClawRuntime } from '../chat/openclawRuntimeProjection'
import type { OpenClawSendSnapshot } from '../openclawContracts'

function snapshot(thinkingLevel: string | null, modelId = 'google/pro'): OpenClawSendSnapshot {
  return { displayText: 'test', gatewayPrompt: 'test', contextItems: [], idempotencyKey: 'test', modelId, thinkingLevel }
}

function pro() {
  const thinkingLevels = ['off', 'low', 'adaptive', 'high'].map((id) => ({ id, label: id }))
  return projectOpenClawRuntime({ models: [{ id: 'pro', provider: 'google', name: 'Pro', reasoning: true, thinkingLevels, thinkingDefault: 'adaptive' }] },
    { agents: [{ id: 'personal', model: { primary: 'google/pro' } }] },
    { session: { key: 'agent:personal:main', modelProvider: 'google', model: 'pro', thinkingLevels, thinkingDefault: 'adaptive' } },
    'personal', 'agent:personal:main')
}

describe('runtime operation boundary', () => {
  it('locks synchronously, including before React renders pending state', () => {
    const refs = createOpenClawLifecycleRefs()
    const release = acquireRuntime(refs)!
    expect(acquireRuntime(refs)).toBeNull()
    release()
    const next = acquireRuntime(refs)!
    release()
    expect(acquireRuntime(refs)).toBeNull()
    next()
    refs.run.pendingSend = true
    expect(acquireRuntime(refs)).toBeNull()
  })

  it('rejects inherited Flash medium and changed session model', () => {
    expect(() => validateSendSelection(snapshot('medium'), pro())).toThrow('推理强度')
    expect(() => validateSendSelection(snapshot('low', 'google/flash'), pro())).toThrow('会话模型已变化')
  })

  it('uses only the target model reported default and allows compatible retry snapshots', () => {
    expect(validateSendSelection(snapshot(null), pro())).toBe('adaptive')
    expect(validateSendSelection(snapshot('low'), pro())).toBe('low')
  })
})
