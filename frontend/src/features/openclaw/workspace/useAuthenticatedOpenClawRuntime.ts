import { useQuery } from '@tanstack/react-query'

import type { ServiceApi } from '../../../api/service'
import { queryKeys } from '../../../api/queryKeys'
import { useOpenClawChat } from '../useOpenClawChat'

export function isOpenClawActivationRoute(pathname: string): boolean {
  return ['/feed', '/saved', '/history', '/subscriptions'].includes(pathname)
    || pathname === '/agent'
    || pathname.startsWith('/agent/')
}

export function useAuthenticatedOpenClawRuntime({
  api,
  userId,
  activated,
}: {
  api: ServiceApi
  userId: string
  activated: boolean
}) {
  const delegations = useQuery({
    queryKey: queryKeys.agentDelegations(userId),
    queryFn: ({ signal }) => api.agentDelegations(signal),
    retry: false,
    enabled: activated,
  })
  const settings = delegations.data?.openclaw_chat
  const chat = useOpenClawChat({
    enabled: activated && Boolean(settings?.enabled),
    imageIoEnabled: Boolean(settings?.image_io_enabled),
    mediaOrigins: settings?.media_origins ?? [],
    userId,
    defaultGatewayUrl: settings?.default_gateway_url ?? 'ws://127.0.0.1:18789',
  })
  return { chat, configLoading: activated && delegations.isLoading }
}
