import type { ApiClient } from './client'

export function deferredInformationApi(client: ApiClient) {
  return { informationAutomations: async () => (await import('./informationAutomationService')).informationAutomationApi(client) }
}
