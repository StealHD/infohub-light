import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

import { createApiClient } from './api/client'
import { queryKeys } from './api/queryKeys'
import { createServiceApi } from './api/service'
import type { AuthStatus } from './api/types'
import { AppRoutes } from './app/App'
import { clearUserCache } from './app/sessionCache'
import { DesignSystemProvider } from './design-system'
import './styles/global.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: false },
    mutations: { retry: false },
  },
})

const client = createApiClient({
  onUnauthorized: () => {
    const previous = queryClient.getQueryData<AuthStatus>(queryKeys.auth)?.user
    if (previous) void clearUserCache(queryClient, previous.id)
    queryClient.setQueryData<AuthStatus>(queryKeys.auth, { authenticated: false, user: null })
  },
})

const api = createServiceApi(client)

export function AppBootstrap() {
  return <QueryClientProvider client={queryClient}>
    <BrowserRouter>
      <DesignSystemProvider>
        <AppRoutes api={api} />
      </DesignSystemProvider>
    </BrowserRouter>
  </QueryClientProvider>
}
