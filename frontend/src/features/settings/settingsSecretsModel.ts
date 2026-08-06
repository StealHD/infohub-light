import { ApiError } from '../../api/client'
import type { ApifyKeyPoolMember, SecretRef } from '../../api/types'

export type SecretDraft = {
  name: string
  kind: string
  provider: string
  envName: string
  baseUrl: string
  value: string
}

export type SecretField = keyof SecretDraft
export type SecretFieldErrors = Partial<Record<SecretField, string>>

const secretEnvPattern = /^[A-Za-z_][A-Za-z0-9_]*$/
const secretProviders: Record<string, string[]> = {
  ai: ['gemini', 'openai', 'anthropic', 'deepseek'],
  apify: ['apify'],
}

export const emptySecretDraft: SecretDraft = { name: '', kind: 'ai', provider: '', envName: '', baseUrl: '', value: '' }
export const secretQuotaStaleTime = 5 * 60 * 1000

export const isApifySecret = (secret: SecretRef) => secret.kind === 'apify' || secret.provider === 'apify'

export function validateSecretDraft(draft: SecretDraft): SecretFieldErrors {
  const errors: SecretFieldErrors = {}
  const provider = draft.provider.trim().toLowerCase()
  if (!draft.name.trim()) errors.name = 'Key 名称不能为空。'
  if (!secretProviders[draft.kind]) errors.kind = '请选择有效的 Key 类型。'
  if (!provider) {
    errors.provider = 'Provider 不能为空。'
  } else if (!secretProviders[draft.kind]?.includes(provider)) {
    errors.provider = draft.kind === 'apify'
      ? 'Apify Key 的 Provider 必须是 apify。'
      : 'AI Key 的 Provider 仅支持 gemini、openai、anthropic 或 deepseek。'
  }
  if (!draft.envName.trim()) {
    errors.envName = '环境变量名不能为空。'
  } else if (!secretEnvPattern.test(draft.envName.trim())) {
    errors.envName = '环境变量名必须以字母或下划线开头，且只能包含字母、数字和下划线。'
  }
  const baseUrl = draft.baseUrl.trim()
  if (draft.kind !== 'ai' && baseUrl) {
    errors.baseUrl = '只有 AI Key 可以设置 Base URL。'
  } else if (baseUrl) {
    try {
      const parsed = new URL(baseUrl)
      if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.host || parsed.username || parsed.password || parsed.search || parsed.hash) {
        errors.baseUrl = 'Base URL 必须是无凭据、查询参数或片段的 http/https 地址。'
      }
    } catch {
      errors.baseUrl = 'Base URL 必须是有效的 http/https 地址。'
    }
  }
  if (!draft.value) {
    errors.value = 'Key 值不能为空。'
  } else if (draft.value.includes('\r') || draft.value.includes('\n') || draft.value.includes('\u0000')) {
    errors.value = 'Key 值必须为不含换行或空字符的单行文本。'
  } else if (draft.value.length > 4096) {
    errors.value = 'Key 值不能超过 4096 个字符。'
  }
  return errors
}

export function secretCreateErrorMessage(caught: unknown): string {
  if (!(caught instanceof ApiError)) {
    return caught instanceof Error && caught.message
      ? `网络请求失败：${caught.message}。请检查连接后重试。`
      : '网络请求失败，请检查连接后重试。'
  }
  if (caught.code === 'secret_env_conflict') return '环境变量名已被其他 Key 使用，请更换后重试。'
  if (caught.code === 'invalid_secret') {
    if (/provider/i.test(caught.message)) return 'Provider 与 Key 类型不匹配，请检查后重试。'
    if (/env|environment/i.test(caught.message)) return '环境变量名格式无效，请使用字母或下划线开头。'
    if (/empty|required/i.test(caught.message)) return '必填内容不能为空，请补充后重试。'
    if (/single|line|null/i.test(caught.message)) return 'Key 值必须为不含换行或空字符的单行文本。'
    if (/4096|exceed/i.test(caught.message)) return 'Key 值不能超过 4096 个字符。'
    return 'Key 元数据或值格式无效，请检查后重试。'
  }
  return caught.action ? `${caught.message} ${caught.action}` : caught.message
}

export const poolStatusLabels: Record<string, string> = {
  empty: '尚未配置 Key',
  ready: 'Ready',
  active: '运行中',
  draining: '正在安全排空',
  blocked: '已阻塞，等待人工核对',
  exhausted: '所有 Key 额度均已用尽',
  disabled: '尚未启用',
}

export const memberStatusPresentation: Record<ApifyKeyPoolMember['status'], {
  label: string
  tone: 'neutral' | 'success' | 'warning' | 'danger'
}> = {
  active: { label: '主用', tone: 'success' },
  standby: { label: '备用', tone: 'neutral' },
  draining: { label: '排空中', tone: 'warning' },
  depleted: { label: '额度已用尽', tone: 'warning' },
  invalid: { label: 'Key 无效', tone: 'danger' },
}

export const memberErrorLabels: Record<string, string> = {
  quota_exhausted: '额度不足，等待下个周期',
  apify_quota_exhausted: '额度不足，等待下个周期',
  apify_credits_depleted: '额度不足，等待下个周期',
  invalid_token: 'Key 无效，请排空后轮换',
  apify_invalid_token: 'Key 无效，请排空后轮换',
  apify_token_invalid: 'Key 无效，请排空后轮换',
  run_outcome_unknown: '启动结果未知，需要人工核对',
  apify_start_outcome_unknown: '启动结果未知，需要人工核对',
  apify_restart_start_outcome_unknown: '重启后启动结果未知，需要人工核对',
}

export function formatUsd(value: number) {
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'USD',
    currencyDisplay: 'narrowSymbol',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatCycleEnd(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '未知'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(date)
}

export function formatDateTime(value: string | null): string {
  if (!value) return '尚未记录'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '尚未记录'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
}

export function secretActionError(caught: unknown, fallback: string): string {
  return caught instanceof ApiError
    ? caught.message
    : caught instanceof Error && caught.message
      ? caught.message
      : fallback
}

export function apifyPoolActionError(caught: unknown, fallback: string): string {
  if (caught instanceof ApiError && (
    caught.code === 'apify_key_pool_generation_conflict'
    || caught.code === 'apify_key_pool_conflict'
  )) return 'Key 池刚刚发生变化，已刷新最新顺序，请重试。'
  return secretActionError(caught, fallback)
}
