import { useMemo } from 'react'
import type { informationAutomationApi } from '../../api/informationAutomationService'
import { useAgentConnectionContext } from '../agent-connection/AgentConnectionContext'

type InformationApi = ReturnType<typeof informationAutomationApi>
const methods = ['informationRules', 'informationRule', 'createInformationRule', 'updateInformationRule',
  'informationModels', 'refreshInformationModels', 'transitionInformationRule', 'testInformationRule', 'informationTestPreview', 'informationRuns'] as const satisfies readonly (keyof InformationApi)[]

export function useInformationContext() {
  const context = useAgentConnectionContext()
  const api = useMemo(() => {
    const information = Object.fromEntries(methods.map((name) => [name, async (...args: unknown[]) => {
      const loaded = await context.api.informationAutomations()
      return (loaded[name] as (...values: unknown[]) => Promise<unknown>)(...args)
    }])) as InformationApi
    return { ...context.api, ...information }
  }, [context.api])
  return { ...context, api }
}
