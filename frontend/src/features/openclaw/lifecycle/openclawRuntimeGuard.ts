import type { OpenClawLifecycleRefs } from './openclawLifecycleRefs'
import type { OpenClawRuntimeProjection } from '../chat/openclawRuntimeProjection'
import type { OpenClawSendSnapshot } from '../openclawContracts'

export function acquireRuntime(refs: OpenClawLifecycleRefs): (() => void) | null {
  if (refs.session.operation || refs.run.pendingSend || refs.run.runId) return null
  const owner = Symbol('runtime-operation')
  refs.session.operation = owner
  return () => { if (refs.session.operation === owner) delete refs.session.operation }
}

export class RuntimeSelectionError extends Error {}

export function validateSendSelection(snapshot: OpenClawSendSnapshot, projection: OpenClawRuntimeProjection): string | null {
  if (!snapshot.modelId || projection.invalidSessionModel || snapshot.modelId !== projection.selection.modelId) {
    throw new RuntimeSelectionError('会话模型已变化。内容已保留，请确认模型后重新发送。')
  }
  const thinking = snapshot.thinkingLevel ?? projection.selection.defaultThinkingLevel
  if (thinking && !projection.thinkingOptions.some((option) => option.id === thinking)) {
    throw new RuntimeSelectionError('当前模型不支持所选推理强度。内容已保留，请重新选择。')
  }
  return thinking
}
