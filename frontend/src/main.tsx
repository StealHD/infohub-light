import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'

import { createApiClient } from './api/client'
import { createServiceApi } from './api/service'
import type { AuthStatus } from './api/types'
import { queryKeys } from './api/queryKeys'
import { AppRoutes } from './app/App'
import { clearUserCache } from './app/sessionCache'
import { UiProvider } from './ui'
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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <UiProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter><AppRoutes api={api} /></BrowserRouter>
      </QueryClientProvider>
    </UiProvider>
  </StrictMode>,
)
