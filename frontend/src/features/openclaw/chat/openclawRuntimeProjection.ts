import type {
  OpenClawContextUsage,
  OpenClawModelOption,
  OpenClawRuntimeSelection,
  OpenClawThinkingOption,
} from '../openclawContracts'
import { recordOf, stringOf } from './openclawProjectionUtils'

function contextUsageRecord(value: unknown, expectedSessionKey: string): Record<string, unknown> | null {
  const root = recordOf(value)
  if (!root) return null
  if (Array.isArray(root.sessions)) {
    return root.sessions
      .map(recordOf)
      .find((candidate) => stringOf(candidate?.key ?? candidate?.sessionKey) === expectedSessionKey)
      ?? null
  }
  const session = recordOf(root.session) ?? root
  const sessionKey = stringOf(session.key ?? session.sessionKey ?? root.sessionKey)
  return sessionKey === expectedSessionKey ? session : null
}

export function contextUsagePayloadMatchesSession(value: unknown, expectedSessionKey: string): boolean {
  return contextUsageRecord(value, expectedSessionKey) !== null
}

export function projectOpenClawContextUsage(
  value: unknown,
  expectedSessionKey: string,
): OpenClawContextUsage | null {
  const session = contextUsageRecord(value, expectedSessionKey)
  if (!session || session.totalTokensFresh === false) return null
  const usedTokens = session.totalTokens
  const contextTokens = session.contextTokens
  if (
    typeof usedTokens !== 'number'
    || !Number.isFinite(usedTokens)
    || usedTokens <= 0
    || typeof contextTokens !== 'number'
    || !Number.isFinite(contextTokens)
    || contextTokens <= 0
  ) return null
  const provider = stringOf(session.modelProvider ?? session.provider)
  const model = stringOf(session.modelId ?? session.model)
  const modelId = model && provider && !model.includes('/') ? `${provider}/${model}` : model
  return {
    sessionKey: expectedSessionKey,
    usedTokens: Math.floor(usedTokens),
    contextTokens: Math.floor(contextTokens),
    percent: Math.min(999, Math.max(0, Math.round((usedTokens / contextTokens) * 100))),
    ...(modelId ? { modelId } : {}),
  }
}

function normalizeThinkingOptions(value: unknown): OpenClawThinkingOption[] {
  if (!Array.isArray(value)) return []
  const seen = new Set<string>()
  return value.flatMap((entry) => {
    const option = recordOf(entry)
    const id = stringOf(option?.id)
    const label = stringOf(option?.label)
    if (!id || !label || seen.has(id)) return []
    seen.add(id)
    return [{ id, label }]
  })
}

function normalizeModels(value: unknown): OpenClawModelOption[] {
  const root = recordOf(value)
  const entries = Array.isArray(root?.models) ? root.models : []
  const seen = new Set<string>()
  return entries.flatMap((entry) => {
    const model = recordOf(entry)
    if (!model) return []
    const rawId = stringOf(model.id)
    const provider = stringOf(model.provider)
    if (!rawId || !provider || model.available === false) return []
    const id = rawId.includes('/') ? rawId : `${provider}/${rawId}`
    const name = stringOf(model.name) ?? rawId
    if (seen.has(id)) return []
    seen.add(id)
    const contextWindow = typeof model.contextWindow === 'number' && Number.isFinite(model.contextWindow)
      ? Math.max(1, Math.floor(model.contextWindow))
      : undefined
    const thinkingLevels = normalizeThinkingOptions(model.thinkingLevels)
    const thinkingDefault = stringOf(model.thinkingDefault)
    const input = Array.isArray(model.input) ? model.input : []
    return [{
      id,
      name,
      provider,
      supportsImages: input.some((capability) => capability === 'image'),
      ...(stringOf(model.alias) ? { alias: stringOf(model.alias)! } : {}),
      ...(contextWindow ? { contextWindow } : {}),
      ...(typeof model.reasoning === 'boolean' ? { reasoning: model.reasoning } : {}),
      ...(thinkingLevels.length ? { thinkingLevels } : {}),
      ...(thinkingDefault && thinkingLevels.some((option) => option.id === thinkingDefault) ? { thinkingDefault } : {}),
    }]
  })
}

