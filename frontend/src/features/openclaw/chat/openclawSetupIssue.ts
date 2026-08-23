import type { OpenClawSetupIssue } from '../openclawContracts'
import { GatewayRequestError } from '../openclawGateway'
import { isOpenClawSessionLabelConflict } from '../openclawSession'

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

export function setupIssue(error: unknown): OpenClawSetupIssue {
  const code = error instanceof GatewayRequestError ? error.code : ''
  const message = error instanceof Error ? error.message : String(error)
  const details = error instanceof GatewayRequestError && error.details && typeof error.details === 'object'
    ? error.details as Record<string, unknown>
    : {}
  const requestId = typeof details.requestId === 'string' ? details.requestId : undefined
  const fingerprint = `${code} ${message}`.toLowerCase()
  if (isOpenClawSessionLabelConflict(error)) return { kind: 'session', message: 'OpenClaw 会话名称冲突，请重新连接。', requestId }
  if (fingerprint.includes('pairing_required') || fingerprint.includes('pairing required')) return { kind: 'pairing', message: '这个浏览器需要在 OpenClaw 中批准设备配对。', requestId }
  if (fingerprint.includes('origin')) return { kind: 'origin', message: 'OpenClaw 尚未允许当前 Inscope 页面来源。' }
  if (fingerprint.includes('protocol')) return { kind: 'protocol', message: 'OpenClaw Gateway 协议版本不兼容，请升级到 2026.7.1 或更高兼容版本。' }
  if (fingerprint.includes('scope') || fingerprint.includes('permission') || fingerprint.includes('权限')) return { kind: 'permission', message: 'OpenClaw 返回的浏览器权限不符合最小权限要求。' }
  if (fingerprint.includes('auth') || fingerprint.includes('token') || fingerprint.includes('unauthorized')) return { kind: 'auth', message: 'OpenClaw Gateway token 无效或已轮换。' }
  if (fingerprint.includes('websocket') || fingerprint.includes('network') || fingerprint.includes('连接')) return { kind: 'network', message: '无法连接 OpenClaw Gateway；浏览器可能还在等待本地网络权限。' }
  return { kind: 'unknown', message: message || 'OpenClaw 连接失败。' }
}

export function hasInteliscopeTools(value: unknown): boolean {
  try {
    if (JSON.stringify(value).toLowerCase().includes('inteliscope')) return true
  } catch {
    return false
  }
  const groups = value && typeof value === 'object' && Array.isArray((value as { groups?: unknown }).groups)
    ? (value as { groups: unknown[] }).groups
    : []
  return groups.some((group) => {
    if (!group || typeof group !== 'object' || !Array.isArray((group as { tools?: unknown }).tools)) return false
    return (group as { tools: unknown[] }).tools.some((tool) => {
      if (!tool || typeof tool !== 'object') return false
      const entry = tool as { id?: unknown; label?: unknown; source?: unknown }
      return entry.source === 'mcp' && `${String(entry.id || '')} ${String(entry.label || '')}`.toLowerCase().includes('inteliscope')
    })
  })
}
