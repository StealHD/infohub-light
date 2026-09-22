import type { OpenClawRuntimeProjection } from './openclawRuntimeProjection'

const messages = {
  MODEL_INHERITANCE_UNRESOLVED: 'Gateway 未能固定所选模型，暂无法保留上下文切换。请管理员检查模型继承兼容修复。',
  MODEL_SELECTION_MISMATCH: 'Gateway 返回的模型与选择不一致。请管理员检查模型配置后重试。',
  MODEL_SELECTION_UNVERIFIED: '无法确认新会话的模型。请重新连接后核对。',
} as const

export class OpenClawModelSwitchError extends Error {
  constructor(readonly code: keyof typeof messages) {
    super(messages[code])
    this.name = 'OpenClawModelSwitchError'
  }
}

export function verifyModelSwitch(projection: OpenClawRuntimeProjection, modelId: string): void {
  if (projection.selection.modelSafety === 'unsafe_fork') throw new OpenClawModelSwitchError('MODEL_INHERITANCE_UNRESOLVED')
  if (projection.selection.modelSafety !== 'verified') throw new OpenClawModelSwitchError('MODEL_SELECTION_UNVERIFIED')
  if (projection.invalidSessionModel || projection.selection.modelId !== modelId) throw new OpenClawModelSwitchError('MODEL_SELECTION_MISMATCH')
}