function matchingModelId(models: OpenClawModelOption[], provider: unknown, model: unknown): string | null {
  const modelName = stringOf(model)
  const providerName = stringOf(provider)
  if (!modelName) return null
  const full = providerName && !modelName.includes('/') ? `${providerName}/${modelName}` : modelName
  const exact = models.find((candidate) => candidate.id === full)?.id
    ?? models.find((candidate) => candidate.id === modelName)?.id
  if (exact) return exact
  if (providerName || modelName.includes('/')) return null
  const suffixMatches = models.filter((candidate) => candidate.id.endsWith(`/${modelName}`))
  return suffixMatches.length === 1 ? suffixMatches[0].id : null
}

export type OpenClawRuntimeProjection = {
  models: OpenClawModelOption[]
  thinkingOptions: OpenClawThinkingOption[]
  selection: OpenClawRuntimeSelection
  invalidSessionModel: boolean
}

export function projectOpenClawRuntime(
  modelsValue: unknown,
  agentsValue: unknown,
  sessionValue: unknown,
  requestedAgentId: string,
): OpenClawRuntimeProjection {
  const models = normalizeModels(modelsValue)
  const agentsRoot = recordOf(agentsValue)
  const agents = Array.isArray(agentsRoot?.agents) ? agentsRoot.agents : []
  const defaultAgentId = stringOf(agentsRoot?.defaultId)
  const agent = agents.map(recordOf).find((candidate) => (
    stringOf(candidate?.id) === requestedAgentId
    || (!agents.some((entry) => stringOf(recordOf(entry)?.id) === requestedAgentId) && stringOf(candidate?.id) === defaultAgentId)
  )) ?? null
  const agentModel = recordOf(agent?.model)
  const defaultModelId = matchingModelId(models, null, agentModel?.primary)
  const sessionRoot = recordOf(sessionValue)
  const session = recordOf(sessionRoot?.session) ?? sessionRoot
  const sessionThinkingOptions = normalizeThinkingOptions(session?.thinkingLevels)
  const matchedSessionModelId = matchingModelId(models, session?.modelProvider, session?.model)
  const hasExplicitSessionModel = Boolean(stringOf(session?.model))
  const defaultModelIsAvailable = Boolean(defaultModelId)
  const modelId = matchedSessionModelId ?? (!hasExplicitSessionModel && defaultModelIsAvailable ? defaultModelId : null)
  const selectedModel = models.find((candidate) => candidate.id === modelId)
  const modelThinkingOptions = selectedModel?.thinkingLevels ?? []
  const thinkingOptions = !selectedModel || selectedModel.reasoning === false
    ? []
    : modelThinkingOptions.length
      ? modelThinkingOptions
      : sessionThinkingOptions.length
        ? sessionThinkingOptions
        : []
  const rawDefaultThinkingLevel = selectedModel?.thinkingDefault ?? stringOf(session?.thinkingDefault)
  const defaultThinkingLevel = rawDefaultThinkingLevel && thinkingOptions.some((option) => option.id === rawDefaultThinkingLevel)
    ? rawDefaultThinkingLevel
    : null
  const sessionThinking = stringOf(session?.thinkingLevel)
  return {
    models,
    thinkingOptions,
    selection: {
      modelId,
      thinkingLevel: sessionThinking && thinkingOptions.some((option) => option.id === sessionThinking)
        ? sessionThinking
        : null,
      defaultModelId: defaultModelIsAvailable ? defaultModelId : null,
      defaultThinkingLevel,
    },
    invalidSessionModel: Boolean(hasExplicitSessionModel && !matchedSessionModelId),
  }
}
