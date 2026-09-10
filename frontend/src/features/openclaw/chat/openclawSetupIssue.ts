import type { OpenClawSetupIssue } from '../openclawContracts'
import { GatewayRequestError } from '../openclawGateway'
import { isOpenClawSessionLabelConflict } from '../openclawSession'
import { openClawSafeError } from './openclawSafeError'

export class MissingOpenClawCredentialError extends Error {
  constructor() {
    super('当前地址尚未配对。请填写 OpenClaw Gateway token，完成首次连接。')
  }
}

export function runtimeFailureMessage(error: unknown, action: 'load' | 'switch'): string {
  const raw = error instanceof Error ? error.message : String(error)
  const fingerprint = raw.toLowerCase()
  if (fingerprint.includes('scope') || fingerprint.includes('operator.admin') || fingerprint.includes('permission')) {
    return action === 'switch'
      ? '当前连接权限不能直接修改旧会话，原对话已保留。'
      : '当前连接权限不足，无法读取 OpenClaw 运行设置。'
  }
  if (fingerprint.includes('context') || fingerprint.includes('too long') || fingerprint.includes('fork')) {
    return '当前对话过长，无法在保留上下文的同时切换模型。'
  }
  return action === 'switch'
    ? '未能切换模型，原对话已保留。'
    : '无法读取 OpenClaw 模型设置。'
}

const MISSING_SESSION_CODES = new Set(['NOT_FOUND', 'SESSION_NOT_FOUND', 'UNKNOWN_SESSION'])

export function isMissingOpenClawSession(error: unknown): boolean {
  if (!(error instanceof GatewayRequestError)) return false
  const code = error.code.trim().toUpperCase()
  if (MISSING_SESSION_CODES.has(code)) return true
  return code === 'INVALID_REQUEST'
    && /^unknown session key(?:\s|$)/iu.test(error.message.trim())
}

export function setupIssue(error: unknown): OpenClawSetupIssue {
  if (error instanceof MissingOpenClawCredentialError) return { kind: 'auth', message: error.message }
  const gatewayError = error instanceof GatewayRequestError
  const code = gatewayError ? error.code.toUpperCase() : ''
  const safeMessage = openClawSafeError(code)
  if (safeMessage) return { kind: 'unknown', message: safeMessage }
  const message = error instanceof Error ? error.message : String(error)
  const details = error instanceof GatewayRequestError && error.details && typeof error.details === 'object'
    ? error.details as Record<string, unknown>
    : {}
  const requestId = typeof details.requestId === 'string' && /^[A-Za-z0-9._:-]{1,128}$/u.test(details.requestId)
    ? details.requestId
    : undefined
  const fingerprint = gatewayError ? code.toLowerCase() : message.toLowerCase()
  if (isOpenClawSessionLabelConflict(error)) return { kind: 'session', message: 'OpenClaw 会话名称冲突，请重新连接。', requestId }
  if (isMissingOpenClawSession(error)) return { kind: 'session', message: '之前的 OpenClaw 会话已失效，请重新连接。' }
  if (fingerprint.includes('pairing_required') || (!gatewayError && fingerprint.includes('pairing required'))) return { kind: 'pairing', message: '这个浏览器需要在 OpenClaw 中批准设备配对。', requestId }
  if (fingerprint.includes('origin')) return { kind: 'origin', message: 'OpenClaw 尚未允许当前 Inscope 页面来源。' }
  if (fingerprint.includes('protocol')) return { kind: 'protocol', message: 'OpenClaw Gateway 协议版本不兼容，请升级到 2026.7.1 或更高兼容版本。' }
  if (fingerprint.includes('scope') || (!gatewayError && (fingerprint.includes('permission') || fingerprint.includes('权限')))) return { kind: 'permission', message: 'OpenClaw 返回的浏览器权限不符合最小权限要求。' }
  if (fingerprint.includes('unauthorized') || fingerprint.includes('invalid_token') || (!gatewayError && (fingerprint.includes('auth') || fingerprint.includes('token')))) return { kind: 'auth', message: 'OpenClaw Gateway token 无效或已轮换。' }
  if (fingerprint.includes('unavailable') || (!gatewayError && (fingerprint.includes('websocket') || fingerprint.includes('network') || fingerprint.includes('连接')))) return { kind: 'network', message: '无法连接 OpenClaw Gateway；浏览器可能还在等待本地网络权限。' }
  return { kind: 'unknown', message: 'OpenClaw 连接失败，请检查 Gateway 后重试。' }
}
