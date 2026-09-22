import { GatewayRequestError, OpenClawSocketClosedError } from '../openclawGateway'
import { OpenClawModelSwitchError } from './openclawModelSwitchError'

function failureReason(error: unknown, action: 'load' | 'switch'): string {
  if (error instanceof OpenClawModelSwitchError) return error.message
  if (error instanceof OpenClawSocketClosedError) return '连接已中断，请重新连接后核对会话。'
  const code = error instanceof GatewayRequestError ? error.code.trim().toUpperCase() : ''
  if (['FORBIDDEN', 'PERMISSION_DENIED', 'MISSING_SCOPE', 'INSUFFICIENT_SCOPE'].includes(code)) {
    return '当前连接权限不足，请管理员检查会话操作权限。'
  }
  if (['MODEL_CONTEXT_LIMIT', 'CONTEXT_LENGTH_EXCEEDED'].includes(code)) {
    return '当前对话过长，无法在保留上下文的同时切换模型。'
  }
  if (['TIMEOUT', 'UNAVAILABLE', 'MODEL_CALL_TIMEOUT'].includes(code)) {
    return '请求未能确认完成，请重新连接后核对会话再重试。'
  }
  // Compatibility for older Gateways without specific error codes. Never echo raw errors.
  const raw = error instanceof Error ? error.message : ''
  if (/missing scope|operator\.admin|permission denied|insufficient scope/iu.test(raw)) {
    return '当前连接权限不足，请管理员检查会话操作权限。'
  }
  if (/context (?:length|window|limit)|(?:context|conversation|transcript).{0,32}too (?:long|large)/iu.test(raw)) {
    return '当前对话过长，无法在保留上下文的同时切换模型。'
  }
  return action === 'switch' ? '未能切换模型，请稍后重试。' : '无法读取 OpenClaw 模型设置，请重新连接后核对。'
}

export function runtimeFailureMessage(error: unknown, action: 'load' | 'switch'): string {
  const reason = failureReason(error, action)
  return action === 'switch' ? `${reason} 原对话和输入已保留。` : reason
}
