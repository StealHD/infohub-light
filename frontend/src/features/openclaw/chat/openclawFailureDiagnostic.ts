import { openClawSafeError } from './openclawSafeError'
import { safeModelIdentity } from './openclawModelSafety'
import { recordOf } from './openclawProjectionUtils'

export type OpenClawFailureDiagnostic = { code: string; runId?: string; actualModelId?: string }
const kinds: Record<string, string> = { rate_limit: 'MODEL_QUOTA_LIMITED', timeout: 'MODEL_CALL_TIMEOUT',
  context_length: 'MODEL_CONTEXT_LIMIT', refusal: 'MODEL_REFUSED' }
const identifier = (value: unknown) => typeof value === 'string' && /^[a-zA-Z0-9_.:-]{1,160}$/u.test(value) ? value : undefined

export function failureDiagnostic(value: unknown): OpenClawFailureDiagnostic {
  const source = recordOf(value) ?? {}
  const kind = typeof source.errorKind === 'string' && Object.hasOwn(kinds, source.errorKind) ? kinds[source.errorKind] : undefined
  const candidate = kind ?? (typeof source.errorCode === 'string' ? source.errorCode : source.code)
  const code = typeof candidate === 'string' && openClawSafeError(candidate) ? candidate : 'FAILURE_REASON_UNAVAILABLE'
  const actual = safeModelIdentity(source.provider, source.model)
    ?? (typeof source.actualModelId === 'string' ? safeModelIdentity(source.actualModelId.split('/')[0], source.actualModelId) : undefined)
  const runId = identifier(source.runId)
  return { code, ...(runId ? { runId } : {}), ...(actual ? { actualModelId: actual } : {}) }
}

export function failureText(text: string, diagnostic: OpenClawFailureDiagnostic): string {
  const placeholder = !text || text.trim() === 'The agent run failed before producing a reply.'
    || text.trim() === '[assistant turn failed before producing content]'
  return placeholder ? openClawSafeError(diagnostic.code)! : text
}

export function mergeFailureDiagnostic(local?: OpenClawFailureDiagnostic, remote?: OpenClawFailureDiagnostic): OpenClawFailureDiagnostic | undefined {
  if (!local) return remote
  if (!remote) return local
  return failureDiagnostic({ ...local, ...remote, runId: remote.runId ?? local.runId,
    actualModelId: remote.actualModelId ?? local.actualModelId,
    code: remote.code === 'FAILURE_REASON_UNAVAILABLE' ? local.code : remote.code })
}
