import { createContext, useContext } from 'react'
import type { OpenClawChatController } from '../openclawContracts'

export const OpenClawWorkspaceRuntimeContext = createContext<OpenClawChatController | null>(null)

export function useOpenClawWorkspaceRuntime(): OpenClawChatController {
  const value = useContext(OpenClawWorkspaceRuntimeContext)
  if (!value) throw new Error('useOpenClawWorkspaceRuntime must be used inside OpenClawWorkspaceRuntimeProvider')
  return value
}
