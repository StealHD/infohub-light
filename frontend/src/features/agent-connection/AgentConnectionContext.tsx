import { createContext, useContext } from 'react'
import type { ServiceApi } from '../../api/service'

const Context = createContext<{ api: ServiceApi; userId: string } | null>(null)
export const AgentConnectionProvider = Context.Provider
export function useAgentConnectionContext() {
  const value = useContext(Context)
  if (!value) throw new Error('Personal Agent requires an authenticated connection context')
  return value
}
